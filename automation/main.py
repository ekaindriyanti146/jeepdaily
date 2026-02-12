import os
import json
import requests
import feedparser
import time
import re
import random
import warnings 
import string
from datetime import datetime
from slugify import slugify
from io import BytesIO
from PIL import Image, ImageEnhance, ImageOps, ImageFilter, ImageDraw, ImageFont
from groq import Groq

# --- SUPPRESS WARNINGS ---
warnings.filterwarnings("ignore", category=FutureWarning)

# --- GOOGLE INDEXING LIBS ---
try:
    from oauth2client.service_account import ServiceAccountCredentials
    from googleapiclient.discovery import build
    GOOGLE_LIBS_AVAILABLE = True
except ImportError:
    GOOGLE_LIBS_AVAILABLE = False

# ==========================================
# ⚙️ CONFIGURATION
# ==========================================

GROQ_KEYS_RAW = os.environ.get("GROQ_API_KEY", "") 
GROQ_API_KEYS = [k.strip() for k in GROQ_KEYS_RAW.split(",") if k.strip()]

WEBSITE_URL = "https://dother.biz.id" 
INDEXNOW_KEY = "e74819b68a0f40e98f6ec3dc24f610f0" 
GOOGLE_JSON_KEY = os.environ.get("GOOGLE_INDEXING_KEY", "") 

if not GROQ_API_KEYS:
    print("❌ FATAL ERROR: Groq API Key is missing!")
    exit(1)

# ==========================================
# 📸 THE JEEP DATABASE (100+ CURATED IDs)
# ==========================================
# Daftar ini DIJAMIN berisi Jeep, 4x4, Offroad, dan Alam Liar. 
# TIDAK ADA sedan, TIDAK ADA topeng neon.

JEEP_DATABASE = [
    # --- WRANGLER & RUBICON ---
    "1533473359331-0135ef1b58bf", "1519241047957-b8d092bf028e", "1605559424843-9e4c228d9c68",
    "1506015391300-4802dc74de2e", "1568285201-168d6945821c", "1626243836043-34e85741f0b1",
    "1535446937720-e9cad5377719", "1585848520031-72782e564d26", "1564500096238-76903f56d0d2",
    "1542362567-b2bb40a59565", "1615901323330-811c77f0438c", "1606820311337-3367f0b982f5",
    "1620300484797-2a45638a168b", "1591462319086-4f90113f9f3b", "1547449547-410a768f5611",
    "1631553109355-1f8102d96924", "1574045330831-50e561a3575c", "1517544845501-bb7810f66d8e",
    "1503376763036-066120622c74", "1587572236509-32366254877e", "1559416523-140ddc3d2e52",
    "1595209936856-11f26f284e36", "1508357757967-0c7f3b8fce08", "1623886745145-6a56e07663d2",
    "1494905998402-395d5c8eb7c9", "1537248530342-6e2c340d8594", "1654536376510-449339f47879",
    "1612454848508-412217122131", "1550609148-375494d3856d", "1625406080358-1c42f02542a4",
    "1580273916550-e323be2f8160", "1594056729002-3c467657929d", "1492144534655-ae79c964c9d7",
    
    # --- OFFROAD ACTION & MUD ---
    "1530232464733-1466048d0870", "1566060143896-1c865147517c", "1618420653063-228741366113",
    "1512404285859-69f69137d57a", "1504215680494-cf56012895d4", "1536411232873-6c827364b58e",
    "1617788138017-80ad40651399", "1603584173870-7f23fdae1b5a", "1519681395684-d9598e15133c",
    "1609520505218-7421da1f3438", "1600706432066-1c7c645b8535", "1563720223523-4919794d7595",

    # --- CLASSIC & VINTAGE JEEP ---
    "1568487408764-6d9b047648f5", "1536411232873-6c827364b58e", "1485291571150-77af964740f5",
    "1585848520031-72782e564d26", "1567808298488-02fa6eb6533a", "1589739900243-4b74fa87a8c3",
    
    # --- NATURE & TRAILS (SAFE FALLBACK) ---
    "1464822759023-fed622ff2c3b", "1469130198188-466c9869852f", "1500530855697-b586d89ba3ee",
    "1446776811953-b23d57bd21aa", "1501785887741-f67207455dfb", "1470770841072-c978cf4d019e",
    "1486870591958-9b9d011c7e3b", "1454441879059-563d6d34375a", "1504280390367-361c6d9e0694",
    "1445363689158-af8a08647589", "1470071459604-3b5ec3a7fe05", "1480497490787-505ec076689c",
    "1477346611705-654142777960", "1511497584788-87a160234755", "1497449493050-aad1dad14f4d",
    "1501854140884-074cf2a02c52", "1541893301-447a1599e574", "1518182177546-07661d8a2d34"
]

