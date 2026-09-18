# 📚 Advanced Novel Name Translator Bot

Ek Telegram bot jo **Chinese / Asian novel** ke character naamon ko
**Indian / Desi naamon** mein badal deta hai. `.txt`, `.md`, `.docx`,
`.epub`, `.html` files support karta hai — formatting preserve karke.

---

## 🔴 Render "Deploy Failed" wala error — FIXED ✅

Aapka bot Render par is error se crash ho raha tha:

```
RuntimeError: There is no current event loop in thread 'MainThread'
File ".../pyrogram/sync.py", line 33, in async_to_sync
    main_loop = asyncio.get_event_loop()
```

### Wajah (Root Cause)
- Purana **official `pyrogram`** (Dan wala) ab **maintain nahi hota**.
- Render ab **Python 3.13** use karta hai. Python 3.12+ mein
  `asyncio.get_event_loop()` ab loop auto-create nahi karta — seedha
  `RuntimeError` deta hai.
- Purana Pyrogram yeh call **import ke time** karta tha, isliye bot
  start hote hi mar jata tha (Exit status 1).

### Fix (kya badla)
1. **`requirements.txt`** — `pyrogram` ki jagah **`kurigram`** (actively
   maintained Pyrogram fork) use kiya. Yeh Python 3.12/3.13 par chalta
   hai aur event-loop bug fix karta hai. Import same rehta hai
   (`import pyrogram`), code change karne ki zaroorat nahi.
2. **`runtime.txt` + `render.yaml`** — Python `3.11.9` pin kiya (extra
   safety), taaki host apne aap koi tooti version na le aaye.
3. **`bot.py`** — top par ek **event-loop safety shim** add ki jo import
   se pehle hi loop bana deti hai — double protection.

---

## 🚀 Naye / Advanced Features

- ⚡ **Event-loop safety shim** — kisi bhi Python version par crash nahi.
- 🔁 **Connect retry** — Telegram se connect fail ho to 5 baar auto-retry.
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
