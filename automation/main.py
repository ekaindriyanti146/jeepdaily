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

# Endpoint Gateway Hugging Face (JANGAN DIGANTI)
GROK_API_URL = "https://velmamore-grok-api-free.hf.space/v1/chat/completions"
GROK_API_KEY = os.environ.get("GROK_API_KEY", "admin") 

WEBSITE_URL = "https://dother.biz.id" 
INDEXNOW_KEY = "e74819b68a0f40e98f6ec3dc24f610f0" 
GOOGLE_JSON_KEY = os.environ.get("GOOGLE_INDEXING_KEY", "") 

# TIM PENULIS (SPESIALIS JEEP)
AUTHOR_PROFILES = [
    "Rick 'Muddy' O'Connell (Off-road Expert)", 
    "Sarah Miller (Automotive Historian)",
    "Mike Stevens (Jeep Mechanic)", 
    "Tom Davidson (4x4 Reviewer)",
    "Elena Forza (Car Design Analyst)"
]

# RSS KHUSUS JEEP
RSS_SOURCES = {
    "Wrangler Life": "https://news.google.com/rss/search?q=Jeep+Wrangler+Review+News&hl=en-US&gl=US&ceid=US:en",
    "Off-road Tips": "https://news.google.com/rss/search?q=Offroad+4x4+Adventure+Tips&hl=en-US&gl=US&ceid=US:en",
    "Jeep Mods": "https://news.google.com/rss/search?q=Jeep+Wrangler+Modifications&hl=en-US&gl=US&ceid=US:en",
    "Classic Jeep": "https://news.google.com/rss/search?q=Classic+Jeep+History+Willys&hl=en-US&gl=US&ceid=US:en"
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

def get_internal_links_markdown():
    memory = load_link_memory()
    if not memory: return ""
    items = list(memory.items())
    selected = random.sample(items, min(len(items), 3))
    return "\n".join([f"- [{title}]({url})" for title, url in selected])

def get_random_user_agent():
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ]
    return random.choice(user_agents)

def fetch_rss_feed(url):
    headers = {'User-Agent': get_random_user_agent()}
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
# 🤖 GROK GATEWAY CLIENT (ANTI-BLOCK)
# ==========================================

def call_grok_gateway(messages, model="grok-4.1"):
    url = GROK_API_URL
    payload = {
        "model": model,
        "messages": messages,
        "stream": False
    }

    max_retries = 3
    for attempt in range(max_retries):
        headers = {
            "Authorization": f"Bearer {GROK_API_KEY}",
            "Content-Type": "application/json",
            "User-Agent": get_random_user_agent(),
            "Origin": "https://huggingface.co",
            "Referer": "https://huggingface.co/"
        }

        try:
            response = requests.post(url, headers=headers, json=payload, timeout=120)
            
            # Cek jika server HF sedang tidur/loading (biasanya return HTML)
            if 'text/html' in response.headers.get('Content-Type', ''):
                print("      ⚠️ Server is sleeping/building. Waiting 20s...")
                time.sleep(20)
                continue

            if response.status_code == 200:
                return response.json()
            elif response.status_code in [403, 429, 500, 503]:
                wait_time = (attempt + 1) * 20
                print(f"      ⚠️ API Error {response.status_code}. Waiting {wait_time}s...")
                time.sleep(wait_time)
                continue
            else:
                print(f"      ❌ API Error: {response.status_code}")
                return None
        except Exception as e:
            print(f"      ⚠️ Connection Error: {e}")
            time.sleep(10)
    
    return None

# ==========================================
# 🎨 IMAGE GENERATION (JEEP STYLE)
# ==========================================

