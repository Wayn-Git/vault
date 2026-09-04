# Deploying PSOK

Two hosts: the interface on Vercel, the API on Render. They are joined by two
settings that must agree, and everything that goes wrong on a first deploy goes
wrong because one of them does not.

There is also a third option that is neither, and is worth reading first.

## Before you split it: you may not need to

`psok serve` serves the built interface and the API from one process on one
port. `npm run build` writes `frontend/dist`, and if that directory exists the
API mounts it — one process, one port, no CORS, no second deploy, no cold start
between the halves. On a laptop, on a home server, or on any single container
that stays up, that is the whole product.

The split below exists for one situation: the interface should be free and
instant on a CDN while the API is a small container that is allowed to sleep.
It costs a cold start and a CORS configuration. Take it deliberately.

## What runs where

| | Vercel | Render |
|---|---|---|
| serves | the built bundle, static | the FastAPI app |
| state | none | SQLite, config, skills, secrets — on a disk |
| config | `VITE_API_BASE`, at build time | `PSOK_HOME`, `PSOK_CORS_ORIGINS`, keys |

## The backend, on Render

`render.yaml` in the repository root is a blueprint: point Render at the repo,
choose **Blueprint**, and it reads that file. Three parts of it are load-bearing.

**The disk.** `PSOK_HOME=/var/psok`, mounted on a 1GB disk. A container's own
filesystem is discarded on every deploy and on every wake from idle, so without
this, every conversation, task, connector and key is gone by the next restart —
which on the free plan is roughly every fifteen minutes of quiet. This is the
setting people skip and then report as "it keeps logging me out".

**`PSOK_CORS_ORIGINS`.** Your Vercel origin, exactly: scheme and host, no
trailing slash, no path. Comma-separate to add preview deployments. There is no
wildcard and there will not be one — this API reads files and runs shell
commands, so "any page the user happens to visit" is not an acceptable set of
callers.

```
PSOK_CORS_ORIGINS=https://psok.vercel.app,https://psok-git-main-you.vercel.app
```

**`PSOK_SECRETS_FILE`.** A container has no OS keychain. Without this, adding a
provider key in the interface answers 503 and says so; with it, keys go to a
JSON file on the private disk, created 0600. That is a real reduction in
protection compared with a keychain and it is stated rather than hidden — see
the docstring at the top of `backend/secrets.py`. The alternative, below, avoids it.

**Provider keys.** Every preset now writes an `api_key_env` into
`providers.yaml`, so a key can arrive as an ordinary environment variable and
never touch a file at all:

```
ANTHROPIC_API_KEY=...
OPENAI_API_KEY=...
GROQ_API_KEY=...
```

The keychain reference is still checked first; the variable is the fallback. If
you set keys this way you can leave `PSOK_SECRETS_FILE` unset, and the only cost
is that the interface's "add a key" field stops working — which is the honest
trade, since there is nowhere safe for it to write.

One worker, deliberately. PSOK holds MCP subprocesses, the reminder loop and the
automation runner as process state; a second worker starts a second copy of all
three against one SQLite file.

## The frontend, on Vercel

`vercel.json` in the repository root builds `frontend/` and serves
`frontend/dist`. Import the repo and set one environment variable:

```
VITE_API_BASE=https://psok-api.onrender.com
```

Scheme and host, no trailing slash, no `/api` — `api.js` appends that. It is
read at **build** time, so changing it means redeploying the frontend, not
restarting anything.

Leave it unset and the bundle talks to `/api` on its own origin, which is what
the single-process build and `npm run dev` both want.

## The cold start, and what the interface does about it

A free Render service stops when nothing has asked it for anything, and the
request that wakes it waits out the boot — tens of seconds. Three things keep
that from reading as a broken deploy:

1. **The wake starts before React does.** `api.js` fires `GET /api/ping` while
   the module graph is still being evaluated, so the container is booting during
   parse and paint rather than after them. `/api/ping` and not `/api/health`:
   health surveys every configured provider over the network, and making a cold
   start wait for a boot *and* a round of probes is the wrong request to lead
   with.
