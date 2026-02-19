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
# ⚙️ CONFIGURATION & SETUP (JEEP / OFF-ROAD NICHE)
# ==========================================

GROQ_KEYS_RAW = os.environ.get("GROQ_API_KEY", "") 
GROQ_API_KEYS = [k.strip() for k in GROQ_KEYS_RAW.split(",") if k.strip()]

WEBSITE_URL = "https://dother.biz.id" 
INDEXNOW_KEY = "e74819b68a0f40e98f6ec3dc24f610f0" 
GOOGLE_JSON_KEY = os.environ.get("GOOGLE_INDEXING_KEY", "")

if not GROQ_API_KEYS:
    print("❌ FATAL ERROR: Groq API Key is missing!")
    exit(1)

# --- NEW: AUTHOR DETAILS WITH SOCIALS (Fixes 'Author Info Missing') ---
AUTHOR_DETAILS = {
    "Rick 'Muddy' O'Connell": {
        "role": "Off-road Expert",
        "bio": "Rick has spent 20 years conquering the Rubicon Trail and modifying Wranglers.",
        "socials": ["https://twitter.com/jeep", "https://instagram.com/jeep"]
    },
    "Sarah Miller": {
        "role": "Automotive Historian",
        "bio": "Sarah specializes in the lineage of 4x4 vehicles, from Willys MB to the CJ era.",
        "socials": ["https://linkedin.com/in/jeep", "https://facebook.com/jeep"]
    },
    "Mike Stevens": {
        "role": "Jeep Mechanic",
        "bio": "Certified ASE Master Mechanic focusing on powertrain conversions and suspension geometry.",
        "socials": ["https://youtube.com/jeep", "https://twitter.com/mopar"]
    },
    "Tom Davidson": {
        "role": "4x4 Reviewer",
        "bio": "Tom tests the limits of stock and modified rigs in the harshest terrains of Moab.",
        "socials": ["https://instagram.com/offroad", "https://twitter.com/4x4"]
    }
}

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

# 🔥 TARGET: 1 Artikel per sumber per run
TARGET_PER_SOURCE = 1

# ==========================================
# 🧠 HELPER FUNCTIONS (ROBUST)
# ==========================================
def safe_request(url, retries=3):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    for i in range(retries):
        try:
            response = requests.get(url, headers=headers, timeout=20)
            if response.status_code == 200: return response
        except requests.RequestException: time.sleep(2)
    return None

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
    try:
        response = safe_request(url)
        return feedparser.parse(response.content) if response else None
    except: return None

def clean_ai_content(text):
    if not text: return ""
    text = re.sub(r'^```[a-zA-Z]*\n', '', text)
    text = re.sub(r'\n```$', '', text)
    text = text.replace("```", "")
    text = re.sub(r'^##\s*(Introduction|Conclusion|Summary|The Verdict|Final Thoughts|In Conclusion)\s*\n', '', text, flags=re.MULTILINE|re.IGNORECASE)
    text = re.sub(r'(?i)^##\s*Table of Contents.*?\n', '', text, flags=re.MULTILINE)
    
    text = text.replace("<h1>", "# ").replace("</h1>", "\n")
    text = text.replace("<h2>", "## ").replace("</h2>", "\n")
    text = text.replace("<h3>", "### ").replace("</h3>", "\n")
    text = text.replace("<h4>", "#### ").replace("</h4>", "\n")
    text = text.replace("<b>", "**").replace("</b>", "**")
    text = text.replace("<p>", "").replace("</p>", "\n\n")
    return text.strip()

def extract_json_from_text(text):
    try:
        start = text.find('{')
        end = text.rfind('}') + 1
        if start != -1 and end != -1:
            return json.loads(text[start:end])
        return None
    except: return None

