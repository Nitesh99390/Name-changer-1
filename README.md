# 📚 Advanced Novel Name Translator Bot

Ek Telegram bot jo **Chinese / Asian novel** ke character naamon ko
**Indian / Desi naamon** mein badal deta hai. `.txt`, `.md`, `.docx`,
`.epub`, `.html` files support karta hai — formatting preserve karke.

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
   `python bot.py`, and health-check path to `/health`.
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
- **Start Command:** `python bot.py`
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
