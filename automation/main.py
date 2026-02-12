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
    print("⚠️ Google Indexing Libs not found (Optional).")

# ==========================================
# ⚙️ CONFIGURATION & SETUP
# ==========================================

# Masukkan API Key Groq Anda di sini (pisahkan koma jika banyak)
GROQ_KEYS_RAW = os.environ.get("GROQ_API_KEY", "gsk_...") 
GROQ_API_KEYS = [k.strip() for k in GROQ_KEYS_RAW.split(",") if k.strip()]

# Konfigurasi Website
WEBSITE_URL = "https://dother.biz.id" 
INDEXNOW_KEY = "e74819b68a0f40e98f6ec3dc24f610f0" 
GOOGLE_JSON_KEY = os.environ.get("GOOGLE_INDEXING_KEY", "") 

# Cek API Key
if not GROQ_API_KEYS or "gsk_" not in GROQ_API_KEYS[0]:
    print("❌ PERINGATAN: GROQ_API_KEY belum diset dengan benar!")
    # exit(1) # Uncomment jika ingin script mati saat tidak ada key

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
    "Jeep Concepts": "https://news.google.com/rss/search?q=Jeep+Concept+Cars+Electric&hl=en-US&gl=US&ceid=US:en",
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
# 🎨 SMART IMAGE ENGINE (SEARCH & REMIX)
# ==========================================

def get_random_header():
    # User agent acak agar tidak diblokir Unsplash saat searching
    uas = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36"
    ]
    return {'User-Agent': random.choice(uas)}

def process_and_save_image(img_obj, save_path):
    """
    Fungsi ini mengubah visual gambar agar unik:
    1. Mirroring (Flip)
    2. Rotation (Miring sedikit)
    3. Color Grading (Filter warna)
    4. Watermark
    """
    try:
        img = img_obj.convert('RGB')
        
        # 1. Random Mirror (50% Chance)
        if random.random() > 0.5:
            img = ImageOps.mirror(img)
            
        # 2. Slight Rotation & Crop (Agar hash file berubah)
        angle = random.uniform(-1.5, 1.5)
        img = img.rotate(angle, resample=Image.BICUBIC, expand=False)
        
        # Crop sisa hitam akibat rotasi (Zoom in 3%)
        w, h = img.size
        crop_val = 0.03
        img = img.crop((w*crop_val, h*crop_val, w*(1-crop_val), h*(1-crop_val)))
        img = img.resize((1200, 675), Image.Resampling.LANCZOS) # Resize ke standar Web

        # 3. Cinematic Color Filter (Random Mood)
        mood = random.choice(['warm', 'cool', 'contrast', 'dark'])
        
        if mood == 'warm': # Filter Sore/Gurun
            overlay = Image.new('RGB', img.size, (255, 180, 100))
            img = Image.blend(img, overlay, 0.1)
        elif mood == 'cool': # Filter Pagi/Gunung
            overlay = Image.new('RGB', img.size, (100, 180, 255))
            img = Image.blend(img, overlay, 0.1)
        elif mood == 'contrast': # Filter High Contrast
            img = ImageEnhance.Contrast(img).enhance(1.15)
            img = ImageEnhance.Color(img).enhance(1.1)

        # 4. Watermark (@JeepDaily)
        draw = ImageDraw.Draw(img)
        text = "@JeepDaily"
        
        # Load Font Default
        try:
            # Coba cari font Arial/DejaVu
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 20)
        except:
            font = ImageFont.load_default()
            
        # Posisi text (Kanan Atas)
        text_w = 120 # estimasi lebar
        x = 1200 - text_w - 40
        y = 40
        
        # Shadow Text (Hitam)
        draw.text((x+2, y+2), text, fill=(0, 0, 0, 160), font=font)
        # Main Text (Putih)
        draw.text((x, y), text, fill=(255, 255, 255, 200), font=font)
        
        # Simpan
        img.save(save_path, "WEBP", quality=85)
        return True
    except Exception as e:
        print(f"      ⚠️ Image Processing Error: {e}")
        return False

