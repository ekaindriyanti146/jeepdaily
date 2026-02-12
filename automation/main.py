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
from groq import Groq, APIError, RateLimitError

# --- SUPPRESS WARNINGS ---
warnings.filterwarnings("ignore", category=FutureWarning)

# --- GOOGLE INDEXING LIBS ---
try:
    from oauth2client.service_account import ServiceAccountCredentials
    from googleapiclient.discovery import build
    GOOGLE_LIBS_AVAILABLE = True
except ImportError:
    GOOGLE_LIBS_AVAILABLE = False
    print("⚠️ Google Indexing Libs not found.")

# ==========================================
# ⚙️ CONFIGURATION & SETUP (JEEP EDITION)
# ==========================================

GROQ_KEYS_RAW = os.environ.get("GROQ_API_KEY", "") 
GROQ_API_KEYS = [k.strip() for k in GROQ_KEYS_RAW.split(",") if k.strip()]

WEBSITE_URL = "https://dother.biz.id" 
INDEXNOW_KEY = "e74819b68a0f40e98f6ec3dc24f610f0" 
GOOGLE_JSON_KEY = os.environ.get("GOOGLE_INDEXING_KEY", "") 

if not GROQ_API_KEYS:
    print("❌ FATAL ERROR: Groq API Key is missing!")
    exit(1)

# TIM PENULIS
AUTHOR_PROFILES = [
    "Rick 'Muddy' O'Connell (Off-road Expert)", 
    "Sarah Miller (Automotive Historian)",
    "Mike Stevens (Jeep Mechanic)", 
    "Tom Davidson (4x4 Reviewer)",
    "Elena Forza (Car Design Analyst)"
]

# KATEGORI JEEP
VALID_CATEGORIES = [
    "Wrangler Life", "Classic Jeeps", "Grand Cherokee", 
    "Gladiator Truck", "Off-road Tips", "Jeep History", "Maintenance & Mods"
]

# RSS SOURCES
RSS_SOURCES = {
    "Jeep Wrangler News": "https://news.google.com/rss/search?q=Jeep+Wrangler+Review+OR+News&hl=en-US&gl=US&ceid=US:en",
    "Jeep Gladiator": "https://news.google.com/rss/search?q=Jeep+Gladiator+News&hl=en-US&gl=US&ceid=US:en",
    "Classic Jeep History": "https://news.google.com/rss/search?q=Classic+Jeep+Willys+History&hl=en-US&gl=US&ceid=US:en",
    "Jeep Concepts": "https://news.google.com/rss/search?q=Jeep+Concept+Cars+Electric&hl=en-US&gl=US&ceid=US:en",
    "Offroad Lifestyle": "https://news.google.com/rss/search?q=Offroad+4x4+Adventure&hl=en-US&gl=US&ceid=US:en"
}

CONTENT_DIR = "content/articles" 
IMAGE_DIR = "static/images"
DATA_DIR = "automation/data"
MEMORY_FILE = f"{DATA_DIR}/link_memory.json"
TARGET_PER_SOURCE = 1 

# Tracker anti-duplikat gambar dalam satu run
USED_IMAGE_IDS = set()

# ==========================================
# 📸 VERIFIED JEEP & OFFROAD NATURE POOL
# ==========================================
UNSPLASH_POOL = {
    # Koleksi Jeep Modern (Sudah dikurasi: Wrangler/Gladiator)
    "wrangler": [
        "1533473359331-0135ef1bcfb0", "1506015391300-4802dc74de2e", "1568285201-168d6945821c",
        "1626243836043-34e85741f0b1", "1535446937720-e9cad5377719", "1585848520031-72782e564d26",
        "1564500096238-76903f56d0d2", "1631553109355-1f8102d96924", "1615901323330-811c77f0438c"
    ],
    # Koleksi Jeep Klasik (Willys/CJ)
    "classic": [
        "1583262612502-869260a99672", "1552932906-e78964d4c207", "1603823483984-7a1926639d67",
        "1519575706483-221027bfbb31", "1559868840-7988566904f4", "1574045330831-50e561a3575c"
    ],
    # ALTERNATIF: Pemandangan Gunung / Jalur Offroad (HANYA JIKA Jeep tidak ditemukan)
    "mountain": [
        "1464822759023-fed622ff2c3b", "1469130198188-466c9869852f", "1500530855697-b586d89ba3ee",
        "1446776811953-b23d57bd21aa", "1530232464733-1466048d0870", "1519681395684-d9598e15133c",
        "1501785887741-f67207455dfb", "1506744038136-46273834b3fb", "1470770841072-c978cf4d019e"
    ]
}

