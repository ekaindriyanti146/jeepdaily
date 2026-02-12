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
from PIL import Image, ImageEnhance, ImageOps, ImageFilter, ImageDraw
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

# TIM PENULIS (OTOMOTIF EXPERT)
AUTHOR_PROFILES = [
    "Rick 'Muddy' O'Connell (Off-road Expert)", 
    "Sarah Miller (Automotive Historian)",
    "Mike Stevens (Jeep Mechanic)", 
    "Tom Davidson (4x4 Reviewer)",
    "Elena Forza (Car Design Analyst)"
]

# KATEGORI JEEP (MICRO NICHE)
VALID_CATEGORIES = [
    "Wrangler Life", 
    "Classic Jeeps", 
    "Grand Cherokee", 
    "Gladiator Truck", 
    "Off-road Tips", 
    "Jeep History",
    "Maintenance & Mods"
]

# RSS SOURCES (GOOGLE NEWS QUERY SPESIFIK JEEP)
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
# 📸 UNSPLASH POOL (JEEP SPECIFIC - ENHANCED)
# ==========================================
UNSPLASH_POOL = {
    "wrangler": [
        "1519245659620-e859806a8d3b", "1533473359331-0135ef1bcfb0", "1506015391300-4802dc74de2e",
        "1568285201-168d6945821c", "1626243836043-34e85741f0b1", "1535446937720-e9cad5377719",
        "1547449547-410a768f5611", "1592965427211-1e9671d18f5a", "1517544845501-bb7810f66d8e",
        "1585848520031-72782e564d26", "1485463931481-863a35c6d36e", "1631553109355-1f8102d96924"
    ],
    "classic": [
        "1583262612502-869260a99672", "1552932906-e78964d4c207", "1603823483984-7a1926639d67",
        "1519575706483-221027bfbb31", "1559868840-7988566904f4", "1574045330831-50e561a3575c"
    ],
    "offroad": [
        "1495819903669-078927b80d5b", "1469130198188-466c9869852f", "1492144534655-ae79c964c9d7",
        "1500530855697-b586d89ba3ee", "1588632616462-974a3f123d46", "1446776811953-b23d57bd21aa",
        "1464822759023-fed622ff2c3b", "1530232464733-1466048d0870"
    ],
    "parts": [
        "1486262715619-0113e342bbef", "1487754180477-ea9d477cc6dc", "1498889444388-e67ea62c464b",
        "1581093110294-8255953049b1", "1611649931327-0b1348821901"
    ],
    "generic": [
        "1533473359331-0135ef1bcfb0", "1519245659620-e859806a8d3b", "1506015391300-4802dc74de2e",
        "1580273916550-e323be2ae537", "1542362567-b2bb40a59565"
    ]
}

FALLBACK_IMG_URL = "https://images.unsplash.com/photo-1533473359331-0135ef1bcfb0?auto=format&fit=crop&w=1200&q=80"

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
    if not text: return ""
    text = re.sub(r'^```[a-zA-Z]*\n', '', text)
    text = re.sub(r'\n```$', '', text)
    text = text.replace("```", "")
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
# 🎨 UNSPLASH ENGINE (PURE PILLOW UNIQUE)
# ==========================================

