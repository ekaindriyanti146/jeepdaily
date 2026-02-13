import os
import json
import requests
import feedparser
import time
import re
import random
import warnings 
from datetime import datetime
from slugify import slugify
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont

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
# ⚙️ KONFIGURASI ENDPOINT (STRICT)
# ==========================================

# Endpoint WAJIB (Sesuai instruksi Anda)
GROK_API_URL = "https://velmamore-grok-api-free.hf.space/v1/chat/completions"

# API Key (Default 'admin' sesuai dokumentasi jika belum diubah)
GROK_API_KEY = os.environ.get("GROK_API_KEY", "admin") 

# Konfigurasi Website
WEBSITE_URL = "https://dother.biz.id" 
INDEXNOW_KEY = "e74819b68a0f40e98f6ec3dc24f610f0" 
GOOGLE_JSON_KEY = os.environ.get("GOOGLE_INDEXING_KEY", "") 

# Folder Output
CONTENT_DIR = "content/articles" 
IMAGE_DIR = "static/images"
DATA_DIR = "automation/data"
MEMORY_FILE = f"{DATA_DIR}/link_memory.json"
TARGET_PER_SOURCE = 1 

# Profil Penulis
AUTHOR_PROFILES = [
    "Rick 'Muddy' O'Connell (Off-road Expert)", 
    "Sarah Miller (Automotive Historian)",
    "Mike Stevens (Jeep Mechanic)", 
    "Tom Davidson (4x4 Reviewer)"
]

# Sumber RSS (Jeep Niche)
RSS_SOURCES = {
    "Wrangler Life": "https://news.google.com/rss/search?q=Jeep+Wrangler+Review&hl=en-US&gl=US&ceid=US:en",
    "Offroad Tips": "https://news.google.com/rss/search?q=Offroad+4x4+Tips&hl=en-US&gl=US&ceid=US:en",
    "Jeep Mods": "https://news.google.com/rss/search?q=Jeep+Modifications&hl=en-US&gl=US&ceid=US:en"
}

# ==========================================
# 🔌 FUNGSI KONEKSI KE ENDPOINT (CORE)
# ==========================================

def get_random_header():
    """Mengacak User-Agent untuk menghindari blokir IP sederhana"""
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/119.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) Chrome/110.0.0.0 Safari/537.36"
    ]
    return {
        "Authorization": f"Bearer {GROK_API_KEY}",
        "Content-Type": "application/json",
        "User-Agent": random.choice(user_agents)
    }

def call_grok_endpoint(messages, model="grok-4.1"):
    """
    Fungsi tunggal untuk memanggil endpoint velmamore-grok-api-free.hf.space
    Digunakan untuk ARTIKEL dan GAMBAR.
    """
    payload = {
        "model": model, # grok-4.1 mendukung text & image generation
        "messages": messages,
        "stream": False
    }
    
    # Retry Logic jika server sibuk (429/503)
    for attempt in range(3):
        try:
            # Timeout panjang (120s) karena generate gambar/artikel butuh waktu
            response = requests.post(GROK_API_URL, headers=get_random_header(), json=payload, timeout=120)
            
            if response.status_code == 200:
                return response.json()
            elif response.status_code in [429, 500, 502, 503]:
                print(f"      ⚠️ Server Busy ({response.status_code}). Retrying in 10s...")
                time.sleep(10)
                continue
            elif response.status_code == 403:
                print("      ❌ Error 403: IP Blocked by Cloudflare/HuggingFace.")
                return None
            else:
                print(f"      ❌ API Error: {response.status_code} - {response.text[:100]}")
                return None
        except Exception as e:
            print(f"      ⚠️ Connection Error: {e}")
            time.sleep(5)
            
    return None

# ==========================================
# 🖼️ FUNGSI GENERATE IMAGE (VIA ENDPOINT)
# ==========================================

def generate_image_from_endpoint(keyword, filename):
    """
    Meminta endpoint Grok untuk menggambar ('Draw...')
    Response dari endpoint ini akan berisi URL gambar.
    """
    output_path = f"{IMAGE_DIR}/{filename}"
    
    # Instruksi spesifik untuk memicu fitur Image Gen di Grok
    prompt = f"Draw a high quality vector art illustration of {keyword}, Jeep Wrangler offroad style, vibrant colors, 4k resolution."
    
    print(f"      🎨 Requesting Image from Endpoint: '{keyword}'")
    
    messages = [{"role": "user", "content": prompt}]
    
    # Panggil Endpoint
    response = call_grok_endpoint(messages, model="grok-4.1")
    
    if response and 'choices' in response:
        content = response['choices'][0]['message']['content']
        
        # Endpoint Grok biasanya mengembalikan markdown image: ![image](https://...)
        # Kita ekstrak URL-nya menggunakan Regex
        urls = re.findall(r'(https?://[^\s)]+)', content)
        
        image_url = None
        # Cari URL yang valid (biasanya di domain hf.space atau sejenisnya)
        for url in urls:
            clean_url = url.split(')')[0].split('"')[0]
            # Validasi ekstensi gambar umum
            if any(ext in clean_url.lower() for ext in ['.png', '.jpg', '.jpeg', '.webp', 'generated']):
                image_url = clean_url
                break
        
        # Jika ketemu URL gambar dari response endpoint
        if image_url:
            try:
                print(f"      ⬇️ Downloading generated image...")
                img_resp = requests.get(image_url, timeout=30)
                if img_resp.status_code == 200:
                    img = Image.open(BytesIO(img_resp.content)).convert("RGB")
                    
                    # Tambah Watermark @JeepDaily
                    draw = ImageDraw.Draw(img)
                    try:
                        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 24)
                    except:
                        font = ImageFont.load_default()
                    draw.text((20, 20), "@JeepDaily", fill=(255, 255, 255), font=font)
                    
                    # Simpan
                    img.save(output_path, "WEBP", quality=90)
                    print("      ✅ Image Saved Successfully!")
                    return f"/images/{filename}"
            except Exception as e:
                print(f"      ❌ Failed to download image from endpoint: {e}")
        else:
            print("      ⚠️ Endpoint responded but no Image URL found in content.")
            # Debug: print konten jika gagal
            # print(f"DEBUG CONTENT: {content[:100]}...")
    else:
        print("      ❌ Failed to get response from Image Endpoint.")

    return "" # Return kosong jika gagal (sesuai instruksi tidak boleh pakai fallback lain)