def generate_image_grok(keyword, filename):
    output_path = f"{IMAGE_DIR}/{filename}"
    
    # PROMPT KHUSUS JEEP / GTA STYLE
    prompt = f"Draw a vector art illustration of {keyword}, jeep wrangler style, offroad action, gta loading screen vibe, vibrant colors, thick outlines, 4k resolution."
    
    print(f"      🎨 Requesting Image: {keyword}")
    
    # Gunakan grok-4.1 untuk trigger gambar
    response = call_grok_gateway([{"role": "user", "content": prompt}], model="grok-4.1")
    
    if response and 'choices' in response:
        content = response['choices'][0]['message']['content']
        urls = re.findall(r'(https?://[^\s)]+)', content)
        
        image_url = None
        for url in urls:
            clean_url = url.split(')')[0].strip('."')
            if any(x in clean_url for x in ['generated', 'blob', 'png', 'jpg', 'webp']):
                image_url = clean_url
                break
        
        if image_url:
            try:
                print(f"      ⬇️ Downloading Image...")
                img_resp = requests.get(image_url, headers={'User-Agent': get_random_user_agent()}, timeout=30)
                if img_resp.status_code == 200:
                    img = Image.open(BytesIO(img_resp.content)).convert("RGB")
                    
                    # Tambah Watermark
                    draw = ImageDraw.Draw(img)
                    try:
                        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 24)
                    except:
                        font = ImageFont.load_default()
                    draw.text((20, 20), "@JeepDaily", fill=(255, 255, 255), font=font)
                    
                    img.save(output_path, "WEBP", quality=90)
                    return f"/images/{filename}"
            except Exception as e:
                print(f"      ⚠️ Download Failed: {e}")

    # Fallback Unsplash (Kalau Grok gagal)
    print("      ⚠️ Grok Image Failed. Using Fallback.")
    return "https://images.unsplash.com/photo-1533473359331-0135ef1b58bf?auto=format&fit=crop&w=1200&q=80"

# ==========================================
# 📝 ARTICLE GENERATION (JEEP NICHE)
# ==========================================

def generate_article_grok(title, summary, link, author_name):
    current_date = datetime.now().strftime("%Y-%m-%d")
    
    system_prompt = f"""
    You are {author_name}, a Jeep Brand Specialist. Date: {current_date}.
    Write a 1000-word SEO article about Jeep/Offroad.
    
    RULES:
    1. Use Markdown (H2, H3, Tables).
    2. Tone: Enthusiastic, Technical, Adventurous.
    3. Include technical specs if relevant.
    4. NO HTML.
    
    OUTPUT JSON ONLY:
    {{
        "title": "SEO Title",
        "description": "Meta description",
        "category": "One of [Wrangler Life, Off-road Tips, Jeep Mods, Classic Jeep]",
        "main_keyword": "Keyword for image gen",
        "tags": ["tag1", "tag2"],
        "content_body": "Full markdown content..."
    }}
    """
    
    user_prompt = f"Topic: {title}\nContext: {summary}\nLink: {link}"
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]
    
    print(f"      🤖 Grok Writing Article...")
    # Gunakan grok-4-fast untuk artikel (lebih cepat & hemat)
    response = call_grok_gateway(messages, model="grok-4-fast")
    
    if response and 'choices' in response:
        content = response['choices'][0]['message']['content']
        content = clean_ai_content(content)
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

    print(f"🔥 JEEP ENGINE STARTED: HF GATEWAY MODE")
    
    # Ping Server
    try:
        requests.get("https://velmamore-grok-api-free.hf.space", timeout=5)
    except: pass

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
            
            # 1. GENERATE ARTIKEL
            author = random.choice(AUTHOR_PROFILES)
            raw_json = generate_article_grok(clean_title, entry.summary, entry.link, author)
            
            if not raw_json: 
                print("      ❌ Failed to get content. Skipping.")
                time.sleep(10)
                continue

            try:
                data = json.loads(raw_json)
            except:
                print("      ❌ JSON Parsing Error. Skipping.")
                continue

            # 2. GENERATE GAMBAR (JEEP STYLE)
            keyword = data.get('main_keyword') or clean_title
            final_img = generate_image_grok(keyword, f"{slug}.webp")
            
            # 3. SAVE MARKDOWN
            md_body = clean_ai_content(data['content_body'])
            cat = data.get('category', 'Wrangler Life')
            links_md = get_internal_links_markdown()
            
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

### Explore More
{links_md}
"""
            with open(f"{CONTENT_DIR}/{filename}", "w", encoding="utf-8") as f:
                f.write(md_content)
            
            save_link_to_memory(data['title'], slug)
            
            # 4. SUBMIT INDEXING
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
            
            # Cooling Down (Penting!)
            print("      💤 Cooling down (45s)...")
            time.sleep(45)

if __name__ == "__main__":
    main()