def modify_image_to_be_unique(img):
    """Memodifikasi gambar menggunakan PIL murni tanpa library luar."""
    
    # 1. Random Mirroring
    if random.random() > 0.5:
        img = ImageOps.mirror(img)
    
    # 2. Subtle Random Rotation & Auto Crop
    # Rotasi sangat kecil (0.5 - 2.0 derajat) merubah hash pixel secara masif
    angle = random.uniform(-2, 2)
    img = img.rotate(angle, resample=Image.BICUBIC, expand=False)
    
    # 3. Dynamic Random Crop Zoom (1200x675 Aspect Ratio)
    w, h = img.size
    crop_val = random.uniform(0.05, 0.10)
    left = w * crop_val
    top = h * crop_val
    right = w * (1 - crop_val)
    bottom = h * (1 - crop_val)
    img = img.crop((left, top, right, bottom))
    img = img.resize((1200, 675), Image.Resampling.LANCZOS)

    # 4. Color Grading (Randomized)
    img = ImageEnhance.Color(img).enhance(random.uniform(0.9, 1.2))
    img = ImageEnhance.Contrast(img).enhance(random.uniform(0.95, 1.1))
    img = ImageEnhance.Brightness(img).enhance(random.uniform(0.98, 1.05))
    
    # 5. Subtle Grain Effect (Menggunakan filter Sharpen halus sebagai pengganti noise)
    if random.random() > 0.5:
        img = img.filter(ImageFilter.SHARPEN)
    
    # 6. Professional Vignette
    # Membuat gradient hitam di pinggiran untuk fokus ke tengah
    vignette = Image.new('L', (1200, 675), 255)
    draw = ImageDraw.Draw(vignette)
    # Membuat oval besar
    draw.ellipse((-100, -100, 1300, 775), fill=0)
    vignette = vignette.filter(ImageFilter.GaussianBlur(120))
    
    # Gabungkan vignette ke gambar asli
    black_bg = Image.new("RGB", (1200, 675), (5, 5, 5))
    img = Image.composite(img, black_bg, ImageOps.invert(vignette))
    
    return img

def generate_unsplash_image(keyword, filename):
    output_path = f"{IMAGE_DIR}/{filename}"
    keyword = keyword.lower()
    
    # Logika pemilihan kategori gambar berdasarkan keyword
    selected_pool = UNSPLASH_POOL['generic'] 
    
    if any(x in keyword for x in ['wrangler', 'rubicon', 'sahara', 'jk', 'jl', '4xe']):
        selected_pool = UNSPLASH_POOL['wrangler']
    elif any(x in keyword for x in ['classic', 'willys', 'cj', 'history', 'vintage']):
        selected_pool = UNSPLASH_POOL['classic']
    elif any(x in keyword for x in ['offroad', 'trail', 'mud', 'rock', 'adventure']):
        selected_pool = UNSPLASH_POOL['offroad']
    elif any(x in keyword for x in ['engine', 'repair', 'mod', 'parts', 'interior', 'wheel']):
        selected_pool = UNSPLASH_POOL['parts']
    
    # Tambahkan elemen random pada seed agar hasil berbeda tiap pemanggilan
    random.seed(time.time() + random.random())
    
    attempts = 0
    while attempts < 5:
        selected_id = random.choice(selected_pool)
        # Menambahkan parameter unik pada URL agar tidak terkena cache CDN
        cache_buster = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
        unsplash_url = f"https://images.unsplash.com/photo-{selected_id}?auto=format&fit=crop&w=1250&q=85&cb={cache_buster}"
        
        print(f"      🎨 Downloading Jeep Image: {selected_id}")
        try:
            resp = requests.get(unsplash_url, timeout=15)
            if resp.status_code == 200:
                img = Image.open(BytesIO(resp.content)).convert("RGB")
                img = modify_image_to_be_unique(img)
                img.save(output_path, "WEBP", quality=85, method=6)
                print(f"      ✅ Unique Image Saved: {filename}")
                return f"/images/{filename}"
        except Exception as e:
            print(f"      ⚠️ Image Engine Error: {e}")
            
        attempts += 1
        time.sleep(1)

    return FALLBACK_IMG_URL

# ==========================================
# 🧠 JEEP CONTENT ENGINE (AUTOMOTIVE EXPERT)
# ==========================================

