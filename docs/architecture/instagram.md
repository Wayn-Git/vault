# Instagram capture

Send a reel to an Instagram account and it lands in the library — the mechanic
savetolist.com has, built on Meta's own API rather than reverse-engineered.

`backend/instagram/` — `signature.py` (the security boundary), `webhook.py`
(parsing), `client.py` (Graph), `store.py` (the queue), `service.py` (decisions),
`runner.py` (the drain).

## Three routes, and they are not equal

This is the thing to understand before anything else, because it decides how
useful a saved item is.

| route | what Instagram actually gives you |
|---|---|
| **mention** — someone comments `@your.account` on a post | a `media_id`, which Graph turns into **the real permalink and the full caption**. The route worth using. |
| **dm_reel / dm_share** — the reel sent as a direct message | a title and an expiring `lookaside.fbsbx.com` asset needing the access token. **No permalink. No caption.** |
| **dm_link** — an instagram.com link pasted as message text | a permalink, and nothing else. Instagram will not serve the page behind it. |

A fourth outcome is not a route: Meta passes some shares through as an
`UNSUPPORTED` message carrying nothing recoverable. Those are recorded and
ignored, never turned into an item invented from the little that arrived.

The lookaside URL is deliberately **not** stored as the item's `url`. It is an
expiring file, not an address anybody can follow later, and putting it there
would show a dead link as though it worked.

## Nothing is invented

A direct-message reel arrives with a title and no words. Asking a model what it
is "about" would be fabrication from a filename, and the fabrication would sit on
the page looking exactly like a real summary.

So the guard is **structural**: `library_items.text_source == 'none'` makes
`enrich_text` return before a model client is even resolved, and
`tests/test_enrichment.py` asserts the model is *never called* rather than called
and ignored. A prompt instruction can be softened by a later edit; a return
cannot.

What a reel with no caption gets instead is a sentence saying so, on the item,
where the summary would have been.

## Transcription is what closes the gap

A DM'd reel has no text until its audio has one. `backend/media/` downloads and
extracts (ffmpeg, through the sandbox); `backend/runtime/transcribe.py` posts it
to a configured provider — Groq's `whisper-large-v3-turbo` or OpenAI's
`whisper-1`, chosen by an explicit `transcription:` block in `providers.yaml`
else a short allowlist.

Every gate is checked before the step it protects, and the order matters:

1. no ffmpeg → say so, download nothing
2. no transcriber → **the video is never fetched at all**, because there would
   be nothing to do with it
3. `max_video_mb` — enforced *during* the stream, since `content-length` can lie
4. `max_duration_seconds` (15 min) → stop before extracting
5. audio over 24 MB → stated, not silently truncated. Splitting long recordings
   is real work and is not done here.

24 kbps mono opus is ~11 MB an hour, which is why the fifteen-minute cap lands
under the upload limit. The two numbers are chosen together.

A transcript is what was *heard*, not what was *meant*. A reel that is mostly
licensed music transcribes to very little, and the `MIN_INDEXABLE_CHARS` floor
treats that as no transcript rather than a bad one.

## The queue, and why the acknowledgement means "written down"

Meta wants a 200 within seconds and retries anything else for hours. The work
behind one delivery takes minutes. A `BackgroundTasks` callback dies with the
process, so a crash between the acknowledgement and the capture would be a reel
the user watched Instagram accept and then never saw — with no retry, because we
already said 200.

So `instagram_events` is a table and `InstagramRunner` drains it. The route does
one HMAC, one JSON parse and one indexed insert, then nudges the runner. The
nudge is what keeps the expiring asset fresh; the 5-second timeout is what
recovers a queue left behind by a crash, together with `reclaim_stale`.

Inside `IngestService.process` the **library row is created as early as
possible**, and the download, the transcription, the enrichment and the reply are
each wrapped so a failure writes a sentence into `capture_note` and carries on.
The item survives all of them failing — the library's existing rule, unchanged.

## Security

**Its only authentication is the HMAC signature**, because Meta will not send a
bearer token. Consequences:

- The signature is verified over the **raw request bytes**. A Pydantic model is
  deliberately *not* a route parameter: FastAPI would consume and re-encode the
  body, and a re-serialised body is not what Meta signed. `tests/test_instagram_webhook.py`
  pins this, and fails the moment somebody adds that parameter.
- The route **404s** when unconfigured or switched off. An endpoint that answers
  401 is an endpoint worth guessing at.
- `delivery_key` is UNIQUE, so a Meta retry and a replay are the same thing:
  nothing inserted, still a 200. A freshness window on `entry.time` is the belt
  to that braces.
- **The sender allowlist is empty by default and nothing is ingested.** Anyone can
  message a public professional account. An unknown sender's delivery is recorded
  as `ignored` with the id, and the interface offers "allow them?" — an IGSID is
  an opaque number nobody can look up, so the only workable way to fill the list
  is from a message that actually arrived.
- Media URLs arrive in an attacker-influenced payload, so `backend/media/download.py`
  runs `check_url_async` on every redirect hop **and** requires the host to be one
  of Instagram's four.
- The access token travels in an `Authorization` header, never `?access_token=`,
  so it stays out of proxy logs.

## Timestamps

Meta sends `entry.time` in **seconds** and `messaging[].timestamp` in
**milliseconds**, in the same delivery, and nothing in the payload says so.
Comparing the second against a seconds clock makes every direct message look
decades old, which the freshness window then silently drops — a feature that
appears to do nothing at all. `webhook._seconds` normalises it.

## Setup

No Facebook Page (Instagram API with Instagram Login), and **no App Review or
Business Verification** — a Meta app in *Development* mode works for its own
admin, developers and testers, which is this single-user case exactly.

What silently does nothing when missed:

1. The receiving account must be **Professional** (Business or Creator).
2. The personal account doing the DMing must be a **tester**, and the invite must
   be **accepted** in Instagram → Settings → Apps and websites → Tester invites.
3. Scopes: `instagram_business_basic`, `instagram_business_manage_messages`,
   `instagram_business_manage_comments`.

Mentions do not fire for media owned by private accounts, and their assets 403.

The long-lived token lasts 60 days and refreshes **only while still valid**. The
runner checks once a day and refreshes at 14 days remaining; once lapsed there is
no automatic recovery, so it is surfaced in `psok doctor`, in the panel, and as a
desktop notification before that happens.

Nothing arrives while PSOK is shut. Same rule as automations, for the same
reason.

## Trying it without Meta

```bash
psok instagram credentials --app-secret ... --verify-token ... --access-token ... --owner-id ...
psok instagram enable
psok instagram senders --allow <your IGSID>
psok instagram send-sample --route dm-reel      # a correctly signed delivery
psok instagram queue
```

`send-sample` shares its fixtures with the tests, so the manual loop and the
suite cannot drift apart.