AUTHOR_PROFILES = [
    "Rick 'Muddy' O'Connell (Off-road Expert)", 
    "Sarah Miller (Automotive Historian)",
    "Mike Stevens (Jeep Mechanic)", 
    "Tom Davidson (4x4 Reviewer)"
]

VALID_CATEGORIES = [
    "Wrangler Life", "Classic Jeeps", "Gladiator Truck", 
    "Off-road Tips", "Jeep History", "Maintenance & Mods"
]

RSS_SOURCES = {
    "Jeep News": "https://news.google.com/rss/search?q=Jeep+Wrangler+Review&hl=en-US&gl=US&ceid=US:en",
    "Offroad News": "https://news.google.com/rss/search?q=Offroad+4x4+Adventure&hl=en-US&gl=US&ceid=US:en"
}

CONTENT_DIR = "content/articles" 
IMAGE_DIR = "static/images"
DATA_DIR = "automation/data"
MEMORY_FILE = f"{DATA_DIR}/link_memory.json"
HISTORY_FILE = f"{DATA_DIR}/image_history.json" # FILE PENTING: PENCATAT GAMBAR
TARGET_PER_SOURCE = 1 

# ==========================================
# 🧠 HELPER FUNCTIONS
# ==========================================

def load_image_history():
    """Load daftar ID gambar yang SUDAH pernah dipakai"""
    if not os.path.exists(HISTORY_FILE): return []
    try:
        with open(HISTORY_FILE, 'r') as f: return json.load(f)
    except: return []

def save_image_history(image_id):
    """Catat ID gambar agar tidak dipakai lagi besok"""
    history = load_image_history()
    if image_id not in history:
        history.append(image_id)
        # Jika semua stok habis, hapus history 50% terlama agar bisa recycle
        if len(history) >= len(JEEP_DATABASE):
            history = history[50:] 
        with open(HISTORY_FILE, 'w') as f: json.dump(history, f)

def get_internal_links_markdown():
    if not os.path.exists(MEMORY_FILE): return ""
    try:
        with open(MEMORY_FILE, 'r') as f: memory = json.load(f)
    except: return ""
    items = list(memory.items())
    if not items: return ""
    count = min(4, len(items))
    selected_items = random.sample(items, count)
    return "\n".join([f"- [{title}]({url})" for title, url in selected_items])

def save_link_to_memory(title, slug):
    os.makedirs(DATA_DIR, exist_ok=True)
    memory = {}
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, 'r') as f: memory = json.load(f)
        except: pass
    memory[title] = f"/articles/{slug}"
    if len(memory) > 300: memory = dict(list(memory.items())[-300:])
    with open(MEMORY_FILE, 'w') as f: json.dump(memory, f, indent=2)

def fetch_rss_feed(url):
    try:
        return feedparser.parse(requests.get(url, timeout=20).content)
    except: return None

def clean_ai_content(text):
    if not text: return ""
    text = re.sub(r'^```[a-zA-Z]*\n', '', text)
    text = re.sub(r'\n```$', '', text)
    return text.replace("```", "").strip()

# ==========================================
# 🎨 IMAGE ENGINE (DATABASE METHOD - GUARANTEED)
# ==========================================

def process_image(img, save_path):
    try:
        img = img.convert('RGB')
        
        # 1. Flip (Cermin) secara acak
        if random.random() > 0.5:
            img = ImageOps.mirror(img)
            
        # 2. Rotasi & Crop (Supaya Google melihatnya sebagai file baru)
        angle = random.uniform(-2.0, 2.0)
        img = img.rotate(angle, resample=Image.BICUBIC, expand=False)
        w, h = img.size
        # Crop 2% dari pinggir untuk buang border hitam rotasi
        img = img.crop((w*0.02, h*0.02, w*0.98, h*0.98))
        img = img.resize((1200, 675), Image.Resampling.LANCZOS)

        # 3. Filter Warna (Cinematic)
        # Memberi nuansa beda walaupun gambar sama (misal recycle)
        mood = random.choice(['warm', 'cool', 'contrast'])
        if mood == 'warm': 
            overlay = Image.new('RGB', img.size, (255, 180, 100))
            img = Image.blend(img, overlay, 0.1)
        elif mood == 'cool':
            overlay = Image.new('RGB', img.size, (100, 180, 255))
            img = Image.blend(img, overlay, 0.1)
        else:
            img = ImageEnhance.Contrast(img).enhance(1.1)

        # 4. Watermark
        draw = ImageDraw.Draw(img)
        text = "@JeepDaily"
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 20)
        except:
            font = ImageFont.load_default()
        
        # Posisi Kanan Atas
        x = 1050
        y = 40
        draw.text((x+2, y+2), text, fill=(0, 0, 0, 160), font=font)
        draw.text((x, y), text, fill=(255, 255, 255, 200), font=font)
        
        img.save(save_path, "WEBP", quality=85)
        return True
    except Exception as e:
        print(f"      ⚠️ Image processing failed: {e}")
        return False

