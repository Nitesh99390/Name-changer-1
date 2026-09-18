# -*- coding: utf-8 -*-
"""
====================================================================
  📚  ADVANCED NOVEL NAME TRANSLATOR BOT  (Single-File Edition)
====================================================================
  Chinese/Asian novel characters -> Indian/Desi names
  Supported: .txt .md .docx .epub .html .htm  + custom .json mapping
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

API_ID    = int(os.environ.get("API_ID", "30417468"))
API_HASH  = os.environ.get("API_HASH", "3905c3cb0effc91feef4d4cdcae89354")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8653761809:AAEr3j5CLr5ZEMY6Nh0Q_D3UN1cZWZhBsMs")
ADMIN_ID  = int(os.environ.get("ADMIN_ID", "6069200310"))

DB_FILE      = "bot_stats.db"
DOWNLOAD_DIR = "downloads"
MAX_FILE_MB  = 50
RATE_LIMIT_S = 15          
LOG_FILE     = "bot.log"

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

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
    workers=16,                 
    sleep_threshold=60          
)

compiled_pattern: Optional[re.Pattern] = None
mapping_dict: Dict[str, str] = {}          
custom_mapping_dict: Dict[str, str] = {}   
_rate_limiter: Dict[int, float] = {}       

# =====================================================================
# 3. NAME BANKS
# =====================================================================

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
    h = hashlib.md5(key.encode("utf-8")).hexdigest()
    return int(h[:8], 16) % pool_size

def _pick_indian_name(ch_name: str) -> str:
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
    global mapping_dict
    mapping_dict.clear()

    chinese_full = (
        [f"{s} {g}" for s in CH_SURNAMES for g in CH_GIVEN] +   
        [f"{s}{g}" for s in CH_SURNAMES for g in CH_GIVEN]      
    )

    for ch_name in chinese_full:
        mapping_dict[ch_name] = _pick_indian_name(ch_name)

    logger.info(f"✅ {len(mapping_dict):,} deterministic Chinese->Indian pairs ready.")
    build_regex_engine()

def build_regex_engine():
    global compiled_pattern
    final_dict = {**mapping_dict, **custom_mapping_dict}

    if not final_dict:
        compiled_pattern = None
        return

    sorted_keys = sorted(final_dict.keys(), key=len, reverse=True)
    escaped = [rf"\b{re.escape(k)}\b" for k in sorted_keys]
    compiled_pattern = re.compile("|".join(escaped), re.IGNORECASE)
    logger.info(f"🚀 Regex engine ready | {len(final_dict):,} total mappings.")

# =====================================================================
# 5. 2-PASS PLACEHOLDER REPLACEMENT
# =====================================================================

_PLACEHOLDER = "\x00{:06d}\x00"

def translate_text(text: str) -> str:
    if not compiled_pattern or not text:
        return text

    final_dict = {**mapping_dict, **custom_mapping_dict}
    found: Dict[str, str] = {}
    counter = [0]

    def _stash(m: re.Match) -> str:
        key = m.group(0)
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
# 6. FILE PROCESSORS
# =====================================================================

def process_txt(old_path: str, new_path: str):
    with open(old_path, "r", encoding="utf-8", errors="replace") as fin, \
         open(new_path, "w", encoding="utf-8") as fout:
        for line in fin:
            fout.write(translate_text(line))

def process_docx(old_path: str, new_path: str):
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

    for section in doc.sections:
        for p in section.header.paragraphs:
            _replace_in_paragraph(p)
        for p in section.footer.paragraphs:
            _replace_in_paragraph(p)

    doc.save(new_path)

def process_html(old_path: str, new_path: str):
    with open(old_path, "r", encoding="utf-8", errors="ignore") as f:
        soup = BeautifulSoup(f, "html.parser")

    skip = {"style", "script", "head", "title", "meta", "[document]", "code", "pre"}
    for node in soup.find_all(string=True):
        if node.parent and node.parent.name not in skip:
            node.replace_with(translate_text(str(node)))

    with open(new_path, "w", encoding="utf-8") as f:
        f.write(str(soup))

def process_epub(old_path: str, new_path: str):
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
# 7. DATABASE
# =====================================================================

def _db():
    conn = sqlite3.connect(DB_FILE, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
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
    with _db() as conn:
        rows = conn.execute("SELECT chinese, indian FROM custom_maps").fetchall()
    custom_mapping_dict.update(dict(rows))

def clear_custom_maps():
    with _db() as conn:
        conn.execute("DELETE FROM custom_maps")
    custom_mapping_dict.clear()

# =====================================================================
# 8. UI & RATE LIMITER
# =====================================================================

def start_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🧠 Engine Info", callback_data="engine_info"),
         InlineKeyboardButton("🗺️ My Dictionary", callback_data="my_map")]
    ])

def post_process_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Translate Another", callback_data="send_more")]
    ])

def is_rate_limited(user_id: int) -> int:
    now = time.time()
    last = _rate_limiter.get(user_id, 0)
    if now - last < RATE_LIMIT_S:
        return int(RATE_LIMIT_S - (now - last)) + 1
    _rate_limiter[user_id] = now
    return 0

async def _progress(current, total, msg, stage):
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

# =====================================================================
# 9. TELEGRAM HANDLERS
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
        f"🧠 **Engine:** `{total_maps:,}` name mappings loaded\n"
        "📂 **Formats:** `.txt` `.md` `.docx` `.epub` `.html`\n"
        "Aap apni file bhejein, main translation shuru kar dunga!",
        reply_markup=start_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )

@app.on_message(filters.command("addmap") & filters.private)
async def addmap_cmd(client: Client, message: Message):
    try:
        payload = message.text.split(None, 1)[1]
        chinese, indian = [x.strip() for x in payload.split("=", 1)]
        if not chinese or not indian:
            raise ValueError
    except (IndexError, ValueError):
        return await message.reply("Sahi format: `/addmap Xiao Yan = Arjun Sharma`")
    
    custom_mapping_dict[chinese] = indian
    save_custom_map(chinese, indian)
    build_regex_engine()
    await message.reply(f"✅ Mapping saved: `{chinese}` → **{indian}**")

@app.on_message(filters.command("clearmap") & filters.private)
async def clearmap_cmd(client: Client, message: Message):
    clear_custom_maps()
    build_regex_engine()
    await message.reply("🧹 Custom dictionary saaf kar di gayi hai.")

@app.on_callback_query(filters.regex(r"^(engine_info|my_map|send_more)$"))
async def callback_handler(client: Client, cq: CallbackQuery):
    if cq.data == "engine_info":
        await cq.message.edit_text(f"🧠 **Engine:** `{len(mapping_dict) + len(custom_mapping_dict):,}` mappings.")
    elif cq.data == "my_map":
        await cq.message.edit_text(f"🗺️ Aapki custom dictionary mein **{len(custom_mapping_dict)}** entries hain.")
    elif cq.data == "send_more":
        await cq.message.edit_text("👍 Bilkul! Apni agli file bhejein.")
    await cq.answer()

@app.on_message(filters.document & filters.private)
async def handle_document(client: Client, message: Message):
    doc = message.document
    file_name = (doc.file_name or "file").lower()
    user_id = message.from_user.id

    wait = is_rate_limited(user_id)
    if wait:
        return await message.reply(f"⏳ Thoda dheere! `{wait}` sec baad try karein.")

    if file_name.endswith(".json"):
        status = await message.reply("⏳ JSON dictionary load ho rahi hai...", quote=True)
        tmp = os.path.join(DOWNLOAD_DIR, f"{user_id}_custom.json")
        try:
            await message.download(file_name=tmp)
            with open(tmp, "r", encoding="utf-8") as f:
                new_map = json.load(f)
            for k, v in new_map.items():
                custom_mapping_dict[str(k)] = str(v)
                save_custom_map(str(k), str(v))
            build_regex_engine()
            await status.edit_text(f"✅ JSON Updated! Naye mappings: `{len(new_map)}`")
        except Exception as e:
            await status.edit_text(f"❌ JSON error: `{e}`")
        finally:
            if os.path.exists(tmp): os.remove(tmp)
        return

    valid_ext = (".txt", ".md", ".docx", ".epub", ".html", ".htm")
    if not file_name.endswith(valid_ext):
        return await message.reply("⚠️ Kripya valid file bhejein.")

    if doc.file_size and doc.file_size > MAX_FILE_MB * 1024 * 1024:
        return await message.reply(f"⚠️ File `{MAX_FILE_MB} MB` se badi hai.")

    if not compiled_pattern:
        generate_and_load_mapping()

    chat_id = message.chat.id
    safe_name = re.sub(r"[^\w.\-]", "_", doc.file_name or "novel")
    old_path = os.path.join(DOWNLOAD_DIR, f"{chat_id}_in_{safe_name}")
    new_path = os.path.join(DOWNLOAD_DIR, f"{chat_id}_out_{safe_name}")

    status = await message.reply("⏳ **Step 1/3:** File download ho rahi hai...")
    t0 = time.time()
    
    try:
        await message.download(
            file_name=old_path,
            progress=_progress,
            progress_args=(status, "📥 **Downloading...**")
        )

        await status.edit_text("⚡ **Step 2/3:** Names translate ho rahe hain...")
        success = await asyncio.to_thread(process_file, old_path, new_path)

        if not success:
            return await status.edit_text("❌ File process nahi ho payi.")

        increment_user_stats(user_id)
        
        elapsed = time.time() - t0
        out_size = os.path.getsize(new_path) / 1024 / 1024
        
        await message.reply_document(
            new_path,
            caption=f"🎉 **Translated!** | Size: `{out_size:.2f} MB` | Time: `{elapsed:.1f} s`",
            reply_markup=post_process_keyboard(),
            progress=_progress,
            progress_args=(status, "📤 **Uploading...**")
        )
        await status.delete()

    except Exception as e:
        logger.error(f"❌ Error: {e}")
        await status.edit_text("❌ Technical kharabi aa gayi.")
    finally:
        for p in (old_path, new_path):
            if os.path.exists(p):
                try: os.remove(p)
                except: pass

# =====================================================================
# 10. WEB SERVER & MAIN LOOP (Render Safe)
# =====================================================================

async def web_handler(request):
    total = len(mapping_dict) + len(custom_mapping_dict)
    return web.json_response({"status": "running", "mappings": total})

async def start_web_server():
    port = int(os.environ.get("PORT", 8080))
    web_app = web.Application()
    web_app.router.add_get("/", web_handler)
    web_app.router.add_get("/health", web_handler)
    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"🌐 Web server live on port {port}")

async def main():
    init_db()
    load_custom_maps()
    generate_and_load_mapping()
    await start_web_server()

    await app.start()
    me = await app.get_me()
    logger.info(f"🤖 Bot online: @{me.username}")
    
    await app.set_bot_commands([
        BotCommand("start", "Bot shuru karein"),
        BotCommand("addmap", "Naya naam jodein"),
        BotCommand("clearmap", "Custom dictionary saaf karein")
    ])

    await idle()
    await app.stop()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
