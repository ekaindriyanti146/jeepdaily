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
from PIL import Image

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
# ⚙️ CONFIGURATION & SETUP
# ==========================================

# Endpoint dari server Hugging Face yang Anda berikan
GROK_GATEWAY_URL = "https://velmamore-grok-api-free.hf.space/v1/chat/completions"
# API Key yang diatur di Admin Panel server tersebut
GROK_API_KEY = os.environ.get("GROK_API_KEY", "your-admin-api-key") 

WEBSITE_URL = "https://beastion.biz.id" 
INDEXNOW_KEY = "e74819b68a0f40e98f6ec3dc24f610f0" 
GOOGLE_JSON_KEY = os.environ.get("GOOGLE_INDEXING_KEY", "") 

AUTHOR_PROFILES = [
    "Dave Harsya (Tactical Analyst)", "Sarah Jenkins (Senior Editor)",
    "Luca Romano (Market Expert)", "Marcus Reynolds (League Correspondent)"
]

VALID_CATEGORIES = ["Transfer News", "Premier League", "Champions League", "La Liga", "International"]

RSS_SOURCES = {
    "SkySports": "https://www.skysports.com/rss/12040",
    "BBC Football": "https://feeds.bbci.co.uk/sport/football/rss.xml"
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
    return text.strip()

# ==========================================
# 🤖 GROK GATEWAY CLIENT (CORE)
# ==========================================

def call_grok_gateway(messages, model="grok-4.1"):
    """Memanggil endpoint tunggal /v1/chat/completions sesuai dokumentasi Grok Gateway"""
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
        response = requests.post(GROK_GATEWAY_URL, headers=headers, json=payload, timeout=120)
        if response.status_code == 200:
            return response.json()
        else:
            print(f"      ⚠️ API Error {response.status_code}: {response.text}")
            return None
    except Exception as e:
        print(f"      ⚠️ Connection Error: {e}")
        return None

# ==========================================
# 🎨 IMAGE GENERATION (Sesuai Cara Kerja Gateway)
# ==========================================

def generate_image_grok(keyword, filename):
    """Memicu generate image dengan instruksi 'Draw' di chat completions"""
    output_path = f"{IMAGE_DIR}/{filename}"
    
    # Instruksi spesifik 'Draw' sesuai fitur Gateway untuk memicu FLUX model
    prompt = f"Draw a realistic cinematic sports photography of {keyword}. High resolution, action shot."
    
    messages = [{"role": "user", "content": prompt}]
    
    print(f"      🎨 Triggering Grok Image Gen for: {keyword}")
    # Menggunakan model grok-4.1 yang mendukung image generation
    response = call_grok_gateway(messages, model="grok-4.1")
    
    if response and 'choices' in response:
        content = response['choices'][0]['message']['content']
        # Gateway biasanya mengembalikan URL gambar di dalam teks atau format khusus
        urls = re.findall(r'(https?://[^\s)]+)', content)
        
        image_url = None
        for url in urls:
            if any(ext in url.lower() for ext in ['.png', '.jpg', '.jpeg', '.webp', 'generated']):
                image_url = url.split(')')[0] # Bersihkan jika dalam format markdown
                break
        
        if not image_url and urls: image_url = urls[0].split(')')[0]

        if image_url:
            try:
                img_resp = requests.get(image_url, timeout=30)
                if img_resp.status_code == 200:
                    img = Image.open(BytesIO(img_resp.content)).convert("RGB")
                    img = img.resize((1200, 675), Image.Resampling.LANCZOS)
                    img.save(output_path, "WEBP", quality=85)
                    return f"/images/{filename}"
            except: pass
            
    print("      ⚠️ Image Gen Failed, returning Unsplash fallback.")
    return "https://images.unsplash.com/photo-1522778119026-d647f0565c6a?auto=format&fit=crop&w=1200&q=80"

# ==========================================
# 📝 ARTICLE GENERATION
# ==========================================

def generate_article_grok(title, summary, link, author_name):
    system_prompt = f"You are {author_name}, a sports journalist. Write a 1000-word markdown article. Return ONLY a JSON object with keys: title, description, category, main_keyword, tags, content_body."
    user_prompt = f"Source: {title}. Summary: {summary}. Source Link: {link}."
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]
    
    print(f"      🤖 Grok Writing Article...")
    # Menggunakan grok-4-fast untuk kecepatan penulisan artikel
    response = call_grok_gateway(messages, model="grok-4-fast")
    
    if response and 'choices' in response:
        content = response['choices'][0]['message']['content']
        content = clean_ai_content(content)
        # Mencoba mengekstrak JSON dari teks jika ada teks tambahan
        try:
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match: return json_match.group(0)
        except: pass
        return content
    return None

# ==========================================
# 🏁 MAIN WORKFLOW
# ==========================================
def main():
    os.makedirs(CONTENT_DIR, exist_ok=True)
    os.makedirs(IMAGE_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)

    print(f"🔥 ENGINE STARTED: GROK GATEWAY MODE")

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
            
            # 1. Generate Teks
            author = random.choice(AUTHOR_PROFILES)
            raw_json = generate_article_grok(clean_title, entry.summary, entry.link, author)
            
            if not raw_json: continue
            try:
                data = json.loads(raw_json)
            except: continue

            # 2. Generate Gambar (PENTING: Gunakan model grok-4.1)
            keyword = data.get('main_keyword') or clean_title
            final_img = generate_image_grok(keyword, f"{slug}.webp")
            
            # 3. Save Markdown
            md_body = clean_ai_content(data['content_body'])
            
            md_content = f"""---
title: "{data['title'].replace('"', "'")}"
date: {datetime.now().strftime("%Y-%m-%dT%H:%M:%S+00:00")}
author: "{author}"
categories: ["{data.get('category', 'International')}"]
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
            print(f"      ✅ Published: {slug}")
            processed += 1
            time.sleep(5)

if __name__ == "__main__":
    main()
