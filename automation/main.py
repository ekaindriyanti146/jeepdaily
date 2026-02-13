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
from PIL import Image, ImageEnhance, ImageOps, ImageFilter

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
# ⚙️ CONFIGURATION & SETUP
# ==========================================

# ⚠️ URL INI SANGAT PENTING. JANGAN UBAH FORMATNYA.
# Format yang benar untuk Direct API Hugging Face Space adalah:
# https://{username}-{spacename}.hf.space/v1/chat/completions
GROK_API_URL = "https://velmamore-grok-api-free.hf.space/v1/chat/completions"

# API Key Admin (Sesuai settingan di Admin Panel server Anda)
GROK_API_KEY = os.environ.get("GROK_API_KEY", "admin") 

WEBSITE_URL = "https://beastion.biz.id" 
INDEXNOW_KEY = "e74819b68a0f40e98f6ec3dc24f610f0" 
GOOGLE_JSON_KEY = os.environ.get("GOOGLE_INDEXING_KEY", "") 

# TIM PENULIS
AUTHOR_PROFILES = [
    "Dave Harsya (Tactical Analyst)", "Sarah Jenkins (Senior Editor)",
    "Luca Romano (Market Expert)", "Marcus Reynolds (League Correspondent)",
    "Ben Foster (Data Journalist)"
]

RSS_SOURCES = {
    "SkySports": "https://www.skysports.com/rss/12040",
    "BBC Football": "https://feeds.bbci.co.uk/sport/football/rss.xml",
    "ESPN FC": "https://www.espn.com/espn/rss/soccer/news",
    "The Guardian": "https://www.theguardian.com/football/rss"
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
    with open(MEMORY_FILE, 'w') as f: json.dump(memory, f, indent=2)

def fetch_rss_feed(url):
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        return feedparser.parse(response.content) if response.status_code == 200 else None
    except: return None

def clean_ai_content(text):
    if not text: return ""
    text = re.sub(r'^```[a-zA-Z]*\n', '', text)
    text = re.sub(r'\n```$', '', text)
    text = text.replace("```", "")
    return text.strip()

# ==========================================
# 🤖 GROK GATEWAY CLIENT (ROBUST VERSION)
# ==========================================

def check_server_health():
    """Mengecek apakah Server Hugging Face Hidup/Bangun"""
    print("      🔍 Checking Grok Server status...")
    try:
        # Ping root domain untuk membangunkan space
        root_url = "https://velmamore-grok-api-free.hf.space"
        requests.get(root_url, timeout=5)
    except:
        pass # Ignore error on ping, just try to wake it up

def call_grok_gateway(messages, model="grok-4.1"):
    """
    Memanggil API dengan penanganan Error HTML (404/502/503) yang lebih baik.
    """
    headers = {
        "Authorization": f"Bearer {GROK_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": model,
        "messages": messages,
        "stream": False
    }
    
    try:
        response = requests.post(GROK_API_URL, headers=headers, json=payload, timeout=120)
        
        # Cek jika responsenya HTML (Tanda Server Error / Salah URL)
        content_type = response.headers.get('Content-Type', '')
        if 'text/html' in content_type:
            print(f"      ❌ SERVER ERROR: Hugging Face Space is returning HTML (404/500).")
            print(f"      👉 Penyebab: Server sedang 'Building', 'Sleeping', atau URL salah.")
            return None

        if response.status_code == 200:
            return response.json()
        else:
            print(f"      ⚠️ API Error {response.status_code}: {response.text[:200]}")
            return None
            
    except Exception as e:
        print(f"      ⚠️ Connection Exception: {e}")
        return None

# ==========================================
# 🎨 IMAGE GENERATION
# ==========================================

def generate_image_grok(keyword, filename):
    output_path = f"{IMAGE_DIR}/{filename}"
    
    # Prompt khusus untuk trigger Image Gen di Grok Gateway
    prompt = f"Draw a realistic high-quality sports photo of {keyword}. Action shot, 4k resolution."
    
    print(f"      🎨 Requesting Image: {keyword}")
    
    # Gunakan model grok-4.1 (Support Image)
    response = call_grok_gateway([{"role": "user", "content": prompt}], model="grok-4.1")
    
    if response and 'choices' in response:
        content = response['choices'][0]['message']['content']
        
        # Ekstrak URL gambar dari markdown/text
        urls = re.findall(r'(https?://[^\s)]+)', content)
        image_url = None
        
        # Cari URL yang valid
        for url in urls:
            clean_url = url.split(')')[0].strip('."')
            if any(x in clean_url for x in ['generated', 'blob', 'png', 'jpg', 'webp']):
                image_url = clean_url
                break
        
        # Download jika URL ketemu
        if image_url:
            try:
                print(f"      ⬇️ Downloading: {image_url[:40]}...")
                img_resp = requests.get(image_url, timeout=30)
                if img_resp.status_code == 200:
                    img = Image.open(BytesIO(img_resp.content)).convert("RGB")
                    img = img.resize((1200, 675), Image.Resampling.LANCZOS)
                    img.save(output_path, "WEBP", quality=85)
                    return f"/images/{filename}"
            except Exception as e:
                print(f"      ⚠️ Download Failed: {e}")

    # Fallback Unsplash
    print("      ⚠️ Grok Image Failed. Using Fallback.")
    return "https://images.unsplash.com/photo-1522778119026-d647f0565c6a?auto=format&fit=crop&w=1200&q=80"

# ==========================================
# 📝 ARTICLE GENERATION
# ==========================================

def generate_article_grok(title, summary, link, author_name):
    current_date = datetime.now().strftime("%Y-%m-%d")
    
    system_prompt = f"""
    You are {author_name}, a sports journalist. Date: {current_date}.
    Write a 800-word analysis article in MARKDOWN format.
    Return ONLY a JSON object with keys: title, description, category, main_keyword, tags, content_body.
    """
    
    user_prompt = f"News: {title}\nSummary: {summary}\nLink: {link}"
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]
    
    print(f"      🤖 Grok Writing...")
    # Gunakan grok-4-fast untuk artikel
    response = call_grok_gateway(messages, model="grok-4-fast")
    
    if response and 'choices' in response:
        content = response['choices'][0]['message']['content']
        content = clean_ai_content(content)
        
        # Ekstrak JSON paksa (in case ada teks pembuka)
        try:
            match = re.search(r'\{.*\}', content, re.DOTALL)
            if match: return match.group(0)
            return content 
        except: return content
        
    return None