FALLBACK_IMG_URL = "https://images.unsplash.com/photo-1464822759023-fed622ff2c3b?auto=format&fit=crop&w=1200&q=80"

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
    if len(memory) > 200: memory = dict(list(memory.items())[-200:])
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
        response = requests.get(url, headers=headers, timeout=15)
        return feedparser.parse(response.content) if response.status_code == 200 else None
    except: return None

def clean_ai_content(text):
    if not text: return ""
    text = re.sub(r'^```[a-zA-Z]*\n', '', text)
    text = re.sub(r'\n```$', '', text)
    text = text.replace("```", "")
    return text.strip()

# ==========================================
# 🚀 INDEXING FUNCTIONS (LENGKAP DENGAN LOG)
# ==========================================
def submit_to_indexnow(url):
    try:
        endpoint = "https://api.indexnow.org/indexnow"
        host = WEBSITE_URL.replace("https://", "").replace("http://", "")
        data = {
            "host": host,
            "key": INDEXNOW_KEY,
            "keyLocation": f"https://{host}/{INDEXNOW_KEY}.txt",
            "urlList": [url]
        }
        requests.post(endpoint, json=data, headers={'Content-Type': 'application/json; charset=utf-8'}, timeout=5)
        print(f"      🚀 IndexNow Log: Submitted {url}")
    except Exception as e:
        print(f"      ⚠️ IndexNow Error: {e}")

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
    except Exception as e:
        print(f"      ⚠️ Google Indexing Error: {e}")

# ==========================================
# 🎨 UNSPLASH ENGINE (PERFECT RELEVANCE + BRANDING)
# ==========================================

def modify_image_to_be_unique(img):
    """Manipulasi gambar agar unik dan watermark @JeepDaily di posisi aman."""
    try:
        # 1. Flip & Slight Rotation
        if random.random() > 0.5:
            img = ImageOps.mirror(img)
        angle = random.uniform(-1.0, 1.0)
        img = img.rotate(angle, resample=Image.BICUBIC, expand=False)
        
        # 2. Crop 16:9 & Resize
        w, h = img.size
        crop_v = random.uniform(0.04, 0.06)
        img = img.crop((w*crop_v, h*crop_v, w*(1-crop_v), h*(1-crop_v)))
        img = img.resize((1200, 675), Image.Resampling.LANCZOS)

        # 3. Enhance Contrast & Vignette
        img = ImageEnhance.Contrast(img).enhance(1.05)
        vignette = Image.new('L', (1200, 675), 255)
        draw_v = ImageDraw.Draw(vignette)
        draw_v.ellipse((-150, -150, 1350, 825), fill=0)
        vignette = vignette.filter(ImageFilter.GaussianBlur(130))
        img = Image.composite(img, Image.new("RGB", (1200, 675), (15, 15, 15)), ImageOps.invert(vignette))

        # 4. ✨ WATERMARK @JeepDaily (KECIL 18px & MARGIN AMAN) ✨
        txt_layer = Image.new('RGBA', (1200, 675), (255, 255, 255, 0))
        draw_txt = ImageDraw.Draw(txt_layer)
        try:
            # Menggunakan font 18px agar tidak memotong desain
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 18)
        except:
            font = ImageFont.load_default()
        
        watermark_text = "@JeepDaily"
        
        # Penempatan: Margin Kanan 50px, Atas 45px (Sangat Aman)
        # Estimasi lebar teks @JeepDaily ~110px
        text_x = 1200 - 110 - 50 
        text_y = 45
        
        draw_txt.text((text_x, text_y), watermark_text, fill=(255, 255, 255, 140), font=font)
        
        img = img.convert('RGBA')
        img = Image.alpha_composite(img, txt_layer)
        img = img.convert('RGB')
        return img
    except:
        return img