def scrape_unsplash_by_keyword(keyword, filename):
    """
    Mencari gambar di Unsplash berdasarkan keyword, mengambil daftar hasil,
    lalu memilih SATU secara ACAK.
    """
    if not os.path.exists(IMAGE_DIR): os.makedirs(IMAGE_DIR, exist_ok=True)
    output_path = f"{IMAGE_DIR}/{filename}"
    
    # Bersihkan keyword & tambah variasi agar hasil search tidak monoton
    base_keyword = keyword.lower().replace(" ", "-")
    variations = ["offroad", "adventure", "trail", "forest", "mud", "4x4"]
    search_term = f"{base_keyword}-{random.choice(variations)}"
    
    # URL Search Unsplash
    url = f"https://unsplash.com/s/photos/{search_term}"
    print(f"      🔍 Searching Image: {search_term}...")

    try:
        # Request halaman pencarian
        resp = requests.get(url, headers=get_random_header(), timeout=15)
        
        if resp.status_code == 200:
            # Regex untuk mengambil ID gambar dari HTML (pola: photo-ID)
            # Ini mengambil semua ID gambar yang muncul di hasil pencarian
            found_ids = re.findall(r'https://images\.unsplash\.com/photo-([a-zA-Z0-9-]+)\?', resp.text)
            
            # Hapus duplikat ID
            unique_ids = list(set(found_ids))
            
            if len(unique_ids) > 0:
                # --- LOGIKA ANTI DUPLIKAT ---
                # Pilih 1 ID secara acak dari sekian banyak hasil
                selected_id = random.choice(unique_ids)
                
                print(f"      📸 Found {len(unique_ids)} candidates. Selected ID: {selected_id}")
                
                # Download gambar resolusi HD (w=1200)
                dl_url = f"https://images.unsplash.com/photo-{selected_id}?auto=format&fit=crop&w=1200&q=80"
                img_data = requests.get(dl_url, headers=get_random_header(), timeout=20)
                
                if img_data.status_code == 200:
                    img = Image.open(BytesIO(img_data.content))
                    
                    # Proses visual (flip/color/watermark)
                    if process_and_save_image(img, output_path):
                        return f"/images/{filename}"
            
            else:
                print("      ⚠️ No images found in search results.")
        else:
            print(f"      ⚠️ Search failed. Status: {resp.status_code}")
            
    except Exception as e:
        print(f"      ❌ Image Engine Exception: {e}")

    # --- FALLBACK (Jika Search Gagal Total) ---
    # Gunakan gambar default Jeep tapi tetap di-remix visualnya
    print("      ⚠️ Using Fallback Image...")
    try:
        fb_url = "https://images.unsplash.com/photo-1533473359331-0135ef1b58bf?auto=format&fit=crop&w=1200&q=80"
        img = Image.open(BytesIO(requests.get(fb_url).content))
        process_and_save_image(img, output_path)
        return f"/images/{filename}"
    except:
        return ""

# ==========================================
# 🧠 CONTENT ENGINE (AI WRITER)
# ==========================================

def get_groq_article_json(title, summary, link, author_name):
    current_date = datetime.now().strftime("%Y-%m-%d")
    
    # Prompt yang sangat spesifik untuk Jeep
    system_prompt = f"""
    You are {author_name}, a Jeep Brand Specialist.
    TASK: Write a 1000-word authoritative article about Jeep.
    
    🛑 HARD NEGATIVE CONSTRAINTS (FORBIDDEN):
    - DO NOT use the word "Introduction".
    - DO NOT use the word "Understanding".
    - DO NOT use the word "Conclusion".
    - DO NOT use the word "Overview".
    - DO NOT use the word "Limitations".
    
    ✅ POSITIVE CONSTRAINTS:
    - Headers (H2, H3) MUST be creative and specific to Jeep (e.g., "The Wrangler's 4:1 Transfer Case Explained").
    - Use technical codes like CJ, YJ, TJ, JK, JL, JT where appropriate.
    - Include engine specs (HP, Torque) in a Markdown table if talking about models.
    - "main_keyword" MUST be a short search term for an image (e.g. "jeep wrangler rubicon", "jeep gladiator mud").
    
    Output JSON with: title, description, category, main_keyword, tags, content_body.
    """
    user_prompt = f"Topic: {title}\nSummary: {summary}\nLink: {link}"
    
    for api_key in GROQ_API_KEYS:
        client = Groq(api_key=api_key)
        try:
            print(f"      🤖 AI Writing ({author_name})...")
            completion = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
                temperature=0.6,
                max_tokens=6000,
                response_format={"type": "json_object"}
            )
            return completion.choices[0].message.content
        except Exception as e:
            print(f"      ⚠️ AI Error: {e}")
            continue
    return None

# ==========================================
# 🏁 MAIN WORKFLOW
# ==========================================
def main():
    # Buat direktori jika belum ada
    os.makedirs(CONTENT_DIR, exist_ok=True)
    os.makedirs(IMAGE_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)

    print("🔥 JEEP ENGINE STARTED (SEARCH & SCRAPE MODE) 🔥")

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
            
            # Cek apakah artikel sudah ada
            if os.path.exists(f"{CONTENT_DIR}/{filename}"): continue
            
            author = random.choice(AUTHOR_PROFILES)
            
            # 1. Generate Konten
            raw_json = get_groq_article_json(clean_title, entry.summary, entry.link, author)
            if not raw_json: continue
            
            try:
                data = json.loads(raw_json)
                
                # 2. Generate Image (SEARCH METHOD)
                # Ambil keyword dari AI, atau gunakan judul jika AI tidak memberi keyword
                keyword_for_image = data.get('main_keyword', clean_title)
                final_img = scrape_unsplash_by_keyword(keyword_for_image, f"{slug}.webp")
                
                # 3. Format Konten
                clean_body = clean_ai_content(data['content_body'])
                links_md = get_internal_links_markdown()
                final_body = clean_body + "\n\n### Explore More\n" + links_md
                
                cat = data.get('category', "Wrangler Life")
                if cat not in VALID_CATEGORIES: cat = "Wrangler Life"
                
                # 4. Buat File Markdown
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
                
                # 5. Simpan Memory & Indexing
                save_link_to_memory(data['title'], slug)
                
                full_url = f"{WEBSITE_URL}/{slug}/"
                submit_to_indexnow(full_url)
                submit_to_google(full_url)

                print(f"      ✅ Successfully Published: {slug}")
                processed += 1
                
                # Jeda 5 detik agar tidak kena rate limit
                time.sleep(5)
                
            except Exception as e:
                print(f"      ❌ Critical Error processing article: {e}")

if __name__ == "__main__":
    main()