def generate_toc(text):
    lines = text.split('\n')
    toc = ["\n## 📋 Table of Contents\n"]
    has_headers = False
    for line in lines:
        if line.startswith("## "):
            title = line.replace("## ", "").strip()
            anchor = slugify(title) 
            toc.append(f"- [{title}](#{anchor})")
            has_headers = True
        elif line.startswith("### "):
            title = line.replace("### ", "").strip()
            anchor = slugify(title)
            toc.append(f"  - [{title}](#{anchor})")
            has_headers = True
    return ("\n".join(toc) + "\n\n---\n\n") if has_headers else ""

def get_contextual_links(current_title):
    memory = load_link_memory()
    items = list(memory.items())
    if not items: return []
    stop_words = ['the', 'a', 'an', 'in', 'on', 'at', 'for', 'to', 'of', 'and', 'with', 'is', 'jeep', 'review', 'news'] 
    keywords = [w.lower() for w in current_title.split() if w.lower() not in stop_words and len(w) > 3]
    relevant_links = []
    for title, url in items:
        if sum(1 for k in keywords if k in title.lower()) > 0:
            relevant_links.append((title, url))
    return random.sample(relevant_links, min(3, len(relevant_links))) if relevant_links else random.sample(items, min(3, len(items)))

def inject_links_into_body(content_body, current_title):
    links = get_contextual_links(current_title)
    if not links: return content_body
    link_box = "\n\n> **🚙 Related Topics:**\n"
    for title, url in links:
        link_box += f"> - [{title}]({url})\n"
    link_box += "\n"
    paragraphs = content_body.split('\n\n')
    if len(paragraphs) < 5: return content_body + link_box
    insert_pos = max(2, int(len(paragraphs) / 3))
    paragraphs.insert(insert_pos, link_box)
    return "\n\n".join(paragraphs)

# --- NEW: SCHEMA & AUTHOR BOX GENERATOR (Fixes SEO Missing Fields) ---
def generate_author_box(author_name):
    details = AUTHOR_DETAILS.get(author_name, {
        "role": "Jeep Enthusiast", 
        "bio": "Passionate writer sharing insights on off-road culture.",
        "socials": []
    })
    
    social_md = " | ".join([f"[Link]({url})" for url in details['socials']])
    
    box = f"""
\n\n---
### 👤 About the Author: {author_name}
**{details['role']}**  
{details['bio']}  
*Follow on:* {social_md}
"""
    return box

def generate_schema_script(title, description, author, date_iso, img_url, slug):
    """Membuat JSON-LD untuk memuaskan Google Checker"""
    schema = {
        "@context": "https://schema.org",
        "@type": "BlogPosting",
        "headline": title,
        "description": description,
        "author": {
            "@type": "Person",
            "name": author
        },
        "datePublished": date_iso,
        "image": f"{WEBSITE_URL}{img_url}",
        "url": f"{WEBSITE_URL}/articles/{slug}/"
    }
    return f'\n<script type="application/ld+json">\n{json.dumps(schema, indent=2)}\n</script>\n'

# ==========================================
# 🚀 INDEXING
# ==========================================
def submit_to_indexnow(url):
    try:
        endpoint = "https://api.indexnow.org/indexnow"
        host = WEBSITE_URL.replace("https://", "").replace("http://", "")
        data = {"host": host, "key": INDEXNOW_KEY, "keyLocation": f"https://{host}/{INDEXNOW_KEY}.txt", "urlList": [url]}
        requests.post(endpoint, json=data, headers={'Content-Type': 'application/json'}, timeout=10)
        print(f"      🚀 IndexNow Submitted")
    except Exception as e: print(f"      ⚠️ IndexNow Failed: {e}")

def submit_to_google(url):
    if not GOOGLE_JSON_KEY or not GOOGLE_LIBS_AVAILABLE: return
    try:
        creds_dict = json.loads(GOOGLE_JSON_KEY)
        credentials = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, ["https://www.googleapis.com/auth/indexing"])
        service = build("indexing", "v3", credentials=credentials)
        service.urlNotifications().publish(body={"url": url, "type": "URL_UPDATED"}).execute()
        print(f"      🚀 Google Indexing Submitted")
    except Exception as e: print(f"      ⚠️ Google Indexing Error: {e}")

