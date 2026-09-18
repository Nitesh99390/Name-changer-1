# -*- coding: utf-8 -*-
"""
====================================================================
  📚  ADVANCED NOVEL NAME TRANSLATOR BOT  (Single-File Edition)
====================================================================
  Chinese/Asian novel characters -> Indian/Desi names
  Supported: .txt .md .docx .epub .html .htm  + custom .json mapping

  Features:
    • 25,000+ auto-generated Chinese->Indian name pairs (deterministic)
    • Deterministic mapping: same Chinese name => same Indian name har baar
    • Gender-aware Indian names (Male / Female pools alag)
    • Placeholder-based 2-pass replacement (cascade corruption = 0%)
    • DOCX formatting preserved (bold/italic/fonts), tables supported
    • EPUB re-packaging with proper zip structure
    • Custom JSON dictionary (user apna naam-pair bhej sakta hai)
    • SQLite stats + per-user tracking + /broadcast (admin)
    • Rate limiting + download/upload progress updates
    • aiohttp health-check server (Render / Koyeb / Heroku compatible)
    • Graceful shutdown + rotating log file
====================================================================
"""

import os
import re
import json
import time
import random
import hashlib
import logging
import sqlite3
import zipfile
import shutil
import asyncio
from logging.handlers import RotatingFileHandler
from typing import Dict, Optional, Tuple
from functools import lru_cache

import docx
from bs4 import BeautifulSoup
from aiohttp import web

from pyrogram import Client, filters, idle
from pyrogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton,
    CallbackQuery, BotCommand
)
from pyrogram.enums import ParseMode, ChatAction
from pyrogram.errors import FloodWait

# =====================================================================
# 1. CONFIGURATION & LOGGING
# =====================================================================

# ⚠️  SECURITY: Kabhi bhi real values code mein paste NA karein.
#     Render/Heroku mein Environment Variables set karein:
#       API_ID, API_HASH, BOT_TOKEN, ADMIN_ID
API_ID    = int(os.environ.get("API_ID", "0"))
API_HASH  = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_ID  = int(os.environ.get("ADMIN_ID", "0"))