# ==========================================
# 🏁 MAIN WORKFLOW
# ==========================================
def main():
    os.makedirs(CONTENT_DIR, exist_ok=True)
    os.makedirs(IMAGE_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)

    print(f"🔥 ENGINE STARTED: GROK GATEWAY")
    
    # 1. Cek Server Dulu!
    check_server_health()

    for source_name, rss_url in RSS_SOURCES.items():
        print(f"\n📡 RSS Source: {source_name}")
        feed = fetch_rss_feed(rss_url)
        if not feed: continue

        processed = 0
        for entry in feed.entries:
            if processed >= TARGET_PER_SOURCE: break
            
            clean_title = entry.title.split(" - ")[0]
            slug = slugify(clean_title, max_length=60)
            filename = f"{slug}.md"
            
            if os.path.exists(f"{CONTENT_DIR}/{filename}"): continue
            
            print(f"   ⚡ Processing: {clean_title[:30]}...")
            
            # GENERATE ARTIKEL
            author = random.choice(AUTHOR_PROFILES)
            raw_json = generate_article_grok(clean_title, entry.summary, entry.link, author)
            
            if not raw_json: 
                print("      ❌ Failed to get content response.")
                continue

            try:
                data = json.loads(raw_json)
            except:
                print("      ❌ JSON Parsing Error.")
                continue

            # GENERATE GAMBAR
            keyword = data.get('main_keyword') or clean_title
            final_img = generate_image_grok(keyword, f"{slug}.webp")
            
            # SAVE MARKDOWN
            md_body = clean_ai_content(data['content_body'])
            cat = data.get('category', 'International')
            
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

{md_body}
"""
            with open(f"{CONTENT_DIR}/{filename}", "w", encoding="utf-8") as f:
                f.write(md_content)
            
            save_link_to_memory(data['title'], slug)
            
            # Submit Indexing
            full_url = f"{WEBSITE_URL}/articles/{slug}/"
            # (Fungsi submit indexnow/google ada di blok import awal jika diperlukan)
            
            print(f"      ✅ Published: {slug}")
            processed += 1
            time.sleep(5)

if __name__ == "__main__":
    main()
