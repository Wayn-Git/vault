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
the docstring at the top of `psok/secrets.py`. The alternative, below, avoids it.

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

## What does not survive the split

Honest list, because finding these one at a time is worse.

- **The filesystem and shell tools reach the container, not your machine.**
  `read_file` on a deployed PSOK reads the container's disk. Anything about
  *your* files needs PSOK running where your files are.
- **stdio MCP connectors** spawn subprocesses in the container. A connector that
  is a local binary has to be installed in the image to exist at all.
- **OAuth sign-ins** need their redirect URL to be the Render host, registered
  with the provider — the loopback URL a laptop uses will not come back.
- **Reminders and automations run only while the service is up.** A free service
  that sleeps is not running, so a reminder due during a quiet spell arrives
  late, when something next wakes it. That is the same rule as on a laptop with
  the lid shut, but the lid closes far more often here.