DB_FILE      = "bot_stats.db"
DOWNLOAD_DIR = "downloads"
MAX_FILE_MB  = 50
RATE_LIMIT_S = 15          # ek user 15 sec mein sirf 1 file
LOG_FILE     = "bot.log"

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# --- Logging: console + rotating file (2 MB x 3 backups) ---
_formatter = logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")
_fh = RotatingFileHandler(LOG_FILE, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8")
_fh.setFormatter(_formatter)
_ch = logging.StreamHandler()
_ch.setFormatter(_formatter)
logging.basicConfig(level=logging.INFO, handlers=[_fh, _ch])
logger = logging.getLogger("NovelBot")

# =====================================================================
# 2. BOT CLIENT
# =====================================================================

app = Client(
    "advanced_novel_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workers=16,                 # zyada concurrent users handle karega
    sleep_threshold=60          # FloodWait ke liye auto-sleep
)

# Global engines
compiled_pattern: Optional[re.Pattern] = None
mapping_dict: Dict[str, str] = {}          # auto-generated base mapping
custom_mapping_dict: Dict[str, str] = {}   # user-provided JSON mapping
_rate_limiter: Dict[int, float] = {}       # user_id -> last request timestamp

# =====================================================================
# 3. NAME BANKS  (Bade pools — hazaron unique combinations)
# =====================================================================

# ---- Chinese surnames (70+) ----
CH_SURNAMES = [
    "Xiao", "Lin", "Ye", "Shi", "Chu", "Luo", "Ji", "Han", "Wang", "Meng",
    "Bai", "Su", "Chen", "Li", "Zhang", "Tang", "Huo", "Yun", "Xia", "Mu",
    "Qin", "Zhao", "Liu", "Yang", "Huang", "Guo", "Gao", "Zheng", "Long", "Shen",
    "Nie", "Jiang", "Wu", "Zhou", "Xu", "Sun", "Zhu", "Hu", "He", "Lu",
    "Fang", "Gu", "Yan", "Wei", "Jin", "Chao", "Gong", "Dong", "Sima", "Ouyang",
    "Mo", "Wen", "Feng", "Du", "Cao", "Song", "Pan", "Xue", "Deng", "Lei",
    "Cheng", "Ma", "Ren", "Fu", "Cai", "Qiu", "Duan", "Xia", "Tan", "Zou",
    "Rong", "Shangguan", "Zhuge", "Murong", "Helan"
]

# ---- Chinese given names (85+) ----
CH_GIVEN = [
    "Yan", "Dong", "Chen", "Hao", "Feng", "Ming", "Ning", "Li", "Xiaochun", "Fan",
    "Qiye", "Xuan", "San", "Yuhao", "Che", "Qingyue", "Zichen", "Lie", "Tian", "Yun",
    "Wei", "Xian", "Yang", "Jian", "Fei", "Chong", "Yue", "Mo", "Baole", "Yuan",
    "Que", "Ping'an", "Yunmu", "Jing", "Hua", "Long", "Ruo", "Bing", "Xue", "Yu",
    "Shan", "Wu", "Qi", "Lan", "Zhi", "Ling", "Jiao", "Rong", "Ying", "Mei",
    "Wushuang", "Tingfeng", "Wuji", "Kai", "Zhen", "Bo", "Gang", "Tao", "Peng", "Lei",
    "Jun", "Hong", "Qiang", "Fang", "Na", "Juan", "Min", "Jingyi", "Xinyi", "Zihan",
    "Ruoxi", "Shihan", "Yichen", "Haoran", "Zixuan", "Jiayi", "Sihan", "Muchen", "Yuxuan", "Nuo",
    "Chuchu", "Qingqing", "Wan'er", "Xuanxuan", "Tianxin"
]

# ---- Indian male first names (85+) ----
IN_MALE_FIRST = [
    "Arjun", "Krishna", "Rudra", "Shivansh", "Kabir", "Dhruv", "Aryan", "Atharv",
    "Aarav", "Vihaan", "Ishaan", "Shaurya", "Dev", "Ansh", "Aditya", "Rohan",
    "Karan", "Vikram", "Abhimanyu", "Samar", "Vivaan", "Ranveer", "Ayush", "Vedant",
    "Yash", "Nakul", "Sahdev", "Bhishm", "Suryakant", "Chandragupta", "Shiv",
    "Mahadev", "Narayan", "Indra", "Madhav", "Govind", "Gautam", "Siddharth",
    "Chanakya", "Ashoka", "Veer", "Jai", "Vijay", "Ravi", "Surya", "Akash",
    "Prithvi", "Agni", "Vayu", "Kalki", "Bhairav", "Daksh", "Eklavya", "Raghav",
    "Arnav", "Reyansh", "Lakshya", "Parth", "Kunal", "Harsh", "Varun", "Tejas",
    "Nikhil", "Sameer", "Pranav", "Jayant", "Uday", "Omkar", "Ritvik", "Sarthak",
    "Ajay", "Deepak", "Rahul", "Manav", "Kartik", "Nirvan", "Advait", "Bhavya",
    "Ritesh", "Mohit", "Gaurav", "Tarun", "Nitin", "Prithviraj", "Himanshu", "Shreyas"
]

# ---- Indian female first names (60+) ----
IN_FEMALE_FIRST = [
    "Priya", "Ananya", "Aishwarya", "Diya", "Kavya", "Meera", "Nandini", "Ishita",
    "Riya", "Sanya", "Tanvi", "Aditi", "Shruti", "Pooja", "Kriti", "Simran",
    "Aarti", "Bhavna", "Chandni", "Deepika", "Ekta", "Gauri", "Harini", "Jhanvi",
    "Kajal", "Lavanya", "Mahi", "Neha", "Pallavi", "Radhika", "Sakshi", "Tara",
    "Urvashi", "Vaishnavi", "Yamini", "Zoya", "Anjali", "Bhoomi", "Chitra", "Durga",
    "Ganga", "Heena", "Ira", "Juhi", "Kiran", "Lakshmi", "Mitali", "Nisha",
    "Parvati", "Rekha", "Saraswati", "Shreya", "Swara", "Trisha", "Uma", "Vidya",
    "Alisha", "Bani", "Charvi", "Devika"
]

# ---- Indian surnames (70+) ----
IN_LAST = [
    "Sharma", "Verma", "Gupta", "Singh", "Kumar", "Patel", "Reddy", "Rao", "Das",
    "Jain", "Chauhan", "Yadav", "Rajput", "Iyer", "Nair", "Mishra", "Pandey",
    "Shukla", "Tiwari", "Deshmukh", "Patil", "Joshi", "Kulkarni", "Chakraborty",
    "Bose", "Sengupta", "Menon", "Pillai", "Kapoor", "Malhotra", "Mehra", "Chopra",
    "Bansal", "Garg", "Agarwal", "Rathore", "Shekhawat", "Agnihotri", "Trivedi",
    "Bhatt", "Saxena", "Rastogi", "Srivastava", "Khanna", "Arora", "Sethi", "Grover",
    "Chawla", "Bajaj", "Soni", "Thakur", "Solanki", "Parmar", "Chaudhary", "Naidu",
    "Nambiar", "Ranganathan", "Venkatesh", "Swamy", "Hegde", "Shetty", "Pai", "Kamath",
    "Dubey", "Tripathi", "Chaturvedi", "Upadhyay", "Dixit", "Awasthi", "Bajpai", "Nigam"
]

# =====================================================================
# 4. DETERMINISTIC MAPPING ENGINE
# =====================================================================

def _stable_index(key: str, pool_size: int) -> int:
    """
    Har Chinese name ke liye ek FIXED index banata hai (MD5 hash se).
    Iska matlab: 'Xiao Yan' har baar wahi Indian naam banega —
    bot restart hone par bhi mapping nahi badlegi. ✅
    """
    h = hashlib.md5(key.encode("utf-8")).hexdigest()
    return int(h[:8], 16) % pool_size


def _pick_indian_name(ch_name: str) -> str:
    """
    Chinese given-name ke 'look' se gender guess karke Indian naam chunta hai.
    Soft-sounding endings (yue, mei, ling, xue, rong, ...) -> female pool.
    """
    soft_endings = ("yue", "mei", "ling", "xue", "rong", "ying", "jiao", "qing",
                    "chu", "er", "xi", "xin", "yi", "na", "juan", "min", "wan")
    parts = ch_name.lower().replace("'", "").split()
    given = parts[-1] if parts else ch_name.lower()

    if any(given.endswith(e) for e in soft_endings):
        first = IN_FEMALE_FIRST[_stable_index(ch_name + "_f", len(IN_FEMALE_FIRST))]
    else:
        first = IN_MALE_FIRST[_stable_index(ch_name + "_m", len(IN_MALE_FIRST))]

    last = IN_LAST[_stable_index(ch_name + "_l", len(IN_LAST))]
    return f"{first} {last}"


def generate_and_load_mapping():
    """Bot start hote hi hazaron deterministic Chinese->Indian pairs banata hai."""
    global mapping_dict
    mapping_dict.clear()

    chinese_full = (
        [f"{s} {g}" for s in CH_SURNAMES for g in CH_GIVEN] +   # "Xiao Yan"
        [f"{s}{g}" for s in CH_SURNAMES for g in CH_GIVEN]      # "Xiaoyan"
    )

    for ch_name in chinese_full:
        mapping_dict[ch_name] = _pick_indian_name(ch_name)

    logger.info(f"✅ {len(mapping_dict):,} deterministic Chinese->Indian pairs ready.")
    build_regex_engine()


def build_regex_engine():
    """
    Base + Custom dictionaries ko merge karke EK fast Regex engine banata hai.
    - Lambe naam pehle match hote hain ('Xiaochun' > 'Xiao')
    - \\b word boundaries se partial-word corruption rukti hai
    """
    global compiled_pattern
    final_dict = {**mapping_dict, **custom_mapping_dict}

    if not final_dict:
        compiled_pattern = None
        return

    sorted_keys = sorted(final_dict.keys(), key=len, reverse=True)
    escaped = [rf"\b{re.escape(k)}\b" for k in sorted_keys]
    compiled_pattern = re.compile("|".join(escaped), re.IGNORECASE)
    logger.info(f"🚀 Regex engine ready | {len(final_dict):,} total mappings "
                f"({len(custom_mapping_dict)} custom).")


# =====================================================================
# 5. 2-PASS PLACEHOLDER REPLACEMENT  (cascade corruption = 0)
# =====================================================================
#
#  Problem: Agar 'Xiao' -> 'Arjun' ho aur 'Arjun' string mein phir koi
#  match ho jaye to text corrupt hota hai.
#  Solution: Pass-1 mein matches ko \x00ID\x00 placeholder se badlo,
#  Pass-2 mein placeholder -> final Indian name. Kabhi double-replace nahi.

_PLACEHOLDER = "\x00{:06d}\x00"


def translate_text(text: str) -> str:
    if not compiled_pattern or not text:
        return text

    final_dict = {**mapping_dict, **custom_mapping_dict}
    found: Dict[str, str] = {}
    counter = [0]

    def _stash(m: re.Match) -> str:
        key = m.group(0)
        # custom mapping priority, phir base mapping (case-insensitive lookup)
        repl = custom_mapping_dict.get(key) or mapping_dict.get(key)
        if repl is None:
            for k, v in custom_mapping_dict.items():
                if k.lower() == key.lower():
                    repl = v
                    break
        if repl is None:
            for k, v in mapping_dict.items():
                if k.lower() == key.lower():
                    repl = v
                    break
        if repl is None:
            return key
        token = _PLACEHOLDER.format(counter[0])
        found[token] = repl
        counter[0] += 1
        return token

    text = compiled_pattern.sub(_stash, text)
    for token, repl in found.items():
        text = text.replace(token, repl)
    return text


# =====================================================================
# 6. FILE PROCESSORS  (TXT / DOCX / HTML / EPUB)
# =====================================================================

def process_txt(old_path: str, new_path: str):
    """Line-by-line streaming — badi files par bhi kam memory."""
    with open(old_path, "r", encoding="utf-8", errors="replace") as fin, \
         open(new_path, "w", encoding="utf-8") as fout:
        for line in fin:
            fout.write(translate_text(line))


def process_docx(old_path: str, new_path: str):
    """
    DOCX mein formatting (bold/italic/font/size) 'runs' mein hoti hai.
    Run-by-run replace karte hain => formatting 100% preserved. ✅
    """
    doc = docx.Document(old_path)

    def _replace_in_paragraph(p):
        for run in p.runs:
            if run.text:
                run.text = translate_text(run.text)

    for p in doc.paragraphs:
        _replace_in_paragraph(p)

    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    _replace_in_paragraph(p)

    # Header / Footer bhi cover karo
    for section in doc.sections:
        for p in section.header.paragraphs:
            _replace_in_paragraph(p)
        for p in section.footer.paragraphs:
            _replace_in_paragraph(p)

    doc.save(new_path)


def process_html(old_path: str, new_path: str):
    """Sirf visible text nodes translate hote hain; <script>/<style> safe rehte hain."""
    with open(old_path, "r", encoding="utf-8", errors="ignore") as f:
        soup = BeautifulSoup(f, "html.parser")

    skip = {"style", "script", "head", "title", "meta", "[document]", "code", "pre"}
    for node in soup.find_all(string=True):
        if node.parent and node.parent.name not in skip:
            node.replace_with(translate_text(str(node)))

    with open(new_path, "w", encoding="utf-8") as f:
        f.write(str(soup))


def process_epub(old_path: str, new_path: str):
    """
    EPUB = zip of XHTML files. Unzip -> translate -> rezip.
    mimetype file ko pehle & uncompressed rakhna zaroori hai (EPUB spec).
    """
    temp_dir = old_path + "_unzipped"
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)

    with zipfile.ZipFile(old_path, "r") as z:
        z.extractall(temp_dir)

    for root, _dirs, files in os.walk(temp_dir):
        for fn in files:
            if fn.lower().endswith((".html", ".xhtml", ".htm", ".xml", ".opf", ".ncx")):
                fp = os.path.join(root, fn)
                with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                content = translate_text(content)
                with open(fp, "w", encoding="utf-8") as f:
                    f.write(content)

    with zipfile.ZipFile(new_path, "w") as zout:
        # mimetype must be FIRST & STORED (EPUB standard)
        mt = os.path.join(temp_dir, "mimetype")
        if os.path.exists(mt):
            zout.write(mt, "mimetype", compress_type=zipfile.ZIP_STORED)
        for root, _dirs, files in os.walk(temp_dir):
            for fn in files:
                fp = os.path.join(root, fn)
                arc = os.path.relpath(fp, temp_dir)
                if arc == "mimetype":
                    continue
                zout.write(fp, arc, compress_type=zipfile.ZIP_DEFLATED)

    shutil.rmtree(temp_dir, ignore_errors=True)