def get_groq_article_json(title, summary, link, author_name):
    current_date = datetime.now().strftime("%Y-%m-%d")
    
    system_prompt = f"""
    You are {author_name}, a passionate Automotive Expert specializing in the **Jeep** brand.
    CURRENT DATE: {current_date}.
    
    OBJECTIVE: Write a high-quality, 1000-word article about Jeeps/Off-road.
    
    🛑 STRICT CONTENT RULES:
    1. **MARKDOWN ONLY:** No HTML tags.
    2. **TONE:** Enthusiastic, technical but accessible, and authoritative.
    3. **ANTI-HOAX:** Be factual about engine specs (Pentastar V6, Hemi V8, 4xe), towing capacity, and model years.
    4. **NO GENERIC HEADERS:**
       - ❌ BAD: "Introduction", "Conclusion", "Features".
       - ✅ GOOD: "Why the Rubicon Dominates the Rocks", "The Pentastar V6 Reliability Verdict".
    
    STRUCTURE ADVICE:
    - **History/Context:** Mention model codes (CJ, YJ, TJ, JK, JL, JT) where relevant.
    - **Specs Table:** Use Markdown Table for HP, Torque, Ground Clearance if reviewing a car.
    - **Pros & Cons:** If it's a review.
    - **The Verdict:** Is it worth the money?

    OUTPUT FORMAT:
    JSON Object keys: "title", "description", "category", "main_keyword", "tags", "content_body".
    """
    
    user_prompt = f"""
    SOURCE INFO:
    - Topic: {title}
    - Snippet: {summary}
    - Link: {link}
    
    TASK: Write the article now using MARKDOWN. Focus on Jeep details.
    """
    
    for api_key in GROQ_API_KEYS:
        client = Groq(api_key=api_key)
        try:
            print(f"      🤖 AI Writing ({author_name})...")
            completion = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.6,
                max_tokens=8000,
                response_format={"type": "json_object"}
            )
            return completion.choices[0].message.content
        except RateLimitError: time.sleep(3)
        except Exception: pass
    return None

# ==========================================
# 🏁 MAIN WORKFLOW
# ==========================================
def main():
    os.makedirs(CONTENT_DIR, exist_ok=True)
    os.makedirs(IMAGE_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)

    print("🔥 JEEP MICRO NICHE ENGINE STARTED 🔥")

    for source_name, rss_url in RSS_SOURCES.items():
        print(f"\n📡 Reading: {source_name}")
        feed = fetch_rss_feed(rss_url)
        if not feed: continue

        processed = 0
        for entry in feed.entries:
            if processed >= TARGET_PER_SOURCE: break
            
            clean_title = entry.title.split(" - ")[0]
            if "jeep" not in clean_title.lower() and "4x4" not in clean_title.lower() and "off-road" not in clean_title.lower() and "wrangler" not in clean_title.lower():
               pass 

            slug = slugify(clean_title, max_length=60, word_boundary=True)
            filename = f"{slug}.md"
            
            if os.path.exists(f"{CONTENT_DIR}/{filename}"): 
                continue
            
            print(f"   ⚡ Processing: {clean_title[:40]}...")
            
            # 1. Content Generation
            author = random.choice(AUTHOR_PROFILES)
            raw_json = get_groq_article_json(clean_title, entry.summary, entry.link, author)
            
            if not raw_json: continue
            try:
                data = json.loads(raw_json)
            except:
                print("      ❌ JSON Parse Error")
                continue

            # 2. Image Generation (PURE PILLOW ENGINE)
            keyword = data.get('main_keyword') or clean_title
            final_img = generate_unsplash_image(keyword, f"{slug}.webp")
            
            # 3. Clean & Save
            clean_body = clean_ai_content(data['content_body'])
            links_md = get_internal_links_markdown()
            final_body = clean_body + "\n\n### Explore More\n" + links_md
            
            # Fallback Category Logic
            cat = data.get('category', "Jeep History")
            if cat not in VALID_CATEGORIES:
                cat = "Wrangler Life" # Default category
            
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
            
            # 4. Submit Indexing
            full_url = f"{WEBSITE_URL}/articles/{slug}/"
            submit_to_indexnow(full_url)
            submit_to_google(full_url)

            print(f"      ✅ Published: {slug}")
            processed += 1
            time.sleep(5)

if __name__ == "__main__":
    main()
