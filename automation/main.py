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
    print("⚠️ Google Indexing Libs not found. Install: pip install google-api-python-client oauth2client")

# ==========================================
# ⚙️ CONFIGURATION & SETUP
# ==========================================

# Endpoint Baru dari Hugging Face Space
GROK_API_BASE = "https://velmamore-grok-api-free.hf.space/v1"
# API Key (Bisa dummy jika space tidak diproteksi, atau ambil dari Env)
GROK_API_KEY = os.environ.get("GROK_API_KEY", "dummy-key") 

WEBSITE_URL = "https://beastion.biz.id" 
INDEXNOW_KEY = "e74819b68a0f40e98f6ec3dc24f610f0" 
GOOGLE_JSON_KEY = os.environ.get("GOOGLE_INDEXING_KEY", "") 

# TIM PENULIS
AUTHOR_PROFILES = [
    "Dave Harsya (Tactical Analyst)", "Sarah Jenkins (Senior Editor)",
    "Luca Romano (Market Expert)", "Marcus Reynolds (League Correspondent)",
    "Ben Foster (Data Journalist)"
]

VALID_CATEGORIES = [
    "Transfer News", "Premier League", "Champions League", 
    "La Liga", "International", "Tactical Analysis"
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
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        return feedparser.parse(response.content) if response.status_code == 200 else None
    except: return None

def clean_ai_content(text):
    """Membersihkan output AI dari wrapper code block dan tag HTML"""
    if not text: return ""
    text = re.sub(r'^```[a-zA-Z]*\n', '', text)
    text = re.sub(r'\n```$', '', text)
    text = text.replace("```", "")
    
    # HTML cleaner simple
    text = text.replace("<h1>", "# ").replace("</h1>", "\n")
    text = text.replace("<h2>", "## ").replace("</h2>", "\n")
    text = text.replace("<h3>", "### ").replace("</h3>", "\n")
    text = text.replace("<b>", "**").replace("</b>", "**")
    text = text.replace("<p>", "").replace("</p>", "\n\n")
    
    return text.strip()

# ==========================================
# 🚀 INDEXING FUNCTIONS
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
        print(f"      🚀 IndexNow Submitted")
    except Exception as e:
        print(f"      ⚠️ IndexNow Failed: {e}")

def submit_to_google(url):
    if not GOOGLE_JSON_KEY or not GOOGLE_LIBS_AVAILABLE: return
    try:
        creds_dict = json.loads(GOOGLE_JSON_KEY)
        SCOPES = ["https://www.googleapis.com/auth/indexing"]
        credentials = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, SCOPES)
        service = build("indexing", "v3", credentials=credentials)
        body = {"url": url, "type": "URL_UPDATED"}
        service.urlNotifications().publish(body=body).execute()
        print(f"      🚀 Google Indexing Submitted")
    except Exception as e:
        print(f"      ⚠️ Google Indexing Error: {e}")

# ==========================================
# 🤖 GROK API CLIENT (CUSTOM)
# ==========================================

def grok_chat_completion(messages, model="grok-beta", stream=False):
    """Fungsi pembantu untuk memanggil API Grok via HTTP Request"""
    url = f"{GROK_API_BASE}/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROK_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": model,
        "messages": messages,
        "stream": stream
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=60)
        if response.status_code == 200:
            return response.json()
        else:
            print(f"      ⚠️ Grok API Error {response.status_code}: {response.text}")
            return None
    except Exception as e:
        print(f"      ⚠️ Grok Connection Error: {e}")
        return None

# ==========================================
# 🎨 IMAGE GENERATION VIA GROK
# ==========================================

def generate_image_grok(keyword, filename):
    """
    Meminta Grok untuk generate gambar berdasarkan keyword.
    Model Grok di Space ini mendukung image generation via prompt "Draw..."
    """
    output_path = f"{IMAGE_DIR}/{filename}"
    
    # Prompt khusus untuk image generation
    prompt = f"Draw a realistic, high-quality image of {keyword}. Ensure it looks like a professional sports photography shot. Cinematic lighting, 4k resolution."
    
    messages = [
        {"role": "user", "content": prompt}
    ]
    
    print(f"      🎨 Requesting Image from Grok: '{keyword}'...")
    
    # Kita coba pakai model yang mendukung image (biasanya model default atau grok-beta bisa trigger tool)
    # Jika API ini spesifik, mungkin perlu model 'grok-4.1' atau sejenisnya jika tersedia di space itu.
    # Kita pakai 'grok-beta' sebagai default aman.
    response = grok_chat_completion(messages, model="grok-beta")
    
    if response:
        try:
            # Mencari URL gambar dalam response. 
            # Biasanya Grok akan mengembalikan markdown image ![alt](url) atau langsung URL.
            content = response['choices'][0]['message']['content']
            
            # Regex untuk mencari URL gambar (http/https ... .png/jpg/webp atau format flux)
            # Pola ini mencoba menangkap URL yang mungkin ada di dalam teks
            url_pattern = r'(https?://[^\s)]+)'
            urls = re.findall(url_pattern, content)
            
            # Filter URL yang kemungkinan besar gambar
            valid_image_url = None
            for url in urls:
                # Cek ekstensi atau domain umum image host
                if any(ext in url.lower() for ext in ['.png', '.jpg', '.jpeg', '.webp', 'blob', 'generated']):
                    valid_image_url = url.strip(')') # Bersihkan trailing bracket markdown
                    break
            
            # Jika tidak ketemu ekstensi, ambil URL pertama saja (asumsi itu gambar dari tool)
            if not valid_image_url and urls:
                valid_image_url = urls[0].strip(')')

            if valid_image_url:
                print(f"      ⬇️ Downloading generated image: {valid_image_url[:30]}...")
                img_resp = requests.get(valid_image_url, timeout=20)
                if img_resp.status_code == 200:
                    img = Image.open(BytesIO(img_resp.content)).convert("RGB")
                    
                    # Resize/Optimize
                    img = img.resize((1200, 675), Image.Resampling.LANCZOS)
                    img.save(output_path, "WEBP", quality=85)
                    print("      ✅ Image Generated & Saved!")
                    return f"/images/{filename}"
            else:
                print("      ⚠️ No image URL found in Grok response.")
                
        except Exception as e:
            print(f"      ⚠️ Failed to process Grok image response: {e}")

    # Fallback ke Unsplash jika Grok gagal generate gambar
    print("      ⚠️ Grok Image Gen Failed. Using Fallback.")
    return "https://images.unsplash.com/photo-1522778119026-d647f0565c6a?auto=format&fit=crop&w=1200&q=80"