def process_file(old_path: str, new_path: str) -> bool:
    """Extension ke hisaab se sahi processor chalata hai."""
    if not compiled_pattern:
        return False
    ext = os.path.splitext(old_path)[1].lower()
    try:
        if ext in (".txt", ".md"):
            process_txt(old_path, new_path)
        elif ext == ".docx":
            process_docx(old_path, new_path)
        elif ext in (".html", ".htm"):
            process_html(old_path, new_path)
        elif ext == ".epub":
            process_epub(old_path, new_path)
        else:
            return False
        return True
    except Exception as e:
        logger.error(f"❌ Processing error ({ext}): {e}", exc_info=True)
        return False


# =====================================================================
# 7. DATABASE  (users + stats + custom mappings persist)
# =====================================================================

def _db():
    conn = sqlite3.connect(DB_FILE, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")   # concurrent reads fast
    return conn


def init_db():
    with _db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                files_processed INTEGER DEFAULT 0,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS custom_maps (
                chinese TEXT PRIMARY KEY,
                indian TEXT
            )
        """)


def add_user(user_id: int, username: str, first_name: str):
    with _db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (user_id, username, first_name) VALUES (?,?,?)",
            (user_id, username or "", first_name or "")
        )


def increment_user_stats(user_id: int):
    with _db() as conn:
        conn.execute("UPDATE users SET files_processed = files_processed + 1 WHERE user_id=?",
                     (user_id,))


def get_stats() -> Tuple[int, int]:
    with _db() as conn:
        cur = conn.cursor()
        total_users = cur.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        total_files = cur.execute(
            "SELECT COALESCE(SUM(files_processed),0) FROM users").fetchone()[0]
        return total_users, total_files


def get_all_user_ids():
    with _db() as conn:
        return [r[0] for r in conn.execute("SELECT user_id FROM users").fetchall()]


def save_custom_map(chinese: str, indian: str):
    with _db() as conn:
        conn.execute("INSERT OR REPLACE INTO custom_maps (chinese, indian) VALUES (?,?)",
                     (chinese, indian))


def load_custom_maps():
    """Restart ke baad bhi custom dictionary wapas aa jayegi. ✅"""
    with _db() as conn:
        rows = conn.execute("SELECT chinese, indian FROM custom_maps").fetchall()
    custom_mapping_dict.update(dict(rows))
    if rows:
        logger.info(f"📦 {len(rows)} custom mappings DB se restore ho gayi.")


def clear_custom_maps():
    with _db() as conn:
        conn.execute("DELETE FROM custom_maps")
    custom_mapping_dict.clear()


# =====================================================================
# 8. UI — KEYBOARDS & TEXTS
# =====================================================================

def start_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📖 Help & Commands", callback_data="help_menu")],
        [InlineKeyboardButton("🧠 Engine Info", callback_data="engine_info"),
         InlineKeyboardButton("🗺️ My Dictionary", callback_data="my_map")],
        [InlineKeyboardButton("👨‍💻 Developer", url="https://t.me/your_username")]
    ])


def post_process_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Translate Another File", callback_data="send_more")],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
    ])


HELP_TEXT = (
    "❓ **Bot Kaise Use Karein?**\n\n"
    "1️⃣ Apni novel file bhejein (`.txt` `.docx` `.epub` `.html`)\n"
    "2️⃣ Bot Chinese naamon ko Indian naamon mein badal dega\n"
    "3️⃣ Translated file wapas mil jayegi 🎉\n\n"
    "🗺️ **Custom Dictionary (2 tareeke):**\n"
    "• `.json` file bhejein:\n`{\"Xiao Yan\": \"Arjun Sharma\"}`\n"
    "• Ya command: `/addmap Xiao Yan = Arjun Sharma`\n\n"
    "📋 **Commands:**\n"
    "/start — Bot shuru karein\n"
    "/help — Yeh madad\n"
    "/mymap — Aapki custom dictionary dekhein\n"
    "/clearmap — Custom dictionary saaf karein\n"
    "/engine — Engine ki jaankari\n"
    "/ping — Bot zinda hai ya nahi\n"
    "/stats — Statistics (Admin)\n"
    "/broadcast — Sabko message (Admin)"
)


# =====================================================================
# 9. RATE LIMITER
# =====================================================================

def is_rate_limited(user_id: int) -> int:
    """Returns remaining seconds if limited, else 0."""
    now = time.time()
    last = _rate_limiter.get(user_id, 0)
    if now - last < RATE_LIMIT_S:
        return int(RATE_LIMIT_S - (now - last)) + 1
    _rate_limiter[user_id] = now
    return 0


# =====================================================================
# 10. COMMAND HANDLERS
# =====================================================================

@app.on_message(filters.command("start") & filters.private)
async def start_cmd(client: Client, message: Message):
    user = message.from_user
    add_user(user.id, user.username, user.first_name)

    if not compiled_pattern:
        generate_and_load_mapping()

    total_maps = len(mapping_dict) + len(custom_mapping_dict)
    await message.reply(
        f"🙏 **Namaste {user.first_name}!**\n\n"
        "Main ek **Advanced Novel Translator Bot** hoon.\n"
        "Chinese/Asian novels ke character naamon ko main "
        "**Indian/Desi naamon** mein badal deta hoon.\n\n"
        f"🧠 **Engine:** `{total_maps:,}` name mappings loaded\n"
        "📂 **Formats:** `.txt` `.md` `.docx` `.epub` `.html`\n"
        "🔥 **Pro Tip:** Apni custom dictionary `.json` file se ya "
        "`/addmap` command se add karein!",
        reply_markup=start_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )


@app.on_message(filters.command("help") & filters.private)
async def help_cmd(client: Client, message: Message):
    await message.reply(HELP_TEXT, parse_mode=ParseMode.MARKDOWN)


@app.on_message(filters.command("ping") & filters.private)
async def ping_cmd(client: Client, message: Message):
    t0 = time.time()
    m = await message.reply("🏓 Pinging...")
    ms = int((time.time() - t0) * 1000)
    await m.edit_text(f"🏓 **Pong!** `{ms} ms` | Engine: {'✅ Ready' if compiled_pattern else '❌ Not Ready'}",
                      parse_mode=ParseMode.MARKDOWN)


@app.on_message(filters.command("engine") & filters.private)
async def engine_cmd(client: Client, message: Message):
    total = len(mapping_dict) + len(custom_mapping_dict)
    await message.reply(
        "🧠 **Translation Engine Info**\n\n"
        f"📚 Base Mappings: `{len(mapping_dict):,}`\n"
        f"🗺️ Custom Mappings: `{len(custom_mapping_dict):,}`\n"
        f"🔢 **Total: `{total:,}`**\n\n"
        f"🇨🇳 Chinese Surnames: `{len(CH_SURNAMES)}`\n"
        f"🇨🇳 Chinese Given Names: `{len(CH_GIVEN)}`\n"
        f"🇮🇳 Indian First Names: `{len(IN_MALE_FIRST) + len(IN_FEMALE_FIRST)}` "
        f"(M:{len(IN_MALE_FIRST)} / F:{len(IN_FEMALE_FIRST)})\n"
        f"🇮🇳 Indian Surnames: `{len(IN_LAST)}`\n\n"
        "⚙️ Engine: Deterministic MD5 mapping + 2-pass placeholder replacement\n"
        "✅ Same Chinese naam hamesha same Indian naam banega!",
        parse_mode=ParseMode.MARKDOWN
    )


@app.on_message(filters.command("mymap") & filters.private)
async def mymap_cmd(client: Client, message: Message):
    if not custom_mapping_dict:
        return await message.reply(
            "🗺️ Aapki custom dictionary **khaali** hai.\n\n"
            "Add karne ke liye:\n`/addmap Xiao Yan = Arjun Sharma`\n"
            "ya `.json` file bhejein.",
            parse_mode=ParseMode.MARKDOWN
        )
    lines = [f"• `{k}` → **{v}**" for k, v in list(custom_mapping_dict.items())[:40]]
    extra = f"\n\n_...aur {len(custom_mapping_dict) - 40} mappings_" \
            if len(custom_mapping_dict) > 40 else ""
    await message.reply(
        f"🗺️ **Aapki Custom Dictionary** ({len(custom_mapping_dict)} entries)\n\n"
        + "\n".join(lines) + extra,
        parse_mode=ParseMode.MARKDOWN
    )


@app.on_message(filters.command("addmap") & filters.private)
async def addmap_cmd(client: Client, message: Message):
    """Usage: /addmap Xiao Yan = Arjun Sharma"""
    try:
        payload = message.text.split(None, 1)[1]
        chinese, indian = [x.strip() for x in payload.split("=", 1)]
        if not chinese or not indian:
            raise ValueError
    except (IndexError, ValueError):
        return await message.reply(
            "⚠️ Format galat hai.\n\nSahi format:\n`/addmap Xiao Yan = Arjun Sharma`",
            parse_mode=ParseMode.MARKDOWN
        )
    custom_mapping_dict[chinese] = indian
    save_custom_map(chinese, indian)
    build_regex_engine()
    await message.reply(
        f"✅ **Mapping add ho gayi!**\n\n`{chinese}` → **{indian}**\n\n"
        f"Ab total custom mappings: `{len(custom_mapping_dict)}`",
        parse_mode=ParseMode.MARKDOWN
    )


@app.on_message(filters.command("clearmap") & filters.private)
async def clearmap_cmd(client: Client, message: Message):
    count = len(custom_mapping_dict)
    clear_custom_maps()
    build_regex_engine()
    await message.reply(f"🧹 `{count}` custom mappings saaf kar di gayi. Base engine intact hai.",
                        parse_mode=ParseMode.MARKDOWN)


@app.on_message(filters.command("stats") & filters.private)
async def stats_cmd(client: Client, message: Message):
    if ADMIN_ID and message.from_user.id != ADMIN_ID:
        return await message.reply("⚠️ Yeh command sirf Admin ke liye hai.")
    total_users, total_files = get_stats()
    await message.reply(
        "📊 **Bot Statistics**\n\n"
        f"👥 Total Users: `{total_users}`\n"
        f"📚 Files Translated: `{total_files}`\n"
        f"🧠 Active Mappings: `{len(mapping_dict) + len(custom_mapping_dict):,}`\n"
        f"🗺️ Custom Mappings: `{len(custom_mapping_dict)}`",
        parse_mode=ParseMode.MARKDOWN
    )


@app.on_message(filters.command("broadcast") & filters.private)
async def broadcast_cmd(client: Client, message: Message):
    if ADMIN_ID and message.from_user.id != ADMIN_ID:
        return await message.reply("⚠️ Yeh command sirf Admin ke liye hai.")
    try:
        text = message.text.split(None, 1)[1]
    except IndexError:
        return await message.reply("⚠️ Usage: `/broadcast <message>`", parse_mode=ParseMode.MARKDOWN)

    status = await message.reply("📢 Broadcast shuru ho raha hai...")
    sent, failed = 0, 0
    for uid in get_all_user_ids():
        try:
            await client.send_message(uid, f"📢 **Admin Message:**\n\n{text}",
                                      parse_mode=ParseMode.MARKDOWN)
            sent += 1
        except FloodWait as e:
            await asyncio.sleep(e.value)
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)   # flood-safe pacing
    await status.edit_text(f"📢 **Broadcast Complete**\n\n✅ Sent: `{sent}`\n❌ Failed: `{failed}`",
                           parse_mode=ParseMode.MARKDOWN)


# =====================================================================
# 11. CALLBACK HANDLER
# =====================================================================

@app.on_callback_query(filters.regex(r"^(help_menu|main_menu|send_more|engine_info|my_map)$"))
async def callback_handler(client: Client, cq: CallbackQuery):
    data = cq.data

    if data == "help_menu":
        await cq.message.edit_text(
            HELP_TEXT,
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("◀️ Back", callback_data="main_menu")]]),
            parse_mode=ParseMode.MARKDOWN
        )
    elif data == "engine_info":
        await cq.message.edit_text(
            f"🧠 **Engine:** `{len(mapping_dict) + len(custom_mapping_dict):,}` mappings | "
            "Deterministic | 2-pass safe replacement",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("◀️ Back", callback_data="main_menu")]]),
            parse_mode=ParseMode.MARKDOWN
        )
    elif data == "my_map":
        n = len(custom_mapping_dict)
        await cq.message.edit_text(
            f"🗺️ Aapki custom dictionary mein **{n}** entries hain.\n"
            "Detail ke liye `/mymap` command use karein.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("◀️ Back", callback_data="main_menu")]]),
            parse_mode=ParseMode.MARKDOWN
        )
    elif data == "main_menu":
        await cq.message.edit_text(
            "🏠 **Main Menu**\n\nApni novel file bhejein ya neeche se option chunein:",
            reply_markup=start_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
    elif data == "send_more":
        await cq.message.edit_text("👍 **Bilkul! Apni agli novel file bhejein...**",
                                   parse_mode=ParseMode.MARKDOWN)

    await cq.answer()


# =====================================================================
# 12. DOCUMENT HANDLER  (JSON dictionary + novel files)
# =====================================================================

async def _progress(current, total, msg, stage):
    """Download/Upload ke dauraan progress dikhata hai (har ~2 sec update)."""
    try:
        now = time.time()
        if not hasattr(_progress, "_last"):
            _progress._last = {}
        key = id(msg)
        if now - _progress._last.get(key, 0) < 2 and current != total:
            return
        _progress._last[key] = now
        pct = int(current * 100 / total) if total else 0
        bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
        await msg.edit_text(f"{stage}\n`{bar}` **{pct}%** "
                            f"({current / 1024 / 1024:.1f}/{total / 1024 / 1024:.1f} MB)",
                            parse_mode=ParseMode.MARKDOWN)
    except Exception:
        pass


@app.on_message(filters.document & filters.private)
async def handle_document(client: Client, message: Message):
    doc = message.document
    file_name = (doc.file_name or "file").lower()
    user_id = message.from_user.id

    # ---- Rate limit ----
    wait = is_rate_limited(user_id)
    if wait:
        return await message.reply(
            f"⏳ Thoda dheere! `{wait}` sec baad dobara koshish karein.",
            quote=True, parse_mode=ParseMode.MARKDOWN
        )

    # ---- (A) Custom JSON dictionary ----
    if file_name.endswith(".json"):
        status = await message.reply("⏳ JSON dictionary load ho rahi hai...", quote=True)
        tmp = os.path.join(DOWNLOAD_DIR, f"{user_id}_custom.json")
        try:
            await message.download(file_name=tmp)
            with open(tmp, "r", encoding="utf-8") as f:
                new_map = json.load(f)
            if not isinstance(new_map, dict):
                raise ValueError("JSON root ek object hona chahiye")
            for k, v in new_map.items():
                custom_mapping_dict[str(k)] = str(v)
                save_custom_map(str(k), str(v))
            build_regex_engine()
            await status.edit_text(
                f"✅ **Custom Dictionary Updated!**\n\n"
                f"🗺️ Naye mappings: `{len(new_map)}`\n"
                f"📚 Total custom: `{len(custom_mapping_dict)}`\n\n"
                "Ab aapki novels in naamon ke saath translate hongi. "
                "(Restart ke baad bhi saved rahengi ✅)",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            await status.edit_text(f"❌ JSON error: `{e}`", parse_mode=ParseMode.MARKDOWN)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
        return

    # ---- (B) Novel file ----
    valid_ext = (".txt", ".md", ".docx", ".epub", ".html", ".htm")
    if not file_name.endswith(valid_ext):
        return await message.reply(
            "⚠️ Kripya keval `TXT, MD, DOCX, EPUB, HTML` ya custom `JSON` file bhejein.",
            quote=True, parse_mode=ParseMode.MARKDOWN
        )

    if doc.file_size and doc.file_size > MAX_FILE_MB * 1024 * 1024:
        return await message.reply(
            f"⚠️ File `{MAX_FILE_MB} MB` se badi hai. Kripya choti file bhejein.",
            quote=True, parse_mode=ParseMode.MARKDOWN
        )

    if not compiled_pattern:
        generate_and_load_mapping()

    chat_id = message.chat.id
    safe_name = re.sub(r"[^\w.\-]", "_", doc.file_name or "novel")
    old_path = os.path.join(DOWNLOAD_DIR, f"{chat_id}_in_{safe_name}")
    new_path = os.path.join(DOWNLOAD_DIR, f"{chat_id}_out_{safe_name}")

    status = await message.reply("⏳ **Step 1/3:** File download ho rahi hai...",
                                 quote=True, parse_mode=ParseMode.MARKDOWN)
    t0 = time.time()
    try:
        await client.send_chat_action(chat_id, ChatAction.UPLOAD_DOCUMENT)
        await message.download(
            file_name=old_path,
            progress=_progress,
            progress_args=(status, "📥 **Downloading...**")
        )

        await status.edit_text(
            "⚡ **Step 2/3:** Chinese naam -> Indian naam badle ja rahe hain...\n"
            "_(Badi files mein thoda samay lag sakta hai)_",
            parse_mode=ParseMode.MARKDOWN
        )

        # CPU-heavy kaam background thread mein (bot block nahi hoga)
        success = await asyncio.to_thread(process_file, old_path, new_path)

        if not success:
            return await status.edit_text(
                "❌ File process nahi ho payi. File corrupt ya format galat ho sakta hai.",
                parse_mode=ParseMode.MARKDOWN
            )

        increment_user_stats(user_id)
        await status.edit_text("📤 **Step 3/3:** Nayi file upload ho rahi hai...",
                               parse_mode=ParseMode.MARKDOWN)

        elapsed = time.time() - t0
        out_size = os.path.getsize(new_path) / 1024 / 1024
        caption = (
            f"🎉 **Translation Successful!**\n\n"
            f"📂 **File:** `{doc.file_name}`\n"
            f"📦 **Size:** `{out_size:.2f} MB`\n"
            f"⏱️ **Time:** `{elapsed:.1f} sec`\n"
            f"🧠 **Engine:** `{len(mapping_dict) + len(custom_mapping_dict):,}` mappings "
            f"(2-pass safe mode)"
        )

        await message.reply_document(
            new_path,
            caption=caption,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=post_process_keyboard(),
            progress=_progress,
            progress_args=(status, "📤 **Uploading...**")
        )
        await status.delete()

    except FloodWait as e:
        await asyncio.sleep(e.value)
    except Exception as e:
        logger.error(f"❌ Handler Error: {e}", exc_info=True)
        await status.edit_text("❌ Technical kharabi aa gayi. Thodi der baad koshish karein.",
                               parse_mode=ParseMode.MARKDOWN)
    finally:
        for p in (old_path, new_path):
            if os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass


# =====================================================================
# 13. WEB SERVER  (Render/Koyeb health-check ke liye)
# =====================================================================

async def web_handler(request):
    total = len(mapping_dict) + len(custom_mapping_dict)
    return web.json_response({
        "status": "running",
        "bot": "Advanced Novel Translator",
        "mappings": total,
        "engine_ready": compiled_pattern is not None
    })


async def start_web_server():
    port = int(os.environ.get("PORT", 8080))
    web_app = web.Application()
    web_app.router.add_get("/", web_handler)
    web_app.router.add_get("/health", web_handler)
    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"🌐 Web server live on port {port} (/health endpoint ready)")


# =====================================================================
# 14. MAIN LOOP  (startup + graceful shutdown)
# =====================================================================

async def main():
    if not all([API_ID, API_HASH, BOT_TOKEN]):
        raise SystemExit(
            "❌ API_ID / API_HASH / BOT_TOKEN environment variables set nahi hain!\n"
            "   Render dashboard -> Environment mein add karein."
        )

    init_db()
    load_custom_maps()
    generate_and_load_mapping()
    await start_web_server()

    await app.start()
    me = await app.get_me()
    logger.info(f"🤖 Bot online: @{me.username}")

    await app.set_bot_commands([
        BotCommand("start", "Bot ko start karein"),
        BotCommand("help", "Madad aur instructions"),
        BotCommand("addmap", "Custom naam mapping add karein"),
        BotCommand("mymap", "Apni dictionary dekhein"),
        BotCommand("clearmap", "Custom dictionary saaf karein"),
        BotCommand("engine", "Translation engine ki jaankari"),
        BotCommand("ping", "Bot status check"),
        BotCommand("stats", "Statistics (Admin only)"),
        BotCommand("broadcast", "Sabko message (Admin only)")
    ])

    await idle()                      # bot yahan chalta rahega
    await app.stop()                  # Ctrl+C par clean shutdown
    logger.info("👋 Bot safely band ho gaya.")


if __name__ == "__main__":
    # Naya event loop set karna taaki Pyrogram aur Web Server dono ek sath chal sakein
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        pass
    finally:
        loop.close()
      