2. **A preconnect goes out with it,** so DNS, TCP and TLS to the API host are
   done before the first byte of the first request.
3. **Nothing else is fetched until it answers.** The store holds the three
   opening calls behind the wake, and `App` renders `BootScreen` — which says
   what is happening and counts the seconds once the wait is worth mentioning —
   instead of mounting seven views that each fail and stay failed.

If the wake gets no answer for ninety seconds the screen says so and offers to
try again, rather than counting forever.

## Checking a deploy

```sh
curl -s https://psok-api.onrender.com/api/ping
# {"status":"ok","version":"0.1.0"}

# The preflight the browser will send. `access-control-allow-origin` has to come
# back with your Vercel origin on it; a 400 means PSOK_CORS_ORIGINS does not
# list it.
curl -si -X OPTIONS https://psok-api.onrender.com/api/ping \
  -H 'Origin: https://psok.vercel.app' \
  -H 'Access-Control-Request-Method: GET' | grep -i access-control
```

## Reaching PSOK from a phone, without publishing your shell

**PSOK has no authentication. That is a decision, not an omission** (ADR-0001):
the security model is that it is only reachable from the machine it runs on.
Every `/api` route assumes that — a public URL hands anyone who finds it your
filesystem, your shell and your mail.

There is exactly one endpoint built to be reached from elsewhere:

```
POST /api/share/capture     Authorization: Bearer <token>     {"url": "..."}
```

It can log a URL into the library and nothing else — no reads, no lists, no
tools. It does not exist until you make a token:

```bash
psok share-token --new        # shown once; stored in the OS keychain
psok share-token --revoke     # the endpoint returns 404 again
```

**A token is not a substitute for a proxy.** It protects one route; the other
fifty are untouched. If PSOK is reachable from the internet, publish that path
and nothing else:

```caddy
share.example.com {
    @capture path /api/share/capture
    handle @capture {
        reverse_proxy 127.0.0.1:8000
    }
    handle {
        respond 404
    }
}
```

The nginx equivalent is a `location = /api/share/capture` block with
`proxy_pass`, and a `location /` returning 404. Keep `psok serve` bound to
`127.0.0.1` so the proxy is the only way in — `psok serve --host 0.0.0.0` prints
a warning saying exactly this, and `psok doctor` reports whether a token exists.

On the phone, an iOS Shortcut or an Android sharing app posting JSON is enough:

```
URL     https://share.example.com/api/share/capture
Method  POST
Headers Authorization: Bearer <token>
Body    {"url": "<the shared link>"}
```

On the machine PSOK runs on you need none of this — the Library page's
bookmarklet opens `/library?url=…` with the link filled in, which is a
navigation rather than a cross-origin request, so nothing has to be switched on.

## Reaching it from everywhere, with Cloudflare

The Instagram webhook needs a stable public HTTPS address, and the library is
worth reading from a phone. Both are the same problem: **PSOK has no login and is
not meant to have one** (ADR-0001), so the identity has to sit in front of it.

Cloudflare Tunnel plus Cloudflare Access does that without changing a line of
PSOK. The tunnel gives a hostname with no port forwarding and no open inbound
port; Access puts a Google login in front of the whole thing, free for up to 50
users. You need a domain on Cloudflare (about £10 a year); a `trycloudflare.com`
quick tunnel is free but its hostname changes on every restart, which a webhook
cannot live with.

```bash
cloudflared tunnel login
cloudflared tunnel create psok
cloudflared tunnel route dns psok psok.example.com
```

`~/.cloudflared/config.yml`:

```yaml
tunnel: psok
credentials-file: /home/you/.cloudflared/<tunnel-id>.json
ingress:
  - hostname: psok.example.com
    service: http://127.0.0.1:8000
  - service: http_status:404
```

