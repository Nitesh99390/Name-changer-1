import os
import asyncio
import random
import re
import logging
import zipfile
import shutil
import docx
from bs4 import BeautifulSoup
from pyrogram import Client, filters, idle
from pyrogram.types import Message
from aiohttp import web

# Sarvar ki gatividhiyon ko darj karne ke liye
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Aapki nayi chaabi (token)
BOT_TOKEN = "8653761809:AAEr3j5CLr5ZEMY6Nh0Q_D3UN1cZWZhBsMs"

app = Client(
    "advanced_novel_bot", 
    api_id=30417468, 
    api_hash="3905c3cb0effc91feef4d4cdcae89354", 
    bot_token=BOT_TOKEN,
    workers=4
)

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

CHINESE_FILE_PATH = "chinese_names.txt"
INDIAN_FILE_PATH = "indian_names.txt"
MASTER_MAPPING_FILE = os.path.join(DOWNLOAD_DIR, "master_mapping.txt")

compiled_pattern = None
mapping_dict = {}

async def create_mapping_from_local():
    if os.path.exists(MASTER_MAPPING_FILE):
        logger.info("Mukhya soochi pehle se uplabdh hai.")
        load_mapping_into_memory()
        return True
        
    try:
        with open(CHINESE_FILE_PATH, 'r', encoding='utf-8') as f:
            chinese_names = [n.strip() for n in f.readlines() if n.strip()]
            
        with open(INDIAN_FILE_PATH, 'r', encoding='utf-8') as f:
            indian_names = [n.strip() for n in f.readlines() if n.strip()]
            
        if not chinese_names or not indian_names:
            logger.error("Nam sanchikayen khali hain.")
            return False
            
        total_pairs = min(len(chinese_names), len(indian_names))
        chinese_names = random.sample(chinese_names, total_pairs)
        indian_names = random.sample(indian_names, total_pairs)
        
        with open(MASTER_MAPPING_FILE, 'w', encoding='utf-8') as f:
            for ch, ind in zip(chinese_names, indian_names):
                f.write(f"{ch}={ind}\n")
                
        logger.info("Sthaniya sanchikaon se soochi safaltapurvak ban gayi.")
        load_mapping_into_memory()
        return True
    except FileNotFoundError:
        logger.error("Sthaniya nam sanchikayen sarvar par nahi milin.")
        return False
    except Exception as e:
        logger.error(f"Truti: {e}")
        return False

