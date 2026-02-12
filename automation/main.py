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
from groq import Groq, APIError

# --- SUPPRESS WARNINGS ---
warnings.filterwarnings("ignore", category=FutureWarning)

# --- GOOGLE INDEXING LIBS ---
try:
    from oauth2client.service_account import ServiceAccountCredentials
    from googleapiclient.discovery import build
    GOOGLE_LIBS_AVAILABLE = True
except ImportError:
    GOOGLE_LIBS_AVAILABLE = False
    print("⚠️ Google Indexing Libs not found (Skipping).")

# ==========================================
# ⚙️ CONFIGURATION & SETUP
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
# 📸 DATABASE GAMBAR (HANYA JEEP & OFFROAD)
# ==========================================
# ID ini sudah dikurasi. Isinya: Wrangler, Rubicon, Gladiator, dan Trail.
JEEP_IDS = [
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
    "1530232464733-1466048d0870", "1566060143896-1c865147517c", "1618420653063-228741366113",
    "1512404285859-69f69137d57a", "1504215680494-cf56012895d4", "1536411232873-6c827364b58e",
    "1617788138017-80ad40651399", "1603584173870-7f23fdae1b5a", "1519681395684-d9598e15133c",
    "1464822759023-fed622ff2c3b", "1469130198188-466c9869852f", "1500530855697-b586d89ba3ee"
]

AUTHOR_PROFILES = [
    "Rick 'Muddy' O'Connell (Off-road Expert)", 
    "Sarah Miller (Automotive Historian)",
    "Mike Stevens (Jeep Mechanic)", 
    "Tom Davidson (4x4 Reviewer)",
    "Elena Forza (Car Design Analyst)"
]

VALID_CATEGORIES = [
    "Wrangler Life", "Classic Jeeps", "Grand Cherokee", 
    "Gladiator Truck", "Off-road Tips", "Jeep History", "Maintenance & Mods"
]

RSS_SOURCES = {
    "Jeep Wrangler News": "https://news.google.com/rss/search?q=Jeep+Wrangler+Review+OR+News&hl=en-US&gl=US&ceid=US:en",
    "Jeep Gladiator": "https://news.google.com/rss/search?q=Jeep+Gladiator+News&hl=en-US&gl=US&ceid=US:en",
    "Classic Jeep History": "https://news.google.com/rss/search?q=Classic+Jeep+Willys+History&hl=en-US&gl=US&ceid=US:en",
    "Offroad Lifestyle": "https://news.google.com/rss/search?q=Offroad+4x4+Adventure&hl=en-US&gl=US&ceid=US:en"
}

CONTENT_DIR = "content/articles" 
IMAGE_DIR = "static/images"
DATA_DIR = "automation/data"
MEMORY_FILE = f"{DATA_DIR}/link_memory.json"
HISTORY_FILE = f"{DATA_DIR}/used_images.json"
TARGET_PER_SOURCE = 1 

# ==========================================
# 🧠 HELPER FUNCTIONS
# ==========================================
def load_link_memory():
    if not os.path.exists(MEMORY_FILE): return {}
    try:
        with open(MEMORY_FILE, 'r') as f: return json.load(f)
    except: return {}

def save_link_to_memory(title, slug):
    os.makedirs(DATA_DIR, exist_ok=True)
    memory = load_link_memory()
    memory[title] = f"/articles/{slug}" 
    if len(memory) > 300: memory = dict(list(memory.items())[-300:])
    with open(MEMORY_FILE, 'w') as f: json.dump(memory, f, indent=2)

def get_internal_links_markdown():
    memory = load_link_memory()
    items = list(memory.items())
    if not items: return ""
    count = min(4, len(items))
    selected_items = random.sample(items, count)
    return "\n".join([f"- [{title}]({url})" for title, url in selected_items])

def fetch_rss_feed(url):
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        response = requests.get(url, headers=headers, timeout=20)
        return feedparser.parse(response.content) if response.status_code == 200 else None
    except: return None