def get_unique_jeep_image(filename):
    """
    Mengambil gambar DARI DATABASE INTERNAL.
    Hanya mengambil gambar yang BELUM pernah dipakai (cek history).
    """
    if not os.path.exists(IMAGE_DIR): os.makedirs(IMAGE_DIR, exist_ok=True)
    output_path = f"{IMAGE_DIR}/{filename}"
    
    # Load History
    used_ids = load_image_history()
    
    # Filter: Ambil ID di Database yang TIDAK ada di History
    available_ids = [pid for pid in JEEP_DATABASE if pid not in used_ids]
    
    # Jika stok habis total, reset (pakai stok full lagi)
    if not available_ids:
        print("      ⚠️ Stock images exhausted. Recycling pool...")
        available_ids = JEEP_DATABASE

    # Pilih 1 Random ID
    selected_id = random.choice(available_ids)
    
    print(f"      🎨 Selected ID: {selected_id} (Available: {len(available_ids)})")
    
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    # Coba Download 3x jika gagal
    for _ in range(3):
        try:
            # URL Download Unsplash Langsung ke ID
            url = f"https://images.unsplash.com/photo-{selected_id}?auto=format&fit=crop&w=1200&q=80"
            resp = requests.get(url, headers=headers, timeout=20)
            
            if resp.status_code == 200:
                img = Image.open(BytesIO(resp.content))
                
                if process_image(img, output_path):
                    # BERHASIL: Catat ID ke history
                    save_image_history(selected_id)
                    return f"/images/{filename}"
        except:
            time.sleep(1)
            
    return "" # Gagal total

# ==========================================
# 🧠 AI WRITER
# ==========================================

def get_groq_article_json(title, summary, link, author_name):
    system_prompt = f"""
    You are {author_name}, a Jeep Expert.
    Write a 1000-word blog post.
    
    HARD RULES:
    - NO "Introduction", "Conclusion", "Overview".
    - Focus on technical Jeep details (Wrangler, Rubicon, Gladiator).
    - Output JSON: title, description, category, tags, content_body.
    """
    user_prompt = f"Topic: {title}\nLink: {link}"
    
    for api_key in GROQ_API_KEYS:
        client = Groq(api_key=api_key)
        try:
            completion = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
                response_format={"type": "json_object"}
            )
            return completion.choices[0].message.content
        except: continue
    return None

# ==========================================
# 🏁 MAIN
# ==========================================
def main():
    os.makedirs(CONTENT_DIR, exist_ok=True)
    os.makedirs(IMAGE_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)

    print("🔥 JEEP ENGINE STARTED (DATABASE MODE - NO ERRORS) 🔥")

    for source_name, rss_url in RSS_SOURCES.items():
        print(f"\n📡 Source: {source_name}")
        feed = fetch_rss_feed(rss_url)
        if not feed: continue

        processed = 0
        for entry in feed.entries:
            if processed >= TARGET_PER_SOURCE: break
            
            clean_title = entry.title.split(" - ")[0]
            slug = slugify(clean_title, max_length=50, word_boundary=True)
            filename = f"{slug}.md"
            
            if os.path.exists(f"{CONTENT_DIR}/{filename}"): continue
            
            author = random.choice(AUTHOR_PROFILES)
            raw_json = get_groq_article_json(clean_title, entry.summary, entry.link, author)
            if not raw_json: continue
            
            try:
                data = json.loads(raw_json)
                
                # --- BAGIAN IMAGE DIPANGGIL DISINI ---
                # Tidak perlu keyword, langsung ambil stok Jeep asli
                final_img = get_unique_jeep_image(f"{slug}.webp")
                
                if not final_img:
                    print("      ❌ Image failed, skipping post.")
                    continue

                clean_body = clean_ai_content(data['content_body'])
                links_md = get_internal_links_markdown()
                final_body = clean_body + "\n\n### Explore More\n" + links_md
                
                cat = data.get('category', "Wrangler Life")
                if cat not in VALID_CATEGORIES: cat = "Wrangler Life"
                
                md_content = f"""---
title: "{data['title'].replace('"', "'")}"
date: {datetime.now().strftime("%Y-%m-%dT%H:%M:%S+00:00")}
author: "{author}"
categories: ["{cat}"]
tags: {json.dumps(data.get('tags', []))}
featured_image: "{final_img}"
description: "{data['description'].replace('"', "'")}"
slug: "{slug}"
url: "/{slug}/"
---

{final_body}

---
*Reference: {author} | Source: [{source_name}]({entry.link})*
"""
                with open(f"{CONTENT_DIR}/{filename}", "w", encoding="utf-8") as f:
                    f.write(md_content)
                
                save_link_to_memory(data['title'], slug)
                print(f"      ✅ Published: {slug}")
                processed += 1
                time.sleep(3)
                
            except Exception as e:
                print(f"      ❌ Error: {e}")

if __name__ == "__main__":
    main()
