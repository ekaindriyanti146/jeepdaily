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

# ==========================================
# ⚙️ CONFIGURATION & SETUP (VESLIFE / JEEP NICHE)
# ==========================================

GROQ_KEYS_RAW = os.environ.get("GROQ_API_KEY", "") 
GROQ_API_KEYS = [k.strip() for k in GROQ_KEYS_RAW.split(",") if k.strip()]

WEBSITE_URL = "https://dother.biz.id" 
INDEXNOW_KEY = "e74819b68a0f40e98f6ec3dc24f610f0" 
GOOGLE_JSON_KEY = os.environ.get("GOOGLE_INDEXING_KEY", "")

if not GROQ_API_KEYS:
    # Fallback manual jika env variable kosong saat testing
    # GROQ_API_KEYS = ["gsk_..."] 
    print("❌ FATAL ERROR: Groq API Key is missing!")
    exit(1)

# Penulis dengan Otoritas (E-E-A-T)
AUTHOR_PROFILES = [
    "Rick 'Muddy' O'Connell (Off-road Expert)", 
    "Sarah Miller (Automotive Historian)",
    "Mike Stevens (Jeep Mechanic)", 
    "Tom Davidson (4x4 Reviewer)",
    "Elena Forza (Car Design Analyst)"
]

# Kategori Global (Disamakan agar AI dan Code sinkron)
VALID_CATEGORIES = [
    "Wrangler Life", "Classic Jeeps", "Grand Cherokee", 
    "Gladiator Truck", "Off-road Tips", "Jeep History", "Maintenance & Mods", "Jeep News"
]

RSS_SOURCES = {
    "Autoblog Jeep": "https://www.autoblog.com/category/jeep/rss.xml",
    "Motor1 Jeep": "https://www.motor1.com/rss/make/jeep/",
    "Mopar Insiders": "https://moparinsiders.com/feed/", 
    "Jeep News": "https://www.autoevolution.com/rss/cars/jeep/",
    "Jeep Wrangler News": "https://news.google.com/rss/search?q=Jeep+Wrangler+Review+OR+News&hl=en-US&gl=US&ceid=US:en",
    "Jeep Gladiator": "https://news.google.com/rss/search?q=Jeep+Gladiator+News&hl=en-US&gl=US&ceid=US:en",
    "Classic Jeep History": "https://news.google.com/rss/search?q=Classic+Jeep+Willys+History&hl=en-US&gl=US&ceid=US:en",
    "Offroad Lifestyle": "https://news.google.com/rss/search?q=Offroad+4x4+Adventure&hl=en-US&gl=US&ceid=US:en"
}

CONTENT_DIR = "content/articles" 
IMAGE_DIR = "static/images"
DATA_DIR = "automation/data"
MEMORY_FILE = f"{DATA_DIR}/link_memory.json"

# 🔥 TARGET: 2 Artikel per sumber per run
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
    if len(memory) > 500: memory = dict(list(memory.items())[-500:])
    with open(MEMORY_FILE, 'w') as f: json.dump(memory, f, indent=2)

def fetch_rss_feed(url):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    try:
        response = requests.get(url, headers=headers, timeout=15)
        return feedparser.parse(response.content) if response.status_code == 200 else None
    except: return None

def clean_ai_content(text):
    if not text: return ""
    text = re.sub(r'^```[a-zA-Z]*\n', '', text)
    text = re.sub(r'\n```$', '', text)
    text = text.replace("```", "")
    text = re.sub(r'^##\s*(Introduction|Conclusion|Summary|The Verdict|Final Thoughts|In Conclusion)\s*\n', '', text, flags=re.MULTILINE|re.IGNORECASE)
    
    text = text.replace("<h1>", "# ").replace("</h1>", "\n")
    text = text.replace("<h2>", "## ").replace("</h2>", "\n")
    text = text.replace("<h3>", "### ").replace("</h3>", "\n")
    text = text.replace("<h4>", "#### ").replace("</h4>", "\n")
    text = text.replace("<b>", "**").replace("</b>", "**")
    text = text.replace("<p>", "").replace("</p>", "\n\n")
    return text.strip()