def clean_ai_content(text):
    if not text: return ""
    # Hapus wrapper markdown ``` yang sering dikasih AI
    text = re.sub(r'^```[a-zA-Z]*\n', '', text)
    text = re.sub(r'\n```$', '', text)
    text = text.replace("```", "")
    return text.strip()

# ==========================================
# 🚀 INDEXING LOGS
# ==========================================
def submit_to_indexnow(url):
    try:
        endpoint = "https://api.indexnow.org/indexnow"
        host = WEBSITE_URL.replace("https://", "").replace("http://", "")
        data = {"host": host, "key": INDEXNOW_KEY, "keyLocation": f"https://{host}/{INDEXNOW_KEY}.txt", "urlList": [url]}
        requests.post(endpoint, json=data, headers={'Content-Type': 'application/json; charset=utf-8'}, timeout=5)
        print(f"      🚀 IndexNow Log: Submitted {url}")
    except: pass

def submit_to_google(url):
    if not GOOGLE_JSON_KEY or not GOOGLE_LIBS_AVAILABLE: return
    try:
        creds_dict = json.loads(GOOGLE_JSON_KEY)
        SCOPES = ["https://www.googleapis.com/auth/indexing"]
        credentials = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, SCOPES)
        service = build("indexing", "v3", credentials=credentials)
        body = {"url": url, "type": "URL_UPDATED"}
        service.urlNotifications().publish(body=body).execute()
        print(f"      🚀 Google Log: Submitted {url}")
    except: pass

# ==========================================
# 🎨 IMAGE ENGINE (DATABASE + VISUAL REMIX)
# ==========================================

def load_image_history():
    if not os.path.exists(HISTORY_FILE): return []
    try:
        with open(HISTORY_FILE, 'r') as f: return json.load(f)
    except: return []

def save_image_to_history(img_id):
    history = load_image_history()
    if img_id not in history:
        history.append(img_id)
        # Reset jika history kepenuhan agar bisa recycle
        if len(history) >= len(JEEP_IDS): history = history[-20:]
        with open(HISTORY_FILE, 'w') as f: json.dump(history, f)

def modify_image(img):
    """
    Membuat gambar terlihat baru & unik dengan manipulasi visual.
    """
    try:
        img = img.convert('RGB')
        
        # 1. Flip (Cermin) - 50% kemungkinan
        if random.random() > 0.5:
            img = ImageOps.mirror(img)
            
        # 2. Rotasi & Crop (Untuk mengubah struktur pixel/hash)
        angle = random.uniform(-1.5, 1.5)
        img = img.rotate(angle, resample=Image.BICUBIC, expand=False)
        w, h = img.size
        crop_v = 0.02
        img = img.crop((w*crop_v, h*crop_v, w*(1-crop_v), h*(1-crop_v)))
        img = img.resize((1200, 675), Image.Resampling.LANCZOS)

        # 3. Color Grading (Mood)
        # Agar tiap post beda nuansa (Pagi, Sore, High Contrast)
        style = random.choice(['warm', 'cool', 'contrast'])
        if style == 'warm': 
            overlay = Image.new('RGB', img.size, (255, 180, 100))
            img = Image.blend(img, overlay, 0.1)
        elif style == 'cool':
            overlay = Image.new('RGB', img.size, (100, 180, 255))
            img = Image.blend(img, overlay, 0.1)
        else:
            img = ImageEnhance.Contrast(img).enhance(1.15)

        # 4. Watermark (@JeepDaily)
        draw = ImageDraw.Draw(img)
        text = "@JeepDaily"
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 20)
        except:
            font = ImageFont.load_default()
            
        # Posisi text (Kanan Atas)
        draw.text((1052, 42), text, fill=(0, 0, 0, 150), font=font) # Shadow
        draw.text((1050, 40), text, fill=(255, 255, 255, 180), font=font) # Text
        
        return img
    except:
        return img

