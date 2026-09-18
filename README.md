# 📚 Advanced Novel Name Translator Bot

Ek Telegram bot jo **Chinese / Asian novel** ke character naamon ko
**Indian / Desi naamon** mein badal deta hai. `.txt`, `.md`, `.docx`,
`.epub`, `.html` files support karta hai — formatting preserve karke.

---

## Render port timeout and character coverage update

The screenshot shows **build successful**, followed by:

```
Port scan timeout reached, no open ports detected.
Bind your service to at least one port.
```

This is a runtime port-binding failure, not a pip installation error. The
screenshot alone does not identify which pre-bind startup step stalled. The
updated startup binds **0.0.0.0:$PORT first**, before database/engine work and
Telegram connection. Database and engine initialization run off the HTTP event
loop. Unbuffered output and explicit bootstrap/stage logs show where a deployment
stops. Invalid ports and credentials fail explicitly rather than claiming readiness.

For an **existing manually created Render Web Service**, set these in its dashboard
(the Blueprint does not automatically change a manually configured service):

- Build command: `pip install -r requirements.txt`
- Start command: `python -u bot.py`
- Health check: `/health`
- Environment: `PYTHON_VERSION=3.11.9`, `PYTHONUNBUFFERED=1`, valid `API_ID`,
  `API_HASH`, `BOT_TOKEN`. Use Render's supplied `PORT`; fallback is `10000`.
- Merge the PR into the deployed branch, then **Manual Deploy -> Clear build
  cache & deploy**. Verify the new commit in Render's deploy view.

Expected order: `NovelBot bootstrap` -> `Starting NovelBot` ->
`Stage: bind_http` -> `HTTP listening on 0.0.0.0:...` -> `Stage: init_database` ->
`Stage: build_name_engine` -> `Stage: connect_telegram` -> `Stage: set_commands` ->
`Stage: ready` / `Telegram and translation engine ready`.

The bot forces line-buffered stdout itself, so these lines appear even if the
dashboard start command is plain `python bot.py`. While startup is in progress a
`Still starting: stage=... elapsed=...s` warning is logged every
`STARTUP_HEARTBEAT_S` seconds (default 20); the same `stage` is exposed in the
`/health` JSON. If Render still reports "no open ports detected", the log will
now show exactly which stage stalled (usually `connect_telegram` with invalid
credentials or a blocked region) instead of silence.

`/ping` returns 200 for HTTP liveness. `/health` and `/ready` intentionally return
503 until Telegram and the name engine are ready; do not change the health check
to `/ping` to conceal a broken Telegram connection. If the port warning persists,
share logs from **bootstrap onward**, without credentials. Local/offline tests do
not prove that a live Render service or its Telegram credentials work.

### Detailed character report

Each successful novel upload returns the translated file **and** a separate
`*.character_report.json`. It contains all dictionary-matched character entries
for that job (not the first 40 entries of the dictionary preview):

| Field | Meaning |
|---|---|
| `original_name` / `replacement_name` | Canonical original and chosen Indian name |
| `mapping_source` | Base dictionary or custom override |
| `occurrences` | Actual matched occurrences, including unchanged custom targets |
| `spellings_seen` | Exact matched spellings and their counts |
| `sample_locations` | Up to five source paragraph/chapter locations |
| `needs_review` | Unmapped candidate text, counts, sample context and location |
| `shared_replacement_names` | Different original entries sharing a target name; review for collisions/aliases |
| `summary` | Actual name/match counts and review-candidate totals |

Spaced, joined, hyphenated, case variants, repeated whitespace and smart
apostrophes are normalized. `Xiao Yan`, `Xiaoyan`, `XIAO-YAN` now use one target.
**Compatibility note:** joined spellings previously had their own generated
name; they now use the spaced canonical name. Use custom mappings to keep a
previous book's preferred choices. Each job freezes its dictionary snapshot so
an update during processing cannot change names halfway through a file.

DOCX matching covers split formatting runs, hyperlink text, nested/merged tables
and standard/first/even headers and footers. Replacement text inherits the first
text segment's formatting; surrounding text styles and embedded objects remain.
HTML/XHTML matching covers inline-tag splits and avoids scripts, styles, comments,
code/pre text and attributes. EPUB links/IDs/binaries are not name-replaced and
`mimetype` remains first and uncompressed. EPUB expansion is capped at 200 MiB
and 10,000 members, with no ZIP extraction to disk. TXT/HTML input must be UTF-8;
invalid bytes fail rather than silently deleting characters.

**No dictionary can guarantee that every character is recognized.** Unknown
nicknames, new names, alternate romanizations and unlisted languages may be
missed. The review heuristic looks for a known romanized surname followed by an
unmapped capitalized token, and Chinese-script text; these may also be places or
ordinary words. It is not AI entity recognition or a character-biography generator.
Review detail is capped at 5,000 candidates, with explicit overflow counts. Images,
DOCX text boxes/footnotes and markup attributes are outside the scan. TXT batching
is paragraph-based at about 64 KiB; a name split at a batch boundary may need review.

For best coverage, review the report, add each confirmed alias with the **same**
replacement, then resend the **original file**:

```text
/addmap Xiao Yan = Arjun Sharma
/addmap Young Master Xiao = Arjun Sharma
/addmap Yan-er = Arjun Sharma
```