def extract_json_from_text(text):
    """Helper untuk mengekstrak JSON valid dari output AI yang kotor"""
    try:
        # Cari kurung kurawal pertama dan terakhir
        start = text.find('{')
        end = text.rfind('}') + 1
        if start != -1 and end != -1:
            json_str = text[start:end]
            return json.loads(json_str)
        return None
    except:
        return None

# ==========================================
# 🧠 SMART SILO LINKING (AUTHORITY BOOSTER)
# ==========================================
def get_contextual_links(current_title):
    memory = load_link_memory()
    items = list(memory.items())
    if not items: return []
    
    stop_words = ['the', 'a', 'an', 'in', 'on', 'at', 'for', 'to', 'of', 'and', 'with', 'is', 'jeep', 'review', 'news'] 
    keywords = [w.lower() for w in current_title.split() if w.lower() not in stop_words and len(w) > 3]
    
    relevant_links = []
    
    for title, url in items:
        title_lower = title.lower()
        match_score = sum(1 for k in keywords if k in title_lower)
        if match_score > 0:
            relevant_links.append((title, url))
    
    if relevant_links:
        count = min(3, len(relevant_links))
        return random.sample(relevant_links, count)
    
    count = min(3, len(items))
    return random.sample(items, count)

def inject_links_into_body(content_body, current_title):
    links = get_contextual_links(current_title)
    if not links: return content_body

    link_box = "\n\n> **🚙 Related Topics:**\n"
    for title, url in links:
        link_box += f"> - [{title}]({url})\n"
    link_box += "\n"

    paragraphs = content_body.split('\n\n')
    if len(paragraphs) < 4: return content_body + link_box
    insert_pos = random.randint(1, 2) 
    paragraphs.insert(insert_pos, link_box)
    return "\n\n".join(paragraphs)

# ==========================================
# 🚀 INDEXING FUNCTIONS
# ==========================================
def submit_to_indexnow(url):
    try:
        endpoint = "https://api.indexnow.org/indexnow"
        host = WEBSITE_URL.replace("https://", "").replace("http://", "")
        data = {
            "host": host, "key": INDEXNOW_KEY,
            "keyLocation": f"https://{host}/{INDEXNOW_KEY}.txt",
            "urlList": [url]
        }
        requests.post(endpoint, json=data, headers={'Content-Type': 'application/json; charset=utf-8'}, timeout=10)
        print(f"      🚀 IndexNow Submitted")
    except Exception as e: print(f"      ⚠️ IndexNow Failed: {e}")

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
    except Exception as e: print(f"      ⚠️ Google Indexing Error: {e}")

# ==========================================
# 🎨 IMAGE GENERATOR (FORCE JEEP STYLE)
# ==========================================
def generate_robust_image(prompt, filename):
    output_path = f"{IMAGE_DIR}/{filename}"
    forbidden_words = ["sedan", "coupe", "bmw", "mercedes", "toyota", "low car", "sports car", "track car"]
    clean_prompt = prompt.lower().replace('"', '').replace("'", "")
    for word in forbidden_words:
        clean_prompt = clean_prompt.replace(word, "")
    
    forced_style = "Jeep Wrangler style SUV, rugged 4x4, boxy off-road vehicle, seven slot grille, lifted suspension, big tires, cinematic automotive photography, realistic 8k, hdr"
    final_prompt = f"{clean_prompt}, {forced_style}"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://google.com"
    }

    print(f"      🎨 Generating Image: {clean_prompt[:30]}...")

    # 1. POLLINATIONS (Priority)
    try:
        seed = random.randint(1, 99999)
        poly_url = f"https://image.pollinations.ai/prompt/{requests.utils.quote(final_prompt)}?width=1280&height=720&model=flux&seed={seed}&nologo=true"
        resp = requests.get(poly_url, headers=headers, timeout=25)
        if resp.status_code == 200:
            img = Image.open(BytesIO(resp.content)).convert("RGB")
            img.save(output_path, "WEBP", quality=85)
            print("      ✅ Image Saved (Source: Pollinations Flux)")
            return f"/images/{filename}"
    except Exception: pass

    # 2. HERCAI (Fallback)
    try:
        hercai_url = f"https://hercai.onrender.com/v3/text2image?prompt={requests.utils.quote(final_prompt)}"
        resp = requests.get(hercai_url, headers=headers, timeout=40)
        if resp.status_code == 200:
            data = resp.json()
            if "url" in data:
                img_data = requests.get(data["url"], headers=headers, timeout=20).content
                img = Image.open(BytesIO(img_data)).convert("RGB")
                img.save(output_path, "WEBP", quality=85)
                print("      ✅ Image Saved (Source: Hercai AI)")
                return f"/images/{filename}"
    except Exception: pass

    # 3. FLICKR (Final Safety)
    try:
        # Menggunakan tag random jeep untuk variasi
        tags = random.choice(["jeep wrangler", "jeep rubicon", "jeep gladiator", "offroad 4x4"])
        flickr_url = f"https://loremflickr.com/1280/720/{tags.replace(' ', ',')}/all"
        resp = requests.get(flickr_url, headers=headers, timeout=20, allow_redirects=True)
        if resp.status_code == 200:
            img = Image.open(BytesIO(resp.content)).convert("RGB")
            img.save(output_path, "WEBP", quality=85)
            print("      ✅ Image Saved (Source: Real Photo Fallback)")
            return f"/images/{filename}"
    except Exception: pass

    return "/images/default-jeep.webp"