# ==========================================
# 📝 FUNGSI GENERATE ARTIKEL (VIA ENDPOINT)
# ==========================================

def generate_article_from_endpoint(title, summary, link, author):
    current_date = datetime.now().strftime("%Y-%m-%d")
    
    system_prompt = f"""
    You are {author}, a Jeep Specialist. Date: {current_date}.
    Write a 1000-word SEO article using MARKDOWN.
    OUTPUT MUST BE A VALID JSON OBJECT ONLY.
    Structure: {{ "title": "...", "description": "...", "category": "...", "main_keyword": "...", "tags": [], "content_body": "..." }}
    """
    
    user_prompt = f"Topic: {title}\nSummary: {summary}\nLink: {link}"
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]
    
    print(f"      🤖 Requesting Article from Endpoint...")
    response = call_grok_endpoint(messages, model="grok-4.1")
    
    if response and 'choices' in response:
        content = response['choices'][0]['message']['content']
        
        # Bersihkan markdown code block ```json ... ```
        content = re.sub(r'^```[a-zA-Z]*\n', '', content)
        content = re.sub(r'\n```$', '', content).replace("```", "").strip()
        
        try:
            # Cari kurung kurawal JSON
            match = re.search(r'\{.*\}', content, re.DOTALL)
            if match:
                return json.loads(match.group(0))
            else:
                # Jika response bukan JSON murni, coba parse paksa
                return json.loads(content)
        except Exception as e:
            print(f"      ❌ JSON Parsing Failed: {e}")
            return None
            
    return None

# ==========================================
# 🧠 HELPER LAINNYA
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

def get_internal_links_markdown():
    memory = load_link_memory()
    if not memory: return ""
    items = list(memory.items())
    selected = random.sample(items, min(len(items), 3))
    return "\n".join([f"- [{title}]({url})" for title, url in selected])

def fetch_rss_feed(url):
    try:
        response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
        return feedparser.parse(response.content) if response.status_code == 200 else None
    except: return None

# ==========================================
# 🏁 MAIN PROGRAM
# ==========================================

def main():
    # Persiapan Folder
    os.makedirs(CONTENT_DIR, exist_ok=True)
    os.makedirs(IMAGE_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)

    print(f"🔥 ENGINE STARTED: STRICT ENDPOINT MODE ({GROK_API_URL}) 🔥")
    
    # Cek Koneksi Awal
    try:
        print("      🔍 Checking Endpoint Connection...")
        # Ping root domain untuk memastikan server hidup
        requests.get("https://velmamore-grok-api-free.hf.space", timeout=10)
        print("      ✅ Server is Reachable.")
    except Exception as e:
        print(f"      ⚠️ Server Warning: {e}")

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
            
            author = random.choice(AUTHOR_PROFILES)
            
            # 1. GENERATE ARTIKEL VIA ENDPOINT
            data = generate_article_from_endpoint(clean_title, entry.summary, entry.link, author)
            
            if not data:
                print("      ❌ Failed to generate article. Skipping.")
                time.sleep(5)
                continue

            # 2. GENERATE GAMBAR VIA ENDPOINT
            keyword = data.get('main_keyword') or clean_title
            final_img = generate_image_from_endpoint(keyword, f"{slug}.webp")
            
            if not final_img:
                print("      ⚠️ Image generation failed/empty from endpoint.")
                # Sesuai instruksi, jika gagal ya gagal (tidak ada fallback ke unsplash)
            
            # 3. SAVE FILE
            md_body = data.get('content_body', '')
            cat = data.get('category', 'Wrangler Life')
            links_md = get_internal_links_markdown()
            
            md_content = f"""---
title: "{data.get('title', clean_title).replace('"', "'")}"
date: {datetime.now().strftime("%Y-%m-%dT%H:%M:%S+00:00")}
author: "{author}"
categories: ["{cat}"]
tags: {json.dumps(data.get('tags', []))}
featured_image: "{final_img}"
description: "{data.get('description', '').replace('"', "'")}"
slug: "{slug}"
url: "/{slug}/"
---

{md_body}

### Explore More
{links_md}
"""
            with open(f"{CONTENT_DIR}/{filename}", "w", encoding="utf-8") as f:
                f.write(md_content)
            
            save_link_to_memory(data.get('title', clean_title), slug)
            
            # 4. INDEXING
            full_url = f"{WEBSITE_URL}/{slug}/"
            try:
                requests.post("https://api.indexnow.org/indexnow", json={
                    "host": WEBSITE_URL.replace("https://", ""),
                    "key": INDEXNOW_KEY,
                    "urlList": [full_url]
                }, timeout=5)
                print("      🚀 IndexNow Submitted")
            except: pass

            print(f"      ✅ Published: {slug}")
            processed += 1
            
            # Jeda untuk menghindari Rate Limit
            print("      💤 Cooling down (20s)...")
            time.sleep(20)

if __name__ == "__main__":
    main()