Do not auto-map ambiguous short names/surnames without checking the novel. The
report is not an importable dictionary. Dictionary uploads still use flat JSON
string pairs and are shared service-wide, not private to each Telegram user.

---

## Render startup fix: one event loop

The reported error was:

```
RuntimeError: Task ... got Future ... attached to a different loop
```

The previous import-time shim created a loop for the Telegram client and its
handlers, but `asyncio.run(main())` created another loop for startup. Retrying
could not fix this mismatch. `run_bot()` now uses `asyncio.Runner` with the
**same loop** used by Kurigram, including handler registration and shutdown.
Do not replace this entrypoint with `asyncio.run(main())`.

### Reliability and safety improvements

- Configurable connection retry count and startup deadline. Network/server
  failures retry with exponential backoff and jitter; invalid credentials and
  programming errors fail immediately. Short Telegram FloodWaits are respected.
- A timed-out startup exits instead of reusing a possibly incomplete session;
  the hosting supervisor can restart it. Cleanup failure also prevents retries.
- SIGINT/SIGTERM interrupt startup, retry delays and normal operation. Telegram
  cleanup is time-bounded, and web resources are closed even on startup failure.
- `/health` and `/ready` return **503** until the engine and Telegram session
  are ready, and during a detected session disconnect. `/` gives JSON status;
  `/ping` is HTTP liveness only. No credentials are exposed in these responses.
- `/stats` and `/broadcast` are disabled when `ADMIN_ID` is unset or zero.
- JSON dictionaries obey the upload-size limit and accept at most 5,000
  non-empty string pairs per upload, with 200 characters per key/value. Database
  writes are transactional. Temporary filenames include the message ID to
  avoid collisions; file statistics increment only after successful upload.

### Existing Render service: redeploy steps

1. Merge the fix PR into the branch your Render service deploys (usually `main`).
2. In **Environment**, set `PYTHON_VERSION=3.11.9`, matching `.python-version`,
   `render.yaml` and `runtime.txt`. Render reads `.python-version`; `runtime.txt`
   alone is not its supported version selector. An existing dashboard
   `PYTHON_VERSION` takes precedence, and changing a Blueprint does not
   automatically configure a manually created service.
3. Verify `API_ID`, `API_HASH`, and `BOT_TOKEN`. Do not paste them into source
   code or public logs. Set your Telegram user ID as `ADMIN_ID` if needed.
4. Set build command to `pip install -r requirements.txt`, start command to
   `python -u bot.py`, and health-check path to `/health`.
5. Choose **Manual Deploy -> Clear build cache & deploy**. Confirm the Python
   version in logs, then wait for `Telegram and translation engine ready`.
6. Check `/health` returns HTTP 200 with `telegram_connected: true`, then send
   `/start`, `/ping`, and a small novel file in Telegram.

Render's free web service can still sleep during inactivity; these fixes do
not provide always-on hosting. SQLite dictionaries/stats remain service-wide
and require persistent storage to survive ephemeral-host redeploys.

### Offline regression tests

```bash
python -m unittest -v test_bot
```

Tests use the real Kurigram loop/handler registration plus mocked Telegram
calls for retries, timeouts, shutdown, health checks and access checks. They do
not contact Telegram; a successful live deployment must be verified separately.

---

## 🚀 Naye / Advanced Features

- **Single-loop lifecycle** — client, handlers aur startup ek hi event loop use karte hain.
- **Selective connect retry** — temporary network/server errors par bounded retries.
- 🛑 **Graceful shutdown** — SIGINT/SIGTERM par bot safely band hota hai
  (Render restart par clean).
- 🧾 **`.env` support** — local testing ke liye `.env` file (dekho
  `.env.example`).
- 🪵 **Read-only FS safe logging** — file na likh paye to bhi crash nahi.
- 📢 **Behtar broadcast** — FloodWait par retry, blocked users count,
  live progress.
- 🔢 **Safe config parsing** — galat env value par default use karega,
  crash nahi.
- ❤️ **Health endpoints** — `/`, `/health`, `/ping`.
- 🧠 **12,000+ deterministic** Chinese→Indian name mappings (same naam
  hamesha same result), gender-aware.

---

## ⚙️ Setup

### 1. Environment Variables (Render Dashboard → Environment)
| Variable    | Required | Description                                   |
|-------------|----------|-----------------------------------------------|
| `API_ID`    | ✅       | https://my.telegram.org se                    |
| `API_HASH`  | ✅       | https://my.telegram.org se                    |
| `BOT_TOKEN` | ✅       | @BotFather se                                 |
| `ADMIN_ID`  | ❌       | Aapka Telegram user id (/stats, /broadcast)   |
| `MAX_FILE_MB` | ❌     | Default `50`                                  |
| `RATE_LIMIT_S`| ❌     | Default `15`                                  |

### 2. Render par Deploy
- **Build Command:** `pip install -r requirements.txt`
- **Start Command:** `python -u bot.py`
- Free tier par **Web Service** chunein (bot ka health-check server
  `$PORT` par chalta hai). Ya `render.yaml` blueprint use karein.

### 3. Local Testing
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # apni values bharo
python bot.py
```

---

## 💬 Commands
`/start` `/help` `/addmap` `/mymap` `/clearmap` `/engine` `/ping`
`/stats` (admin) `/broadcast` (admin)

**Custom mapping:** `/addmap Xiao Yan = Arjun Sharma`
ya ek `.json` file bhejo: `{"Xiao Yan": "Arjun Sharma"}`