# ==========================================
# 🚙 JEEP CONTENT ENGINE (1500 WORDS + NO AI DISCLAIMER)
# ========================================== 

def get_groq_jeep_article_json(title, summary, link, author_name):
    current_date = datetime.now().strftime("%Y-%m-%d")
    
    structures = [
        "OFF_ROAD_PERFORMANCE_REVIEW (Cover: Trail Rated Badge, 4x4 Systems, Articulation, Suspension Tech, Real-world Trail Test)",
        "MODEL_EVOLUTION_HISTORY (Cover: Heritage/Legacy, Design Evolution from CJ/Wrangler, Engine Updates, Collector Value)",
        "TECHNICAL_SPEC_DEEP_DIVE (Cover: Powertrain Analysis, Aftermarket Potential, Axle/Gear Ratios, Towing Capacity, Competitor Comparison)"
    ]
    chosen_structure = random.choice(structures)

    # Menggunakan List Global agar sinkron
    categories_str = ", ".join(VALID_CATEGORIES)

    system_prompt = f"""
    You are {author_name}, a seasoned automotive journalist and Jeep specialist with decades of off-road experience.
    Current Date: {current_date}.
    
    OBJECTIVE: Write a **DEEP DIVE, LONG-FORM (1500+ Words)** automotive analysis about Jeep.
    TARGET AUDIENCE: Jeep Enthusiasts, Off-roaders, Car Buyers, and Mechanics.
    STRUCTURE STYLE: {chosen_structure}.
    
    🚫 NEGATIVE CONSTRAINTS (CRITICAL):
    1. **NO DISCLAIMERS**: DO NOT write a disclaimer at the end.
    2. **NO GENERIC HEADERS**: Do NOT use "Introduction", "Conclusion", "Summary". Start straight with the engine roar.
    3. **NO FLUFF**: Do not repeat the same point. Expand by adding historical context, mechanical details, or modification advice.
    
    ✅ MANDATORY REQUIREMENTS:
    1. **LENGTH**: The article MUST be comprehensive (aim for 1200-1500 words). Use multiple sub-sections.
    2. **DATA TABLE**: You MUST include a detailed Markdown Table (e.g., **Technical Specs: HP, Torque, Ground Clearance, Approach/Departure Angles**).
    3. **HIERARCHY**: Use H2 (##) for major sections, H3 (###) for technical breakdown, and H4 (####) for specific parts.
    4. **FAQ**: Add a "Frequently Asked Questions" section at the very end with 3 technical questions (e.g., about death wobble, lockers, or lift kits).
    5. **VISUAL KEYWORD**: Describe a specific dramatic scene of the Jeep for the image generator (e.g., rock crawling in Moab).
    
    OUTPUT FORMAT (JSON):
    {{
        "title": "Rugged, Click-Worthy Automotive Headline",
        "description": "SEO Meta description (150 chars) focusing on specs/performance",
        "category": "One of: {categories_str}",
        "main_keyword": "Visual prompt description...",
        "tags": ["Jeep", "Wrangler", "Off-Road", "4x4", "specific_model"],
        "content_body": "The full long-form markdown content..."
    }}
    """
    
    user_prompt = f"""
    SOURCE MATERIAL:
    - Topic/Vehicle: {title}
    - Key Details: {summary}
    - Reference Link: {link}
    
    Write the 1500-word Jeep analysis now. Respond ONLY in valid JSON.
    """
    
    for api_key in GROQ_API_KEYS:
        client = Groq(api_key=api_key)
        try:
            print(f"      🚙 Jeep AI Writing ({chosen_structure.split()[0]} - Long Form)...")
            completion = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.6,
                max_tokens=7500,
                response_format={"type": "json_object"}
            )
            return completion.choices[0].message.content
        except RateLimitError:
            print("      ⚠️ Rate Limit Hit, switching key...")
            time.sleep(2)
        except Exception as e:
            print(f"      ❌ Error: {e}")
            pass
    return None