def get_jeep_image(filename):
    if not os.path.exists(IMAGE_DIR): os.makedirs(IMAGE_DIR, exist_ok=True)
    output_path = f"{IMAGE_DIR}/{filename}"
    
    used_ids = load_image_history()
    # Cari ID yang belum dipakai
    available = [pid for pid in JEEP_IDS if pid not in used_ids]
    
    # Jika habis, pakai semua (recycle) tapi nanti di-remix visualnya
    if not available:
        available = JEEP_IDS
        
    selected_id = random.choice(available)
    print(f"      🎨 Downloading Image ID: {selected_id}")

    try:
        url = f"https://images.unsplash.com/photo-{selected_id}?auto=format&fit=crop&w=1200&q=80"
        resp = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=20)
        
        if resp.status_code == 200:
            img = Image.open(BytesIO(resp.content))
            final_img = modify_image(img)
            final_img.save(output_path, "WEBP", quality=85)
            save_image_to_history(selected_id)
            return f"/images/{filename}"
    except Exception as e:
        print(f"      ❌ Image Error: {e}")
        
    return "/images/default-jeep.webp"

# ==========================================
# 🧠 CONTENT ENGINE (RESTORED HIGH QUALITY)
# ==========================================

def get_groq_article_json(title, summary, link, author_name):
    # Prompt ini dikembalikan ke versi LENGKAP agar artikel tidak rusak formatnya
    system_prompt = f"""
    You are {author_name}, a professional Automotive Journalist specializing in Jeep.
    
    TASK: Write a comprehensive, high-quality blog post (approx 800-1000 words).
    
    FORMATTING RULES (CRITICAL):
    1. USE MARKDOWN syntax for all formatting.
    2. Split the text into clear paragraphs. DO NOT write a wall of text.
    3. Use H2 (##) for main sections and H3 (###) for subsections.
    4. If discussing a vehicle model, INCLUDE A MARKDOWN TABLE of specs (Engine, HP, Torque, Towing).
    5. Use bullet points for feature lists.
    
    CONTENT RULES:
    - Tone: Authoritative, enthusiastic, yet technical.
    - NO generic intros like "In this article..." or "Let's dive in...".
    - Focus on off-road capabilities, mechanics, and heritage.
    
    OUTPUT FORMAT:
    Return ONLY a JSON object with keys: "title", "description", "category", "tags", "content_body".
    """
    
    user_prompt = f"Topic: {title}\nSummary context: {summary}\nSource Link: {link}"
    
    for api_key in GROQ_API_KEYS:
        client = Groq(api_key=api_key)
        try:
            print(f"      🤖 AI Writing ({author_name})...")
            completion = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
                temperature=0.6,
                max_tokens=6500,
                response_format={"type": "json_object"}
            )
            return completion.choices[0].message.content
        except: continue
    return None

# ==========================================
# 🏁 MAIN WORKFLOW
# ==========================================
def main():
    os.makedirs(CONTENT_DIR, exist_ok=True)
    os.makedirs(IMAGE_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)

    print("🔥 JEEP ENGINE RESTARTED (FIXED FORMAT & IMAGES) 🔥")

    for source_name, rss_url in RSS_SOURCES.items():
        print(f"\n📡 Reading Source: {source_name}")
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
            
            # Generate Artikel (Format JSON)
            raw_json = get_groq_article_json(clean_title, entry.summary, entry.link, author)
            if not raw_json: continue
            
            try:
                data = json.loads(raw_json)
                
                # Generate Gambar dari Database Jeep
                final_img = get_jeep_image(f"{slug}.webp")
                
                # Format Body Markdown
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
*Reference: Automotive analysis by {author} based on news from [{source_name}]({entry.link}).*
"""
                with open(f"{CONTENT_DIR}/{filename}", "w", encoding="utf-8") as f:
                    f.write(md_content)
                
                save_link_to_memory(data['title'], slug)
                
                # Indexing
                full_url = f"{WEBSITE_URL}/{slug}/"
                submit_to_indexnow(full_url)
                submit_to_google(full_url)

                print(f"      ✅ Successfully Published: {slug}")
                processed += 1
                time.sleep(5) # Jeda aman
            except Exception as e:
                print(f"      ❌ Critical Error: {e}")

if __name__ == "__main__":
    main()