# ==========================================
# 🎨 IMAGE GENERATOR (ROBUST)
# ==========================================
def generate_robust_image(prompt, filename):
    output_path = f"{IMAGE_DIR}/{filename}"
    forbidden_words = ["sedan", "coupe", "bmw", "mercedes", "toyota", "low car"]
    clean_prompt = prompt.lower().replace('"', '').replace("'", "")[:200]
    for word in forbidden_words: clean_prompt = clean_prompt.replace(word, "")
    final_prompt = f"{clean_prompt}, Jeep Wrangler style, rugged off-road 4x4, cinematic lighting, realistic, 4k"
    
    print(f"      🎨 Generating Image: {clean_prompt[:30]}...")

    # 1. HERCAI (Prodia/v3)
    try:
        hercai_url = f"https://hercai.onrender.com/v3/text2image?prompt={requests.utils.quote(final_prompt)}"
        resp = requests.get(hercai_url, timeout=40)
        if resp.status_code == 200:
            data = resp.json()
            if "url" in data:
                img = Image.open(BytesIO(requests.get(data["url"], timeout=20).content)).convert("RGB")
                img.save(output_path, "WEBP", quality=85)
                print("      ✅ Image Saved (Source: Hercai AI)")
                return f"/images/{filename}"
    except: pass

    # 2. FLICKR FALLBACK
    try:
        tags = random.choice(["jeep wrangler", "jeep rubicon", "jeep offroad", "jeep gladiator"])
        flickr_url = f"https://loremflickr.com/1280/720/{tags.replace(' ', ',')}/all"
        resp = requests.get(flickr_url, timeout=20, allow_redirects=True)
        if resp.status_code == 200:
            Image.open(BytesIO(resp.content)).convert("RGB").save(output_path, "WEBP", quality=85)
            print("      ✅ Image Saved (Source: Real Photo Fallback)")
            return f"/images/{filename}"
    except: pass
    return "/images/default-jeep.webp"

# ==========================================
# 🚙 JEEP CONTENT ENGINE (LOGIC)
# ========================================== 
def get_groq_jeep_article_json(title, summary, link, author_name):
    current_date = datetime.now().strftime("%Y-%m-%d")
    structures = [
        "OFF_ROAD_PERFORMANCE_REVIEW (Cover: Trail Rated Badge, 4x4 Systems, Articulation, Suspension Tech, Real-world Trail Test)",
        "MODEL_EVOLUTION_HISTORY (Cover: Heritage/Legacy, Design Evolution from CJ/Wrangler, Engine Updates, Collector Value)",
        "TECHNICAL_SPEC_DEEP_DIVE (Cover: Powertrain Analysis, Aftermarket Potential, Axle/Gear Ratios, Towing Capacity, Competitor Comparison)"
    ]
    chosen_structure = random.choice(structures)
    categories_str = ", ".join(VALID_CATEGORIES)

    system_prompt = f"""
    You are {author_name}, a seasoned automotive journalist. Date: {current_date}.
    OBJECTIVE: Write a **DEEP DIVE (1500+ Words)** Jeep analysis.
    STRUCTURE: {chosen_structure}.
    
    🚫 NO DISCLAIMERS. NO "Introduction" headers.
    ✅ REQUIREMENTS:
    1. LENGTH: Minimum 1500 words. Force yourself to write 6+ long paragraphs per section.
    2. TABLE: Include a Markdown Table.
    3. HIERARCHY: Use ## and ### widely.
    4. FAQ: Add 3 technical questions.
    5. VISUAL KEYWORD: Describe a scene.
    
    OUTPUT JSON:
    {{
        "title": "Click-Worthy Headline",
        "description": "SEO Meta description (150 chars)",
        "category": "One of: {categories_str}",
        "main_keyword": "Visual prompt...",
        "tags": ["Jeep", "Wrangler", "Off-Road"],
        "content_body": "Full markdown content..."
    }}
    """
    user_prompt = f"Topic: {title}\nDetails: {summary}\nLink: {link}\nRespond ONLY in JSON."
    
    for api_key in GROQ_API_KEYS:
        client = Groq(api_key=api_key)
        try:
            print(f"      🚙 Jeep AI Writing ({chosen_structure.split()[0]} - Long Form)...")
            completion = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
                temperature=0.6, max_tokens=7500, response_format={"type": "json_object"}
            )
            return completion.choices[0].message.content
        except RateLimitError:
            print("      ⚠️ Rate Limit Hit, switching key...")
            time.sleep(2)
        except Exception as e: print(f"      ❌ Error: {e}")
    return None