def generate_unsplash_image(keyword, filename):
    global USED_IMAGE_IDS
    if not os.path.exists(IMAGE_DIR): os.makedirs(IMAGE_DIR, exist_ok=True)
    output_path = f"{IMAGE_DIR}/{filename}"
    keyword = keyword.lower()
    
    # Pilih Pool berdasarkan keyword. Jika bukan Jeep, lari ke Gunung/Nature.
    pool_key = 'mountain' 
    if any(x in keyword for x in ['wrangler', 'gladiator', 'rubicon', 'sahara', 'jeep']): 
        pool_key = 'wrangler'
    elif any(x in keyword for x in ['classic', 'willys', 'history', 'cj', 'old']): 
        pool_key = 'classic'
    
    selected_pool = UNSPLASH_POOL[pool_key]
    
    attempts = 0
    headers = {'User-Agent': 'Mozilla/5.0'}

    while attempts < 4:
        # Pilih ID yang belum dipakai di sesi ini
        available_ids = [i for i in selected_pool if i not in USED_IMAGE_IDS]
        if not available_ids: 
            USED_IMAGE_IDS.clear()
            available_ids = selected_pool
        
        selected_id = random.choice(available_ids)
        USED_IMAGE_IDS.add(selected_id)
        
        sig = "".join(random.choices(string.digits, k=5))
        unsplash_url = f"https://images.unsplash.com/photo-{selected_id}?auto=format&fit=crop&w=1250&q=85&sig={sig}"
        
        try:
            print(f"      🎨 Downloading {pool_key.upper()} ID: {selected_id}")
            resp = requests.get(unsplash_url, headers=headers, timeout=25)
            if resp.status_code == 200:
                img = Image.open(BytesIO(resp.content)).convert("RGB")
                img = modify_image_to_be_unique(img)
                img.save(output_path, "WEBP", quality=85, method=6)
                
                # Verifikasi Ketat: Pastikan file tidak kosong (minimal 4KB)
                if os.path.exists(output_path) and os.path.getsize(output_path) > 4096:
                    return f"/images/{filename}"
        except: pass
        attempts += 1
        time.sleep(2)

    return FALLBACK_IMG_URL

# ==========================================
# 🧠 JEEP CONTENT ENGINE (GROQ)
# ==========================================

def get_groq_article_json(title, summary, link, author_name):
    current_date = datetime.now().strftime("%Y-%m-%d")
    system_prompt = f"You are {author_name}, a Jeep Expert. Write a high-quality 1000-word article in Markdown. Output JSON with: title, description, category, main_keyword, tags, content_body."
    user_prompt = f"Topic: {title}\nSummary: {summary}\nLink: {link}"
    
    for api_key in GROQ_API_KEYS:
        client = Groq(api_key=api_key)
        try:
            print(f"      🤖 AI Writing ({author_name})...")
            completion = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
                temperature=0.6,
                max_tokens=8000,
                response_format={"type": "json_object"}
            )
            return completion.choices[0].message.content
        except: continue
    return None

# ==========================================
# 🏁 MAIN WORKFLOW (LENGKAP 100%)
# ==========================================
def main():
    os.makedirs(CONTENT_DIR, exist_ok=True)
    os.makedirs(IMAGE_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)

    print("🔥 JEEP BRANDED ENGINE STARTED 🔥")

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
            raw_json = get_groq_article_json(clean_title, entry.summary, entry.link, author)
            if not raw_json: continue
            
            try:
                data = json.loads(raw_json)
                # Image Engine: Strict Jeep or Mountain
                final_img = generate_unsplash_image(data.get('main_keyword', clean_title), f"{slug}.webp")
                
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
draft: false
weight: {random.randint(1, 10)}
---

{final_body}

---
*Reference: Automotive analysis by {author} based on news from [{source_name}]({entry.link}).*
"""
                with open(f"{CONTENT_DIR}/{filename}", "w", encoding="utf-8") as f:
                    f.write(md_content)
                
                save_link_to_memory(data['title'], slug)
                
                # Submit Indexing (Google & IndexNow)
                full_url = f"{WEBSITE_URL}/{slug}/"
                submit_to_indexnow(full_url)
                submit_to_google(full_url)

                print(f"      ✅ Successfully Published: {slug}")
                processed += 1
                time.sleep(5)
            except Exception as e:
                print(f"      ❌ Error processing article: {e}")

if __name__ == "__main__":
    main()