def load_mapping_into_memory():
    global compiled_pattern, mapping_dict
    mapping_dict.clear()
    
    if not os.path.exists(MASTER_MAPPING_FILE):
        return

    with open(MASTER_MAPPING_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            if "=" in line:
                old, new = line.split("=", 1)
                mapping_dict[old.strip()] = new.strip()
    
    if mapping_dict:
        sorted_keys = sorted(mapping_dict.keys(), key=len, reverse=True)
        escaped_keys = map(re.escape, sorted_keys)
        compiled_pattern = re.compile("|".join(escaped_keys))
        logger.info("Smriti mein soochi load ho gayi hai.")

def process_txt(old_path: str, new_path: str):
    with open(old_path, 'r', encoding='utf-8', errors='replace') as infile, \
         open(new_path, 'w', encoding='utf-8') as outfile:
        for line in infile:
            new_line = compiled_pattern.sub(lambda match: mapping_dict[match.group(0)], line)
            outfile.write(new_line)

def process_docx(old_path: str, new_path: str):
    doc = docx.Document(old_path)
    for para in doc.paragraphs:
        if para.text:
            para.text = compiled_pattern.sub(lambda m: mapping_dict[m.group(0)], para.text)
    
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                if cell.text:
                    cell.text = compiled_pattern.sub(lambda m: mapping_dict[m.group(0)], cell.text)
    doc.save(new_path)

def process_html(old_path: str, new_path: str):
    with open(old_path, 'r', encoding='utf-8', errors='ignore') as f:
        soup = BeautifulSoup(f, 'html.parser')
    
    for text_node in soup.find_all(string=True):
        if text_node.parent.name not in ['style', 'script', 'head', 'title', 'meta', '[document]']:
            replaced = compiled_pattern.sub(lambda m: mapping_dict[m.group(0)], text_node)
            text_node.replace_with(replaced)
            
    with open(new_path, 'w', encoding='utf-8') as f:
        f.write(str(soup))

def process_epub(old_path: str, new_path: str):
    temp_dir = old_path + "_unzipped"
    with zipfile.ZipFile(old_path, 'r') as zip_ref:
        zip_ref.extractall(temp_dir)

    for root, dirs, files in os.walk(temp_dir):
        for file in files:
            if file.lower().endswith(('.html', '.xhtml', '.htm')):
                file_path = os.path.join(root, file)
                process_html(file_path, file_path)

    with zipfile.ZipFile(new_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(temp_dir):
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, temp_dir)
                zipf.write(file_path, arcname)

    shutil.rmtree(temp_dir)

def process_file_optimized(old_path: str, new_path: str) -> bool:
    global compiled_pattern, mapping_dict
    if not compiled_pattern or not mapping_dict:
        return False
    ext = os.path.splitext(old_path)[1].lower()
    try:
        if ext == '.txt': process_txt(old_path, new_path)
        elif ext == '.docx': process_docx(old_path, new_path)
        elif ext in ['.html', '.htm']: process_html(old_path, new_path)
        elif ext == '.epub': process_epub(old_path, new_path)
        else: return False
        return True
    except Exception as e:
        logger.error(f"Sanchika parivartan mein truti: {e}")
        return False

@app.on_message(filters.command("start") & filters.private)
async def start_cmd(client, message):
    status_msg = await message.reply("⏳ Kripya pratiksha karein, sarvar nam soochi taiyar kar raha hai...", quote=True)
    success = await asyncio.to_thread(create_mapping_from_local)
    if success:
        await status_msg.edit_text("✅ Bot taiyar hai! Nam soochi safaltapurvak load ho gayi hai. Kripya apni pustak ki sanchika bhejein.")
    else:
        await status_msg.edit_text("❌ Mukhya soochi banane mein vifalta hui. Kripya sunishchit karein ki nam sanchikayen sarvar mein maujud hain.")

@app.on_message(filters.document & filters.private)
async def handle_document(client, message):
    doc = message.document
    valid_extensions = ('.txt', '.md', '.docx', '.epub', '.html', '.htm')
    if not doc.file_name.lower().endswith(valid_extensions):
        return await message.reply("⚠️ Kripya keval TXT, DOCX, EPUB ya HTML sanchika hi bhejein.", quote=True)
    if doc.file_size > 50 * 1024 * 1024:
        return await message.reply("⚠️ Sanchika ka aakar bahut bada hai.", quote=True)

    chat_id = message.chat.id
    old_novel_path = os.path.join(DOWNLOAD_DIR, f"{chat_id}_in_{doc.file_name}")
    new_novel_path = os.path.join(DOWNLOAD_DIR, f"{chat_id}_out_{doc.file_name}")
    status_msg = await message.reply("⏳ Sanchika prapt ho rahi hai...", quote=True)
    
    try:
        await app.download_media(doc.file_id, file_name=old_novel_path)
        if not compiled_pattern:
            await status_msg.edit_text("❌ Soochi taiyar nahi hai. Kripya pehle /start command ka upyog karein.")
            return
            
        await status_msg.edit_text("⚡ Namon ko badla ja raha hai, kripya pratiksha karein...")
        success = await asyncio.to_thread(process_file_optimized, old_novel_path, new_novel_path)
        
        if success:
            await status_msg.edit_text("📤 Nayi sanchika bheji ja rahi hai...")
            await app.send_document(chat_id, new_novel_path, caption=f"🎉 Aapki sanchika mein nam safaltapurvak badal diye gaye hain!")
            await status_msg.delete()
        else:
            await status_msg.edit_text("❌ Sanchika ko badalne mein truti utpann hui.")
    except Exception as e:
        logger.error(f"Sanchika sambhalne mein truti: {e}")
        await status_msg.edit_text("❌ Kuch takniki samasya utpann ho gayi hai.")
    finally:
        if os.path.exists(old_novel_path): os.remove(old_novel_path)
        if os.path.exists(new_novel_path): os.remove(new_novel_path)

# --- Render Dummy Web Server ---
async def web_handler(request):
    return web.Response(text="Bot is running on Render!")

async def main():
    # 1. Start Render Web Server
    port = int(os.environ.get("PORT", 8080))
    web_app = web.Application()
    web_app.router.add_get("/", web_handler)
    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Render Web Server started on port {port}")

    # 2. Start Pyrogram Bot
    load_mapping_into_memory()
    await app.start()
    logger.info("Bot Telegram se jud chuka hai aur chal raha hai...")
    await idle()
    await app.stop()

if __name__ == "__main__":
    asyncio.run(main())