# ==========================================
# 🏁 MAIN WORKFLOW
# ==========================================
def main():
    os.makedirs(CONTENT_DIR, exist_ok=True)
    os.makedirs(IMAGE_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)
    print("🔥 ENGINE STARTED: JEEP EDITION (PERFECT SCORE: TOC + AUTHOR BOX + SCHEMA)")

    for source_name, rss_url in RSS_SOURCES.items():
        print(f"\n📡 Reading: {source_name}")
        feed = fetch_rss_feed(rss_url)
        if not feed: continue
        processed_count = 0
        
        for entry in feed.entries:
            if processed_count >= TARGET_PER_SOURCE: break
            clean_title = entry.title.split(" - ")[0]
            slug = slugify(clean_title, max_length=60, word_boundary=True)
            filename = f"{slug}.md"
            if os.path.exists(f"{CONTENT_DIR}/{filename}"): continue
            
            print(f"   ⚡ Processing: {clean_title[:40]}...")
            author_name = random.choice(list(AUTHOR_DETAILS.keys())) # Pilih dari list detail
            
            raw_json_str = get_groq_jeep_article_json(clean_title, entry.summary, entry.link, author_name)
            if not raw_json_str: continue
            data = extract_json_from_text(raw_json_str)
            if not data: continue

            # 1. Assets & Content
            img_path = generate_robust_image(data.get('main_keyword', clean_title), f"{slug}.webp")
            clean_body = clean_ai_content(data['content_body'])
            toc_content = generate_toc(clean_body)
            body_with_toc = toc_content + clean_body
            final_body = inject_links_into_body(body_with_toc, data['title'])
            
            # 2. Add Author Box (Fixes "Author Info Missing")
            author_box = generate_author_box(author_name)
            final_body += author_box
            
            # 3. Add Visual Date (Fixes "Publish Date Missing" for visual check)
            pub_date_iso = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+00:00")
            pub_date_visual = datetime.now().strftime("%B %d, %Y")
            
            # 4. Generate Schema (Fixes "Schema" & "Date" for bots)
            schema_script = generate_schema_script(data['title'], data['description'], author_name, pub_date_iso, img_path, slug)
            
            # 5. Build Markdown
            cat = data.get('category', 'Jeep News')
            final_category = cat if cat in VALID_CATEGORIES else "Jeep News"
            
            md_content = f"""---
title: "{data['title'].replace('"', "'")}"
date: {pub_date_iso}
author: "{author_name}"
categories: ["{final_category}"]
tags: {json.dumps(data.get('tags', []))}
featured_image: "{img_path}"
description: "{data['description'].replace('"', "'")}"
slug: "{slug}"
url: "/{slug}/"
draft: false
weight: {random.randint(1, 10)}
---

**Published:** {pub_date_visual} | **By:** {author_name}

{final_body}

{schema_script}
---
*Reference: Analysis by {author_name} based on reports from [{source_name}]({entry.link}).*
"""
            try:
                with open(f"{CONTENT_DIR}/{filename}", "w", encoding="utf-8") as f: f.write(md_content)
                save_link_to_memory(data['title'], slug)
                full_url = f"{WEBSITE_URL}/articles/{slug}/"
                submit_to_indexnow(full_url)
                submit_to_google(full_url)
                print(f"      ✅ Published: {slug}")
                processed_count += 1
                time.sleep(60)
            except Exception as e: print(f"      ❌ File Write Error: {e}")

if __name__ == "__main__":
    main()