# ==========================================
# 📝 ARTICLE GENERATION VIA GROK
# ==========================================

def generate_article_grok(title, summary, link, author_name):
    current_date = datetime.now().strftime("%Y-%m-%d")
    
    system_prompt = f"""
    You are {author_name}, a professional sports journalist.
    CURRENT DATE: {current_date}.
    
    OBJECTIVE: Write a high-quality, 1000-word analysis article based on the provided news source.
    
    🛑 FORMATTING RULES:
    1. **MARKDOWN ONLY.** No HTML.
    2. Headers using hashtags (#).
    3. Tables using standard markdown if needed (e.g. for stats).
    4. NO Code Blocks.
    
    OUTPUT FORMAT:
    Return ONLY a valid JSON object with these keys: 
    "title", "description", "category", "main_keyword", "tags", "content_body".
    Ensure "content_body" contains the full markdown article.
    """
    
    user_prompt = f"""
    SOURCE NEWS:
    - Headline: {title}
    - Summary: {summary}
    - Link: {link}
    
    TASK: Write the article now in JSON format.
    """
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]
    
    print(f"      🤖 Grok Writing ({author_name})...")
    response = grok_chat_completion(messages, model="grok-beta")
    
    if response:
        try:
            content = response['choices'][0]['message']['content']
            # Bersihkan markdown code block jika ada (```json ... ```)
            content = clean_ai_content(content)
            # Cari JSON object start/end jika ada teks sampah di awal/akhir
            json_start = content.find('{')
            json_end = content.rfind('}') + 1
            if json_start != -1 and json_end != -1:
                json_str = content[json_start:json_end]
                return json_str
            return content # Coba return raw jika tidak ketemu pattern
        except Exception as e:
            print(f"      ⚠️ Parsing Grok Response Failed: {e}")
            return None
    return None

# ==========================================
# 🏁 MAIN WORKFLOW
# ==========================================
def main():
    os.makedirs(CONTENT_DIR, exist_ok=True)
    os.makedirs(IMAGE_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)

    print(f"🔥 ENGINE STARTED: GROK API ({GROK_API_BASE})")

    for source_name, rss_url in RSS_SOURCES.items():
        print(f"\n📡 Reading: {source_name}")
        feed = fetch_rss_feed(rss_url)
        if not feed: continue

        processed = 0
        for entry in feed.entries:
            if processed >= TARGET_PER_SOURCE: break
            
            clean_title = entry.title.split(" - ")[0]
            slug = slugify(clean_title, max_length=60, word_boundary=True)
            filename = f"{slug}.md"
            
            if os.path.exists(f"{CONTENT_DIR}/{filename}"): 
                continue
            
            print(f"   ⚡ Processing: {clean_title[:40]}...")
            
            # 1. Content Generation via Grok
            author = random.choice(AUTHOR_PROFILES)
            raw_json = generate_article_grok(clean_title, entry.summary, entry.link, author)
            
            if not raw_json: 
                print("      ❌ Failed to generate content.")
                continue
                
            try:
                data = json.loads(raw_json)
            except json.JSONDecodeError as e:
                print(f"      ❌ JSON Parse Error: {e}")
                # Optional: Log raw output untuk debug
                # print(raw_json[:100]) 
                continue

            # 2. Image Generation via Grok
            # Gunakan main_keyword dari hasil generate, atau title
            keyword = data.get('main_keyword') or clean_title
            final_img = generate_image_grok(keyword, f"{slug}.webp")
            
            # 3. Clean & Save
            clean_body = clean_ai_content(data['content_body'])
            links_md = get_internal_links_markdown()
            final_body = clean_body + "\n\n### Read More\n" + links_md
            
            # Validasi Kategori
            if data.get('category') not in VALID_CATEGORIES:
                data['category'] = "International"

            md_content = f"""---
title: "{data['title'].replace('"', "'")}"
date: {datetime.now().strftime("%Y-%m-%dT%H:%M:%S+00:00")}
author: "{author}"
categories: ["{data['category']}"]
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
*Reference: Analysis by {author} based on reports from [{source_name}]({entry.link}).*
"""
            with open(f"{CONTENT_DIR}/{filename}", "w", encoding="utf-8") as f:
                f.write(md_content)
            
            save_link_to_memory(data['title'], slug)
            
            # 4. Submit Indexing
            full_url = f"{WEBSITE_URL}/articles/{slug}/"
            submit_to_indexnow(full_url)
            submit_to_google(full_url)

            print(f"      ✅ Published: {slug}")
            processed += 1
            time.sleep(5)

if __name__ == "__main__":
    main()