Point it at the one `psok serve` process, never the Vite dev server. Then in
Cloudflare Zero Trust:

1. An **Access application** covering `psok.example.com`, policy *Allow* → emails
   → your address. That is the login for the whole interface.
2. **One bypass policy**, for the exact path `/api/instagram/webhook`. Meta cannot
   log in, so that path is protected by its HMAC signature instead.

```bash
PSOK_CORS_ORIGINS=https://psok.example.com psok serve
```

### The rule, stated plainly

`/api/share/capture` and `/api/instagram/webhook` are the **only two** paths that
may ever be bypassed, and each carries its own credential — a bearer token and a
signature. Every other route runs shell commands, reads your files and reads your
mail, with no authentication at all.

A bypass on `/api/*`, or on a path *prefix* rather than an exact path, publishes
all of that to the internet. Widening it by one character is the whole risk.

Keep `psok serve` bound to `127.0.0.1` so the tunnel is the only way in.
`psok serve --host 0.0.0.0` prints a warning saying exactly this, and
`psok doctor` reports which of the two endpoints are switched on.

### On a phone

The library is just the site, behind the Access login. To *send* something without
opening it, an iOS Shortcut or an Android sharing app posting JSON is enough:

```
URL     https://psok.example.com/api/share/capture
Method  POST
Headers Authorization: Bearer <psok share-token --new>
Body    {"url": "<the shared link>"}
```

On the machine PSOK runs on you need none of this — the Library page's
bookmarklet opens it with the link filled in, which is a navigation rather than a
cross-origin request.

## What does not survive the split

Honest list, because finding these one at a time is worse.

- **The filesystem and shell tools reach the container, not your machine.**
  `read_file` on a deployed PSOK reads the container's disk. Anything about
  *your* files needs PSOK running where your files are.
- **stdio MCP connectors** spawn subprocesses in the container. A connector that
  is a local binary has to be installed in the image to exist at all.
- **OAuth sign-ins** need their redirect URL to be the Render host, registered
  with the provider — the loopback URL a laptop uses will not come back. For a
  connector that runs its *own* flow this is not a setting to change but a wall:
  `workspace-mcp` binds its callback listener on `localhost:8765` inside the
  container, so the browser that opened the Google page has nowhere to deliver
  the code to. The Google connectors are local-only until something else holds
  that callback.
- **Reminders have nowhere to arrive.** This is the one that surprises people,
  and it is not about the plan. `backend/notify.py` shells out to `notify-send`,
  `osascript` or `powershell` — it asks the platform what it has rather than
  assuming a desktop. A container has none of them, so `_notifier()` returns
  None, logs once, and drops the message. The loop still runs and still stamps
  `reminded_at`, so from the inside it looks like it worked. Until PSOK grows a
  delivery channel that is not a desktop session, a deployed reminder is a
  reminder nobody gets.

  Automations are the half that does survive, because their output is a
  conversation you can open and read rather than a notification you have to be
  present for. The journal is the same shape: a briefing and a review are rows
  you open, not notifications you have to be present for, so they survive the
  split as long as the service is up when their hour comes round.

- **Both loops run only while the service is up.** A free service that has
  spun down is not running either of them. An automation due during a quiet
  spell fires when something next wakes the container, not on time. Same rule
  as a laptop with the lid shut — the lid just closes far more often here.

- **A free service has no disk at all**, so `PSOK_HOME` is discarded on every
  spin-down. Provider keys given as environment variables survive (they are
  service config, not disk) and `providers.yaml` regenerates on boot with the
  `api_key_env` for each preset, so the agent can still answer. Tasks come back
  too, because To Do is the source of truth. Conversations, memory, the
  execution log and `mcp.yaml` — every connector added and its sign-in — do not.
  Do not set `PSOK_SECRETS_FILE` on a free service: it would accept a key into
  storage that is about to vanish, where leaving it unset gives an honest 503
  and points at the environment variable instead.
