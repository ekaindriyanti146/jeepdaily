import os
import json
import requests
import feedparser
import time
import re
import random
import warnings 
import subprocess
import string
from urllib.parse import quote
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
# 🎨 POLLINATIONS AI ENGINE (CURL BYPASS VERSION)
# ==========================================

def add_watermark(image_path):
    """
    Membuka gambar dari path, memberi watermark, lalu save ulang (overwrite).
    """
    try:
        if not os.path.exists(image_path): return
        
        img = Image.open(image_path)
        img = img.convert("RGB")
        draw = ImageDraw.Draw(img)
        text = "@JeepDaily"
        
        # Font handling
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 26)
        except:
            font = ImageFont.load_default()
            
        img_w, img_h = img.size
        text_bbox = draw.textbbox((0, 0), text, font=font)
        text_w = text_bbox[2] - text_bbox[0]
        text_h = text_bbox[3] - text_bbox[1]
        
        x = img_w - text_w - 40
        y = 40
        
        # Shadow & Text
        draw.text((x+3, y+3), text, fill=(0, 0, 0, 160), font=font)
        draw.text((x, y), text, fill=(255, 255, 255, 240), font=font)
        
        # Save overwrite as optimized WEBP
        img.save(image_path, "WEBP", quality=90)
        
    except Exception as e:
        print(f"      ⚠️ Watermark error: {e}")

def generate_cartoon_image(keyword, filename):
    """
    Menggunakan 'curl' sistem operasi untuk bypass Error 530/403.
    """
    if not os.path.exists(IMAGE_DIR): os.makedirs(IMAGE_DIR, exist_ok=True)
    output_path = f"{IMAGE_DIR}/{filename}"
    
    # 1. Bersihkan Keyword (Hanya alphanumeric) agar URL bersih
    clean_keyword = re.sub(r'[^\w\s]', '', keyword).strip()
    if len(clean_keyword) > 80: clean_keyword = clean_keyword[:80]
    
    # 2. Prompt Style
    prompt = f"{clean_keyword} cartoon vector art jeep offroad gta style flat color 8k"
    encoded_prompt = quote(prompt)
    
    print(f"      🎨 Generating AI Image for: '{clean_keyword}'")

    # 3. List Model untuk dicoba
    # Kita coba 'flux' dulu, kalau gagal 'turbo'
    models = ["flux", "turbo"]
    
    for model in models:
        try:
            seed = random.randint(100, 99999999)
            # URL Pollinations
            url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1280&height=720&seed={seed}&nologo=true&model={model}"
            
            # --- TEKNIK CURL (BYPASS PYTHON REQUESTS) ---
            # Kita panggil command line linux 'curl' yang lebih tahan banting
            command = [
                "curl", 
                "-L",                # Follow redirects
                "-A", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36", # User Agent Palsu
                "--retry", "2",      # Coba ulang 2x jika putus
                "--max-time", "60",  # Timeout 60 detik
                "-o", output_path,   # Output ke file
                url
            ]
            
            # Jalankan perintah
            result = subprocess.run(command, capture_output=True, text=True)
            
            # Cek apakah file berhasil didownload
            if os.path.exists(output_path) and os.path.getsize(output_path) > 3000:
                # Cek header file apakah benar gambar (bukan HTML error)
                try:
                    img_check = Image.open(output_path)
                    img_check.verify() # Validasi integritas gambar
                    
                    # Jika valid, beri watermark
                    add_watermark(output_path)
                    return f"/images/{filename}"
                except Exception:
                    print(f"      ⚠️ File downloaded but corrupted/invalid image (Model: {model})")
                    os.remove(output_path) # Hapus file rusak
            else:
                print(f"      ⚠️ Curl failed or empty file (Model: {model})")
                
        except Exception as e:
            print(f"      ❌ System Call Error: {e}")
            
        time.sleep(3) # Jeda sebelum ganti model

    print("      ❌ Failed to generate image with all methods.")
    return ""

# ==========================================
# ⚙️ STANDARD CONFIG
# ==========================================

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
# 🧠 CONTENT ENGINE
# ==========================================

def get_groq_article_json(title, summary, link, author_name):
    system_prompt = f"""
    You are {author_name}, a Senior Automotive Journalist & SEO Specialist.
    TASK: Write a comprehensive blog post (1000+ words).
    
    ### STRUCTURE:
    - **H1:** Provided.
    - **H2 (##):** 3-4 Main Headings.
    - **H3 (###):** Sub-headings.
    - **Tables:** Must include a Markdown Table.
    - **Lists:** Bullet points for features.
    
    ### OUTPUT JSON KEYS: 
    - "title", "description", "category", "main_keyword", "tags", "content_body"
    
    Note: 'main_keyword' should be a short visual description for an image (max 6 words).
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
                max_tokens=7000,
                response_format={"type": "json_object"}
            )
            return completion.choices[0].message.content
        except Exception as e:
            print(f"      ⚠️ AI Gen Error: {e}")
            continue
    return None

# ==========================================
# 🏁 MAIN WORKFLOW
# ==========================================
def main():
    os.makedirs(CONTENT_DIR, exist_ok=True)
    os.makedirs(IMAGE_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)

    print("🔥 JEEP ENGINE STARTED (CURL MODE ACTIVATED) 🔥")

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
            
            # 1. Content
            raw_json = get_groq_article_json(clean_title, entry.summary, entry.link, author)
            if not raw_json: continue
            
            try:
                data = json.loads(raw_json)
                
                # 2. Image (Call CURL function)
                image_keyword = data.get('main_keyword', clean_title)
                final_img = generate_cartoon_image(image_keyword, f"{slug}.webp")
                
                # Jika masih kosong juga, isi string kosong biar gak error
                if not final_img: final_img = ""

                # 3. Save
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
                
                # Jeda agar IP tidak dibanned
                time.sleep(8) 
            except Exception as e:
                print(f"      ❌ Critical Error: {e}")

if __name__ == "__main__":
    main()
