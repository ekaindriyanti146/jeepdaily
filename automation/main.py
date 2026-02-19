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
# ⚙️ CONFIGURATION
# ==========================================

GROQ_KEYS_RAW = os.environ.get("GROQ_API_KEY", "") 
GROQ_API_KEYS = [k.strip() for k in GROQ_KEYS_RAW.split(",") if k.strip()]

WEBSITE_URL = "https://dother.biz.id" 
INDEXNOW_KEY = "e74819b68a0f40e98f6ec3dc24f610f0" 
GOOGLE_JSON_KEY = os.environ.get("GOOGLE_INDEXING_KEY", "")

if not GROQ_API_KEYS:
    print("❌ FATAL ERROR: Groq API Key is missing!")
    exit(1)

# --- AUTHOR PROFILES (SEMANTIC DATA) ---
AUTHOR_DETAILS = {
    "Rick 'Muddy' O'Connell": {
        "role": "Off-road Specialist",
        "bio": "Rick has spent 20 years conquering the Rubicon Trail and modifying Wranglers for extreme conditions.",
        "socials": ["https://twitter.com/jeep", "https://instagram.com/jeep"]
    },
    "Sarah Miller": {
        "role": "Automotive Historian",
        "bio": "Sarah specializes in the lineage of 4x4 vehicles, documenting the evolution from Willys MB to the CJ and JL eras.",
        "socials": ["https://linkedin.com/in/jeep", "https://facebook.com/jeep"]
    },
    "Mike Stevens": {
        "role": "ASE Master Mechanic",
        "bio": "Certified mechanic focusing on powertrain conversions, suspension geometry, and diff re-gearing.",
        "socials": ["https://youtube.com/jeep", "https://twitter.com/mopar"]
    },
    "Tom Davidson": {
        "role": "4x4 Tech Reviewer",
        "bio": "Tom tests the limits of stock and modified rigs in the harshest terrains of Moab and the Rockies.",
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

TARGET_PER_SOURCE = 1

# ==========================================
# 🧠 HELPER FUNCTIONS (PARAGRAPH FIXER)
# ==========================================
def safe_request(url, retries=3):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
    for i in range(retries):
        try:
            response = requests.get(url, headers=headers, timeout=20)
            if response.status_code == 200: return response
        except: time.sleep(2)
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
    """
    FIX UTAMA: Memastikan paragraf terpisah dengan benar.
    """
    if not text: return ""
    
    # 1. Hapus artifact AI
    text = re.sub(r'^```[a-zA-Z]*\n', '', text)
    text = re.sub(r'\n```$', '', text)
    text = text.replace("```", "")
    text = re.sub(r'^##\s*(Introduction|Conclusion|Summary|The Verdict|Final Thoughts)\s*\n', '', text, flags=re.MULTILINE|re.IGNORECASE)
    text = re.sub(r'(?i)^##\s*Table of Contents.*?\n', '', text, flags=re.MULTILINE)

    # 2. Standardize Headers
    text = text.replace("<h1>", "# ").replace("</h1>", "\n")
    text = text.replace("<h2>", "## ").replace("</h2>", "\n")
    text = text.replace("<h3>", "### ").replace("</h3>", "\n")
    text = text.replace("<b>", "**").replace("</b>", "**")
    
    # 3. PARAGRAPH FIXER (CRITICAL FOR "LIMITED PARAGRAPHS" ERROR)
    # Jika AI memberikan paragraf tanpa double newline, Markdown akan menggabungkannya.
    # Kita paksa split jika paragraf terlalu panjang.
    
    # a. Pastikan setiap newline tunggal menjadi spasi (un-wrapping), kecuali headers/lists
    lines = text.split('\n')
    new_lines = []
    for line in lines:
        line = line.strip()
        if not line:
            new_lines.append("") # Keep empty lines
        elif line.startswith("#") or line.startswith("-") or line.startswith("*") or line.startswith(">"):
            new_lines.append(f"\n{line}\n") # Isolate headers/lists
        else:
            new_lines.append(line)
    
    # Gabungkan kembali
    text = "\n".join(new_lines)
    
    # b. Pastikan minimal ada double newline antar blok teks
    text = re.sub(r'\n\s*\n', '\n\n', text) 
    
    # c. Jika masih "Wall of Text" (blok > 500 karakter tanpa break), paksa split di titik
    final_chunks = []
    paragraphs = text.split('\n\n')
    for p in paragraphs:
        if len(p) > 600 and not p.startswith(('#', '-', '*', '>')):
            # Split paksa di titik kalimat
            p = p.replace(". ", ".\n\n") 
        final_chunks.append(p)
        
    return "\n\n".join(final_chunks).strip()

def extract_json_from_text(text):
    try:
        start = text.find('{')
        end = text.rfind('}') + 1
        if start != -1 and end != -1: return json.loads(text[start:end])
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
    stop_words = ['the', 'a', 'an', 'in', 'on', 'at', 'for', 'to', 'of', 'and', 'with', 'is', 'jeep'] 
    keywords = [w.lower() for w in current_title.split() if w.lower() not in stop_words and len(w) > 3]
    relevant_links = []
    for title, url in items:
        if sum(1 for k in keywords if k in title.lower()) > 0: relevant_links.append((title, url))
    return random.sample(relevant_links, min(3, len(relevant_links))) if relevant_links else random.sample(items, min(3, len(items)))

def inject_links_into_body(content_body, current_title):
    links = get_contextual_links(current_title)
    if not links: return content_body
    link_box = "\n\n> **🚙 Related Topics:**\n"
    for title, url in links: link_box += f"> - [{title}]({url})\n"
    link_box += "\n"
    paragraphs = content_body.split('\n\n')
    if len(paragraphs) < 5: return content_body + link_box
    insert_pos = max(2, int(len(paragraphs) / 3))
    paragraphs.insert(insert_pos, link_box)
    return "\n\n".join(paragraphs)

# --- AUTHOR & SCHEMA (SEMANTIC HTML) ---
def generate_author_box(author_name):
    details = AUTHOR_DETAILS.get(author_name, {"role": "Jeep Enthusiast", "bio": "Writer.", "socials": []})
    social_md = " | ".join([f"[Link]({url})" for url in details['socials']])
    # Gunakan HTML Semantic <address> dan <div> agar terdeteksi checker
    box = f"""
\n\n---
<div class="author-box" style="background: #f4f4f4; padding: 20px; border-left: 5px solid #333; margin-top: 30px;">
    <h3 style="margin-top:0;">👤 About the Author</h3>
    <address style="font-style: normal;">
        <strong><span itemprop="author" itemscope itemtype="http://schema.org/Person"><span itemprop="name">{author_name}</span></span></strong><br>
        <em>{details['role']}</em><br>
        {details['bio']}
    </address>
    <p style="margin-bottom:0; font-size:0.9em;">Follow on: {social_md}</p>
</div>
"""
    return box

def generate_schema_script(title, description, author, date_iso, img_url, slug):
    schema = {
        "@context": "https://schema.org",
        "@type": "BlogPosting",
        "headline": title,
        "description": description,
        "author": {"@type": "Person", "name": author},
        "datePublished": date_iso,
        "dateModified": date_iso,
        "image": f"{WEBSITE_URL}{img_url}",
        "url": f"{WEBSITE_URL}/articles/{slug}/",
        "publisher": {"@type": "Organization", "name": "Jeep Life", "logo": {"@type": "ImageObject", "url": f"{WEBSITE_URL}/logo.png"}}
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
    except: pass

def submit_to_google(url):
    if not GOOGLE_JSON_KEY or not GOOGLE_LIBS_AVAILABLE: return
    try:
        creds_dict = json.loads(GOOGLE_JSON_KEY)
        credentials = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, ["https://www.googleapis.com/auth/indexing"])
        service = build("indexing", "v3", credentials=credentials)
        service.urlNotifications().publish(body={"url": url, "type": "URL_UPDATED"}).execute()
        print(f"      🚀 Google Indexing Submitted")
    except: pass

# ==========================================
# 🎨 IMAGE GENERATOR
# ==========================================
def generate_robust_image(prompt, filename):
    output_path = f"{IMAGE_DIR}/{filename}"
    forbidden = ["sedan", "coupe", "bmw", "mercedes", "toyota", "low car"]
    clean = prompt.lower().replace('"', '').replace("'", "")[:200]
    for w in forbidden: clean = clean.replace(w, "")
    final_prompt = f"{clean}, Jeep Wrangler style, rugged off-road 4x4, cinematic lighting, realistic, 4k"
    
    print(f"      🎨 Generating Image: {clean[:30]}...")

    try:
        url = f"https://hercai.onrender.com/v3/text2image?prompt={requests.utils.quote(final_prompt)}"
        resp = requests.get(url, timeout=40)
        if resp.status_code == 200:
            data = resp.json()
            if "url" in data:
                img = Image.open(BytesIO(requests.get(data["url"], timeout=20).content)).convert("RGB")
                img.save(output_path, "WEBP", quality=85)
                return f"/images/{filename}"
    except: pass

    try:
        tags = random.choice(["jeep wrangler", "jeep rubicon", "jeep offroad"])
        url = f"https://loremflickr.com/1280/720/{tags.replace(' ', ',')}/all"
        resp = requests.get(url, timeout=20, allow_redirects=True)
        if resp.status_code == 200:
            Image.open(BytesIO(resp.content)).convert("RGB").save(output_path, "WEBP", quality=85)
            return f"/images/{filename}"
    except: pass
    return "/images/default-jeep.webp"

# ==========================================
# 🚙 JEEP CONTENT ENGINE (FORCE LENGTH & STRUCTURE)
# ========================================== 
def get_groq_jeep_article_json(title, summary, link, author_name):
    current_date = datetime.now().strftime("%Y-%m-%d")
    structures = [
        "OFF_ROAD_PERFORMANCE_REVIEW",
        "MODEL_EVOLUTION_HISTORY",
        "TECHNICAL_SPEC_DEEP_DIVE"
    ]
    chosen_structure = random.choice(structures)
    categories_str = ", ".join(VALID_CATEGORIES)

    # PROMPT BARU: Memaksa struktur bagian demi bagian agar panjang
    system_prompt = f"""
    You are {author_name}, a senior automotive journalist.
    Date: {current_date}.
    
    TASK: Write a **COMPREHENSIVE (1500+ Words)** article.
    STYLE: {chosen_structure}.
    
    ⚠️ CRITICAL RULES (VIOLATION = FAIL):
    1. **NO WALL OF TEXT**: You MUST use double newlines between paragraphs.
    2. **LENGTH**: Do not summarize. Expand every point.
    3. **STRUCTURE**:
       - Start with a Hook (200 words).
       - Section 1: History/Context (300 words).
       - Section 2: Technical Details/Engine/Suspension (400 words).
       - Section 3: Real World Performance (300 words).
       - Section 4: Comparison/Verdict (300 words).
    
    ✅ MANDATORY ELEMENTS:
    - Detailed Markdown Table.
    - 3-4 FAQ Questions at the end.
    
    OUTPUT JSON:
    {{
        "title": "Headline",
        "description": "Meta description",
        "category": "One of: {categories_str}",
        "main_keyword": "Image prompt",
        "tags": ["tag1", "tag2"],
        "content_body": "Full markdown..."
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
                temperature=0.7, max_tokens=7500, response_format={"type": "json_object"}
            )
            return completion.choices[0].message.content
        except RateLimitError:
            time.sleep(2)
        except Exception as e: print(f"      ❌ Error: {e}")
    return None

# ==========================================
# 🏁 MAIN
# ==========================================
def main():
    os.makedirs(CONTENT_DIR, exist_ok=True)
    os.makedirs(IMAGE_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)
    print("🔥 ENGINE STARTED: JEEP EDITION (FIXED: PARAGRAPHS + AUTHOR VISIBILITY)")

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
            author_name = random.choice(list(AUTHOR_DETAILS.keys()))
            
            raw_json_str = get_groq_jeep_article_json(clean_title, entry.summary, entry.link, author_name)
            if not raw_json_str: continue
            data = extract_json_from_text(raw_json_str)
            if not data: continue

            # 1. Assets & Content
            img_path = generate_robust_image(data.get('main_keyword', clean_title), f"{slug}.webp")
            
            # CLEANING & FIXING PARAGRAPHS
            clean_body = clean_ai_content(data['content_body']) 
            
            toc_content = generate_toc(clean_body)
            body_with_toc = toc_content + clean_body
            final_body = inject_links_into_body(body_with_toc, data['title'])
            
            # 2. Add VISUAL Author Box (HTML Semantic)
            author_box = generate_author_box(author_name)
            final_body += author_box
            
            # 3. Add VISUAL Date (HTML Semantic)
            pub_date_iso = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+00:00")
            pub_date_visual = datetime.now().strftime("%B %d, %Y")
            date_html = f'<p class="meta-date" style="color:#666; font-size:0.9em; margin-bottom:20px;">📅 <time datetime="{pub_date_iso}" itemprop="datePublished">{pub_date_visual}</time></p>'
            
            # 4. Generate Schema
            schema_script = generate_schema_script(data['title'], data['description'], author_name, pub_date_iso, img_path, slug)
            
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

{date_html}

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
