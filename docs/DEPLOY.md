# Deploying Parthenon at projectforty2.ai/parthenon

The public city runs today as one Docker container on the Project Forty2 DGX,
behind the gateway the site already uses for `/api` (see
[On the DGX](#on-the-dgx-how-it-runs-today)). The same image can instead run
as a Render **private service** from `render.yaml`, which the rest of this
document describes. Either way it is never reached directly: the site's edge
(the `chronos` web service, which serves projectforty2.ai) proxies
`/parthenon` and `/parthenon/*` to it.

It is a demo for the xAI team, so:

- **It runs on the owner's Grok subscription**, through the server's own
  sign-in (the bridge's OAuth device-code login, made once on the server).
  That also brings the portraits, the film and the voices. While the server
  has no sign-in it falls back to an API key if one is set, else to
  OpenRouter's free models.
- **An invite code gates making anything new**: beginning a gathering, every
  Symposium question, the Oracle's draft, portraits, a film, a stance reading
  and the voices. The owner hands the code to the xAI team.
- **Anyone with the link may walk the exhibits**, read-only: the gatherings,
  their Chronicles, films and portraits.
- The daily limits stay as a backstop.

```
visitor ── Cloudflare ── chronos (projectforty2.ai, observatory repo)
                             │  /parthenon/*  (P42_PARTHENON_ORIGIN)
                             ▼
              parthenon  (private service, Dockerfile.render)
              deploy/start.py
                ├─ bridge   127.0.0.1:5055  the models: the Grok sign-in,
                │                           the fallback keys
                └─ site     0.0.0.0:10000   waitress: API + built frontend
                             │
                          /data  (10 GB disk: gatherings, memory, exhibits,
                                  grok-oauth.json, the server's Grok sign-in)
```

What each file does:

| File | Role |
| --- | --- |
| `render.yaml` | The Blueprint: the private service, its disk and its settings. |
| `Dockerfile.render` | The image: the frontend built for `/parthenon/`, the backend from `backend/uv.lock` with the CPU build of torch, the bridge, and ffmpeg with the title card's fonts for the film. |
| `deploy/start.py` | The entrypoint: lays out `/data`, makes the Grok sign-in file the service user's, installs the exhibits once, starts the bridge, then the site, and stops both together. |
| `deploy/grok_signin.py` | Signs the server in to Grok (and out), says which provider it is on, and prints the invite link. |
| `deploy/serve.py` | Runs `backend/wsgi.py` with waitress (one process, 24 threads). |
| `deploy/seed_exhibits.py` | Installs the exhibits archive on the first boot. |
| `deploy/export_exhibits.py` | Makes that archive from the owner's own finished gatherings. |

## On the DGX (how it runs today)

```
visitor ── Cloudflare ── chronos (projectforty2.ai, observatory repo)
                             │  /parthenon/*  with the edge key (x-p42-edge-key),
                             │  to DGX_PUBLIC_GATEWAY_URL like /api
                             ▼
              DGX gateway (project42-public-gateway.service, 127.0.0.1:8812,
                           Tailscale Funnel :10000; 404 without the edge key)
                             │  /parthenon/* forwarded whole to PARTHENON_URL
                             ▼
              parthenon container  127.0.0.1:8830 → 10000  (this image)
                             │
                          ~/parthenon-data → /data
```

No new secret and no new public door: chronos already holds the edge key
and the gateway URL, and the gateway already refuses anything without the key.
The two changes that open `/parthenon` are in the observatory repo:
`backend/edge/app.py` (the route; `P42_PARTHENON_ORIGIN=off` turns it into a
404, a URL sends it to another origin instead) and
`deploy/dgx/public_gateway.py` (the forward; `PARTHENON_URL`, default
`http://127.0.0.1:8830`).

On the DGX (`ssh chronos@dgx-spark`):

| What | Where |
| --- | --- |
| Source | `~/parthenon` (a clone of this repository) |
| Image | `parthenon:demo`, built there (arm64) |
| Container | `parthenon`: `--restart unless-stopped --memory 12g --cpus 8`, loopback only |
| Data | `~/parthenon-data` (gatherings, memory, exhibits, `grok-oauth.json`) |
| Settings | `~/.config/parthenon/demo.env` (the admin key and the invite code; never committed) |
| Logs | `docker logs parthenon`; the sign-in and build logs in `~/parthenon-logs` |

To bring it up to date with `main`:

```bash
cd ~/parthenon && git pull --ff-only
docker build -f Dockerfile.render -t parthenon:demo . > ~/parthenon-logs/build.log 2>&1
docker rm -f parthenon
docker run -d --name parthenon --restart unless-stopped \
  -p 127.0.0.1:8830:10000 -v ~/parthenon-data:/data \
  --env-file ~/.config/parthenon/demo.env --memory 12g --cpus 8 parthenon:demo
```

The sign-in, the exhibits and the gatherings stay in `~/parthenon-data`, so a
new container carries on where the old one stopped (a night that was arguing
at that moment is stopped, as on Render). The commands in the owner's steps
below work here with `docker exec parthenon` in place of Render's Shell, for
example `docker exec -it parthenon python /app/deploy/grok_signin.py status`.
If the gateway's DGX checkout is ever reset, `public_gateway.py` must again be
the observatory version with the `/parthenon` forward, and the gateway
restarted (`systemctl --user restart project42-public-gateway.service`).

## Before the first deploy: the exhibits

The two finished gatherings, *When Sand Speaks* and *Socrates' Apology*, ship
with their portraits, films and Chronicles already made, so the steps are
furnished before anyone begins a gathering. They travel as one archive, made
on the owner's machine:

```bash
backend/.venv/bin/python deploy/export_exhibits.py --out ~/Desktop/exhibits --name exhibits-v1
```

This reads `backend/uploads` and the memory database strictly read-only and
writes `exhibits-v1.tar.gz` (about 61 MB, mostly the two films) and
`exhibits-v1.tar.gz.sha256`. Upload the archive as a release asset:

```bash
gh release create exhibits-v1 ~/Desktop/exhibits/exhibits-v1.tar.gz \
  --repo techno-optimist/parthenon --title "Exhibits v1" \
  --notes "The two finished gatherings the public site opens with."
```

`render.yaml` already points `PARTHENON_EXHIBITS_URL` at that asset and pins
`PARTHENON_EXHIBITS_SHA256`. If you export again, put the new digest (the
first word of the `.sha256` file) in `PARTHENON_EXHIBITS_SHA256`, or the boot
will refuse the archive.

The exhibits are installed once, when `/data/exhibits/manifest.json` does not
exist yet. Nothing already on the disk is ever overwritten. To install a new
set on a running service, delete that one marker file from a Render shell and
restart.

## The owner's steps

### 1. Launch the Blueprint

In the Render dashboard, **New > Blueprint**, pick `techno-optimist/parthenon`,
branch `main`. Render reads `render.yaml` and proposes one service,
`parthenon`: a private service, Docker, Oregon, Standard, with a 10 GB disk
at `/data`.

It asks for the keys marked `sync: false`:

- `OPENROUTER_API_KEY`: the fallback, OpenRouter's free models, used only
  while the server has no Grok sign-in. Paste it, so the city still answers
  if the sign-in ever goes.
- `XAI_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`: leave them empty. If
  one is set it is used instead of the free models while there is no Grok
  sign-in (the first of xAI, OpenAI, Anthropic).

**Apply.** The first build takes several minutes (the image is about 2 GB:
the Python environment 1.2 GB, the film tools 0.5 GB). On the first boot the
log shows

```
start: data /data; bridge 127.0.0.1:5055 (auto: openrouter); site 0.0.0.0:10000/parthenon/
start: no Grok sign-in in /data/grok-oauth.json yet; sign the server in with deploy/grok_signin.py signin (docs/DEPLOY.md)
exhibits: installed When Sand Speaks, Socrates' Apology: 112 files new, 0 kept, memory installed
```

Until step 3 the city answers on the free models, without portraits, film
or voices.

### 2. Find the invite code

Render generated `PARTHENON_INVITE_CODE`. On the service's page, open
**Environment** and reveal it. It is a random base64 value, something like
`B0jrphAPOY7pg92AN0c9MN4yecczLMdwnx4OkA1KFUk=`.

You may replace it with words of your own (`owl-of-athena`), or give several
codes separated by commas, one per group, so that one can be withdrawn
without the others. Saving a change restarts the service. With the variable
empty or removed, no invite is asked for and anyone may begin gatherings
within the daily limits.

`PARTHENON_ADMIN_KEY` was generated the same way: it is the keepers' key
(below), and it passes without an invite.

### 3. Sign the server in to Grok

The server gets its **own** sign-in. Never copy the Mac's
`~/.config/parthenon/grok-oauth.json` to it: xAI rotates the refresh token on
every refresh, so two holders of one grant sign each other out, and both the
Mac and the server would keep losing their sign-in. A second device-code
sign-in is a second grant, and the two live side by side.

Open a shell in the **running** service, with the Render CLI (`render login`
once, and choose the workspace):

```bash
render ssh parthenon
```

Never `render ssh --ephemeral`: an ephemeral instance has no disk, and the
helper refuses to sign it in. The **Shell** tab on the service's page in the
dashboard also opens a shell in the running instance.

In that shell (an SSH session does not carry the image's `PATH`, so name its
Python):

```bash
/app/backend/.venv/bin/python /app/deploy/grok_signin.py signin
```

It runs the bridge's own `login --no-browser` as the service user
(`parthenon`, uid 10001) with the server's sign-in file,
`/data/grok-oauth.json`, and prints a link and a code:

```
Sign in to Grok for Parthenon:
  1. Open https://accounts.x.ai/...
  2. Check the code matches: ABCD-EFGH
  3. Sign in with the account that has your SuperGrok / X Premium+ subscription and approve.
Waiting for approval...
```

Open the link on any device, check that the code matches, and approve with
the account that has the Grok subscription. The helper then makes the file
the service user's with mode 0600 and waits until the running bridge has
taken it up. No restart is needed:

```
The server is on the Grok subscription now: portraits, film and voices are on. No restart needed.
```

Confirm at any time with:

```bash
/app/backend/.venv/bin/python /app/deploy/grok_signin.py status
```

```
Provider:     grok-subscription: the Grok subscription (this server's own sign-in)
Signed in:    yes (Grok)
Features:     portraits on, film on, voice on
Invite:       required (1 code)
Sign-in file: /data/grok-oauth.json (parthenon, 0600)
```

`status` exits 0 only when the server is on the Grok subscription. It never
prints a token.

(Optional: the Hearing's graph building was paced for the free models when
the service started without a sign-in. A restart, **Manual Deploy > Restart
service**, lifts that pacing; nothing else needs it.)

### 4. Give chronos the private address

On the service's page, **Connect > Internal** shows its host and port, for
example `parthenon-abcd:10000`. On the **chronos** web service, set
`P42_PARTHENON_ORIGIN=http://parthenon-abcd:10000` and redeploy chronos. Both
services must be in the same workspace and region (Oregon). The edge must
pass the `X-Parthenon-*` request headers through, `X-Parthenon-Invite` among
them.

### 5. Check

- `https://projectforty2.ai/parthenon/healthz` answers `{"status": "ok", ...}`.
- `https://projectforty2.ai/parthenon/api/parthenon/status` shows
  `"provider": "grok-subscription"`, `features` all true and
  `"invite_required": true`.
- `https://projectforty2.ai/parthenon/` opens on the steps; walk an exhibit
  and play its film.

Private services take no health check path, so Render only knows the service
is up when its port is open; `/parthenon/healthz` is for you and the edge.

### 6. Hand the xAI team the link

```
https://projectforty2.ai/parthenon?invite=CODE
```

with the code escaped for a URL. A generated code is base64, and its `+`,
`/` and `=` must be written `%2B`, `%2F` and `%3D`. The helper prints the
link, escaped, for every code:

```bash
/app/backend/.venv/bin/python /app/deploy/grok_signin.py invite-link
```

or on your own machine:

```bash
python3 -c 'import sys, urllib.parse; print("https://projectforty2.ai/parthenon?invite=" + urllib.parse.quote(sys.argv[1], safe=""))' 'THE-CODE'
```

The page takes the code from the link, removes it from the address bar and
keeps it in that browser (`localStorage` `parthenon.invite`), so the link is
needed once per browser. Someone without it who tries to begin a gathering,
ask a question or have the Oracle draft is asked for the word they were
given, and may type the code in. The plain link,
`https://projectforty2.ai/parthenon`, is for anyone: the exhibits, read-only.

## The Grok sign-in

- **Where it lives**: `/data/grok-oauth.json` (`GROK_BRIDGE_TOKEN_FILE`), on
  the disk, owned by `parthenon`, mode 0600, with the bridge's
  `grok-oauth.json.lock` beside it. The bridge refreshes the access token
  itself and writes the rotated refresh token back to the same file.
- **Provider choice** (`PARTHENON_UPSTREAM=auto`): the Grok subscription when
  that file holds a usable sign-in; else the first of `XAI_API_KEY`,
  `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`; else OpenRouter's free models. The
  running bridge decides again when the file appears or goes, so signing in
  switches the server to Grok and signing out (or a revoked sign-in) falls
  back, without a restart. The bridge's `/health`, and the site's status,
  report `provider: grok-subscription` with images and voice on in that mode.
- **Signing out**: `grok_signin.py signout` deletes the sign-in; the server
  falls back at once and `status` says to what. If xAI stops accepting the
  sign-in (revoked in the xAI account, or the subscription ended), the bridge
  marks it revoked and falls back too. `signin` again brings it back.
- **At every boot** the entrypoint makes the file, when there is one, the
  service user's with mode 0600 (it never follows a link there), so a file
  written by root in a shell is repaired by a restart. `signin` does the same
  at once.
- **Backups**: Render's daily disk snapshots include the sign-in. A snapshot
  restored after the bridge has refreshed carries a refresh token xAI has
  already rotated away: sign in again after a restore.
- **Who can read it**: anyone who can open a shell on the service. Keep the
  Render workspace to the people who should hold the subscription.
- **Which Grok model**: the Symposium, the Scribe and the Oracle answer on
  grok-4.7 (`GROK_MODEL`, the bridge's default). The memory's graph building
  (the Hearing, about 130 s a window on grok-4.7) and the stance reading run
  on `LOCAL_MEMORY_LLM_MODEL`, `grok-4.20-0309-non-reasoning` in
  `render.yaml`, a fast non-reasoning model. A Grok name passes through on the
  subscription; on an API key or the free models the bridge puts that
  provider's own model in its place, so the fallback is unchanged.
- **Stopping never cuts a refresh short**: the bridge holds
  `grok-oauth.json.lock` from its refresh request until the rotated refresh
  token is on the disk. When the service stops, the entrypoint takes that
  lock (waiting up to 3 s for a refresh under way) before it stops the
  bridge, so a deploy or restart can never lose the one refresh token xAI
  will still accept.
- **If `render ssh` does not connect**: Render's SSH into a Docker service
  needs the running user's `~/.ssh` (mode 0700) in the container. The image
  runs as root and the entrypoint makes `/root/.ssh` at boot; the dashboard's
  Shell tab is the other way in.

## The invite

When `PARTHENON_INVITE_CODE` is set, these need the header
`X-Parthenon-Invite` with one of its codes (the page sends it; a link's
`?invite=` is accepted once and then kept by the page):

- beginning a gathering (`POST /api/graph/ontology/generate`, which hands
  out the owner's key);
- every Symposium question (the citizens' interviews, the one who had the
  floor, the Scribe's chat) and the Oracle's draft (`stage/draft`);
- starting portraits, a film or a stance reading, and the voices.

Reading never needs it: the exhibits, a gathering by its link, films,
portraits and Chronicles. The keepers' `X-Parthenon-Admin` passes without it.
A missing or wrong code is `403 {success: false, code: "invite_needed",
error}` in the city's words (English or Chinese); after
`PARTHENON_INVITE_TRIES_PER_HOUR` (10) wrong codes in an hour a visitor gets
`429 slow_down` until the hour turns. `GET /api/parthenon/status` says
`invite_required`.

## Long answers and Cloudflare

Cloudflare cuts any proxied request at 100 s (a 524), and grok-4.7 takes 25
to 110 s to answer in the Symposium; the Scribe's chat and the Oracle's draft
can take longer. So on the public steps a question does not hold the request:

- `POST` to a question route (the interviews, the speaker, the Scribe's
  chat, `stage/draft`) answers `202 {success: true, data: {ticket, status:
  "thinking"}}` at once, and the question is worked in a thread of its own
  for up to `PARTHENON_QUESTION_SECONDS` (240).
- The page reads `GET /api/parthenon/ticket/<id>` every 2 s (5 s after the
  first 30 s) until the answer is there, exactly as the route would have
  given it. Tickets live in memory for 30 minutes; a restart loses them, and
  the page says so calmly and keeps the question for asking again.
- Anything still answered within the request gives up after
  `PARTHENON_REQUEST_SECONDS` (85) with `503 slow_down`, under Cloudflare's
  cut.
- Beginning a gathering answers at once too; the scroll is read in a task
  the page follows.

## Featuring a gathering

Visitors' gatherings are unlisted: whoever has the link can watch and read
(and, with the invite, ask), and only the browser that began one can steer
it. The shelf shows the featured gatherings (the two exhibits to begin with)
and the visitor's own.

To put a gathering on the shelf for everyone, or take it off:

```bash
curl -X POST https://projectforty2.ai/parthenon/api/parthenon/featured \
  -H "X-Parthenon-Admin: $PARTHENON_ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"id": "sim_2c79002f1b0c", "featured": true}'
```

Any id of the gathering works (`proj_…`, `sim_…` or `report_…`, as in its
link); the whole gathering is featured. `"featured": false` takes it off.
`GET /parthenon/api/parthenon/featured` lists the shelf. The starting list is
`PARTHENON_FEATURED` (a comma list of ids; unset, the two exhibits).

## Raising the limits

Every limit is an environment variable on the service (in `render.yaml` with
its default). Change it under **Environment**; the service restarts with it.

| Variable | Default | What it limits |
| --- | --- | --- |
| `PARTHENON_INVITE_CODE` | generated | the codes that open speaking (comma separated; empty: no invite) |
| `PARTHENON_INVITE_TRIES_PER_HOUR` | 10 | wrong invite codes per visitor per hour |
| `PARTHENON_DAILY_GATHERINGS` | 12 | gatherings begun per day, site-wide |
| `PARTHENON_DAILY_PER_VISITOR` | 8 | gatherings per visitor per day |
| `PARTHENON_MAX_CITIZENS` | 12 | citizens summoned to one gathering |
| `PARTHENON_MAX_RUN` | `day` | the longest run a visitor may choose |
| `PARTHENON_CONCURRENT_RUNS` | 1 | nights argued, or squares left open, at the same time |
| `PARTHENON_IDLE_ENV_MINUTES` | 20 | how long a square left open after its night stays open unused |
| `PARTHENON_QUESTIONS_PER_HOUR` | 120 | Symposium questions per visitor per hour |
| `PARTHENON_QUESTION_SECONDS` | 240 | how long one question (a ticket) may think |
| `PARTHENON_REQUEST_SECONDS` | 85 | how long a request may wait on the model (under Cloudflare's 100) |
| `PARTHENON_MAX_SCROLL_CHARS` | 20000 | the length of a visitor's own scroll |

A visitor is known by the address Cloudflare reports (`CF-Connecting-IP`,
trusted because `PARTHENON_TRUST_PROXY=1`). So a team behind one office
address is one visitor: everyone there shares the 8 gatherings a day and the
120 questions an hour (and the 10 wrong invite codes an hour). The Blueprint
sets these two for a team, since the invite already decides who may speak;
the site-wide `PARTHENON_DAILY_GATHERINGS` (12) and
`PARTHENON_CONCURRENT_RUNS` (1) stay the backstop. If the team runs into
them (`429 come_back_tomorrow` for gatherings, `429 slow_down` for
questions, in the city's words), raise the per-visitor two.

Before raising `PARTHENON_CONCURRENT_RUNS`, look at memory. The Standard plan
has 2 GB, and it holds **one run or one open environment**: a running night
is the heaviest thing the service does (the simulator loads a 1.1 GB
recommendation model, twhin-bert, on the CPU; it is downloaded once into
`/data/cache` on the first run), and a square left open after its night, so
its citizens can still be questioned live, holds about 1 GB too. An open
square takes a seat of `PARTHENON_CONCURRENT_RUNS`; a new night closes the
least recently used idle one, and idle ones close after
`PARTHENON_IDLE_ENV_MINUTES`. Raise the limit only on the Pro plan (4 GB) or
larger. If the service restarts with an out-of-memory event during a night,
move it to Pro.

Without a Grok sign-in the free OpenRouter models also pace the city: about
20 requests a minute and a daily cap per key.

## Operating it

- **Logs**: the service's Logs tab shows the entrypoint (`start:`), the
  exhibits (`exhibits:`), the bridge and the backend. The backend's own daily
  files are in `/data/logs` (kept 14 days, `PARTHENON_LOG_DAYS`).
- **Deploys** stop the old instance before the new one starts (a service with
  a disk runs one instance): a short downtime, and a night that
  is arguing at that moment is stopped, as are the questions still thinking.
  Render allows 30 s between its SIGTERM and its SIGKILL, and the entrypoint
  uses them in two turns. The backend goes first, so it can close the run
  while the bridge still answers; after `PARTHENON_STOP_TIMEOUT` (20 s) it is
  killed alone (a Gathering being prepared can hold it that long, waiting on
  the model). Then the bridge: the entrypoint waits for any Grok token
  refresh under way (above), sends it SIGTERM, and kills it only after
  `PARTHENON_BRIDGE_STOP_TIMEOUT` (5 s). The Grok sign-in stays on the disk.
- **Backups**: Render snapshots the disk daily. Everything the city keeps is
  under `/data/uploads` (gatherings and `memory/local_memory.sqlite3`),
  `/data/parthenon_public.sqlite3` (the day's counts and the featured list)
  and `/data/grok-oauth.json` (see above about restoring it).
- **The film tools**: ffmpeg, ffprobe and the DejaVu and Noto CJK fonts
  (about 540 MB of the image) are there for the film, which the Grok sign-in
  (or an xAI key) makes possible. To build without them, set
  `PARTHENON_FILM_TOOLS` (in `render.yaml` as `1`) to `0` under
  **Environment**: Render passes it to the build, and the next image leaves
  them out. `GET /parthenon/api/parthenon/status` then reports
  `features.film: false` even when signed in; set it back to `1` and
  redeploy to bring them back.
- **Settings the entrypoint fills in** (only when you have not set them):
  `GROK_BRIDGE_TOKEN_FILE` (`<data>/grok-oauth.json`), `LLM_BASE_URL` (the
  bridge), `LLM_API_KEY`, `LLM_MODEL_NAME` (`parthenon-free`; the bridge puts
  the provider's model in its place), `MEMORY_BACKEND=local`,
  `LOCAL_MEMORY_DB_PATH`, `HF_HOME`, `PARTHENON_FRONTEND_DIR`, and
  `LOCAL_MEMORY_LLM_MIN_INTERVAL_SECONDS=3.5` when the service starts on the
  free models. The bridge always listens on 127.0.0.1 only.

## Trying the image without Render

```bash
docker build -f Dockerfile.render -t parthenon-public .
# (add --build-arg PARTHENON_FILM_TOOLS=0 for an image without ffmpeg)
docker run --rm --name parthenon -p 10000:10000 -v parthenon-data:/data \
  -e OPENROUTER_API_KEY=... -e PARTHENON_ADMIN_KEY=choose-one \
  -e PARTHENON_INVITE_CODE=choose-a-word \
  -e PARTHENON_EXHIBITS_URL=https://github.com/techno-optimist/parthenon/releases/download/exhibits-v1/exhibits-v1.tar.gz \
  parthenon-public
# then http://localhost:10000/parthenon/?invite=choose-a-word
```

To sign that container in to Grok (its own grant, like the server's):

```bash
docker exec -it parthenon /app/backend/.venv/bin/python /app/deploy/grok_signin.py signin
```

Without Docker, the same entrypoint runs from a copy of the app (never from
the working tree, whose `backend/uploads` it refuses to hide):
`PARTHENON_DATA_DIR=/tmp/parthenon-data PORT=8091 python deploy/start.py`.
`grok_signin.py` refuses to run beside a `.env`, so it never signs in over
the owner's own machine; there, `npm run grok:login` is the sign-in.

The deploy tests: `cd backend && .venv/bin/python -m pytest -q ../deploy/tests`.