# ==========================================
# 🏁 MAIN WORKFLOW
# ==========================================
def main():
    os.makedirs(CONTENT_DIR, exist_ok=True)
    os.makedirs(IMAGE_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)

    print("🔥 ENGINE STARTED: VESLIFE JEEP EDITION (SILO + IMAGE FIX)")

    for source_name, rss_url in RSS_SOURCES.items():
        print(f"\n📡 Reading: {source_name}")
        feed = fetch_rss_feed(rss_url)
        if not feed: continue

        processed_count = 0
        
        for entry in feed.entries:
            if processed_count >= TARGET_PER_SOURCE:
                print(f"   🛑 Target reached for {source_name}")
                break
            
            clean_title = entry.title.split(" - ")[0]
            slug = slugify(clean_title, max_length=60, word_boundary=True)
            filename = f"{slug}.md"
            
            if os.path.exists(f"{CONTENT_DIR}/{filename}"): 
                continue
            
            print(f"   ⚡ Processing: {clean_title[:40]}...")
            
            author = random.choice(AUTHOR_PROFILES)
            
            # --- FIX: Menggunakan nama fungsi yang BENAR ---
            raw_json_str = get_groq_jeep_article_json(clean_title, entry.summary, entry.link, author)
            
            if not raw_json_str: continue
            
            # --- FIX: Ekstraksi JSON yang lebih aman ---
            data = extract_json_from_text(raw_json_str)
            if not data:
                print("      ❌ JSON Parse Error / Invalid Output")
                continue

            # 1. Generate Image (With Force-Filter)
            image_prompt = data.get('main_keyword', clean_title)
            final_img_path = generate_robust_image(image_prompt, f"{slug}.webp")
            
            # 2. Clean Content
            clean_body = clean_ai_content(data['content_body'])
            
            # 3. Inject Contextual Links (Siloing)
            final_body_with_links = inject_links_into_body(clean_body, data['title'])
            
            # 4. Fallback Category Checking
            cat = data.get('category', 'Jeep News')
            # Jika kategori dari AI tidak ada di list valid, paksa jadi Jeep News
            final_category = cat if cat in VALID_CATEGORIES else "Jeep News"

            # 5. Create Markdown File
            md_content = f"""---
title: "{data['title'].replace('"', "'")}"
date: {datetime.now().strftime("%Y-%m-%dT%H:%M:%S+00:00")}
author: "{author}"
categories: ["{final_category}"]
tags: {json.dumps(data.get('tags', []))}
featured_image: "{final_img_path}"
description: "{data['description'].replace('"', "'")}"
slug: "{slug}"
url: "/{slug}/"
draft: false
weight: {random.randint(1, 10)}
---

{final_body_with_links}

---
*Reference: Analysis by {author} based on reports from [{source_name}]({entry.link}).*
"""
            try:
                with open(f"{CONTENT_DIR}/{filename}", "w", encoding="utf-8") as f:
                    f.write(md_content)
                
                # 6. Save & Index
                save_link_to_memory(data['title'], slug)
                
                full_url = f"{WEBSITE_URL}/articles/{slug}/"
                submit_to_indexnow(full_url)
                submit_to_google(full_url)

                print(f"      ✅ Published: {slug}")
                processed_count += 1
                
                print("      💤 Sleeping for 120s (Natural Drip Feed)...")
                time.sleep(120)
            except Exception as e:
                print(f"      ❌ File Write Error: {e}")

if __name__ == "__main__":
    main()
