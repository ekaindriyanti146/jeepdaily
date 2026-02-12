import os
import json
import requests
import feedparser
import time
import re
import random
import warnings
import string
from urllib.parse import quote
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
    print("⚠️ Google Indexing Libs not found.")

# ==========================================
# ⚙️ CONFIGURATION & SETUP
# ==========================================

# DAFTAR TOKEN SSO GROK (Ganti dengan token Anda)
GROK_SSO_TOKENS = [
    "MASUKKAN_TOKEN_SSO_1_DISINI",
    "MASUKKAN_TOKEN_SSO_2_DISINI"
]

WEBSITE_URL = "https://dother.biz.id" 
INDEXNOW_KEY = "e74819b68a0f40e98f6ec3dc24f610f0" 
GOOGLE_JSON_KEY = os.environ.get("GOOGLE_INDEXING_KEY", "") 

CONTENT_DIR = "content/articles" 
IMAGE_DIR = "static/images"
DATA_DIR = "automation/data"
MEMORY_FILE = f"{DATA_DIR}/link_memory.json"

# Niche RSS Sources (SEO Multi-Niche)
RSS_SOURCES = {
    "Wrangler Life": "https://news.google.com/rss/search?q=Jeep+Wrangler+Review+News&hl=en-US&gl=US&ceid=US:en",
    "Off-road Tips": "https://news.google.com/rss/search?q=Offroad+4x4+Adventure+Tips&hl=en-US&gl=US&ceid=US:en",
    "Jeep Mods": "https://news.google.com/rss/search?q=Jeep+Wrangler+Modifications&hl=en-US&gl=US&ceid=US:en",
    "Classic Jeep": "https://news.google.com/rss/search?q=Classic+Jeep+History+Willys&hl=en-US&gl=US&ceid=US:en"
}

# ==========================================
# 🔄 GROK SSO ENGINE (TOKEN ROTATOR)
# ==========================================

class GrokEngine:
    def __init__(self, tokens):
        self.tokens = [t.strip() for t in tokens if t.strip()]
        self.current_idx = 0
        if not self.tokens:
            raise Exception("❌ NO GROK SSO TOKENS FOUND!")

    def get_token(self):
        token = self.tokens[self.current_idx]
        self.current_idx = (self.current_idx + 1) % len(self.tokens)
        return token

    def call_grok(self, prompt, is_image=False):
        token = self.get_token()
        url = "https://grok.com/api/rpc/chat/completion"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Origin": "https://grok.com",
            "Referer": "https://grok.com/"
        }
        payload = {
            "modelName": "grok-latest",
            "message": prompt,
            "fileAttachments": [],
            "intent": "IMAGE_GEN" if is_image else "UNKNOWN"
        }

        try:
            response = requests.post(url, headers=headers, json=payload, stream=True, timeout=120)
            full_text = ""
            image_url = ""

            for line in response.iter_lines():
                if not line: continue
                try:
                    chunk = json.loads(line.decode('utf-8'))
                    res = chunk.get("result", {}).get("response", {})
                    if "token" in res:
                        full_text += res["token"]
                    if "attachments" in res:
                        for att in res["attachments"]:
                            if att.get("type") == "image":
                                image_url = att.get("url")
                except: continue
            return {"text": full_text, "image_url": image_url}
        except Exception as e:
            print(f"      ❌ Grok RPC Error: {e}")
            return None

grok = GrokEngine(GROK_SSO_TOKENS)

# ==========================================
# 🧠 SEO & ENTITY HELPERS
# ==========================================

def load_link_memory():
    if not os.path.exists(MEMORY_FILE): return {}
    try:
        with open(MEMORY_FILE, 'r') as f: return json.load(f)
    except: return {}

def save_link_to_memory(title, slug):
    os.makedirs(DATA_DIR, exist_ok=True)
    memory = load_link_memory()
    memory[title] = f"/{slug}/"
    if len(memory) > 300: memory = dict(list(memory.items())[-300:])
    with open(MEMORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(memory, f, indent=2)

def get_internal_links_html():
    memory = load_link_memory()
    if not memory: return ""
    items = list(memory.items())
    selected = random.sample(items, min(len(items), 3))
    links = "".join([f'<li><a href="{url}">{title}</a></li>' for title, url in selected])
    return f'<div class="related-posts"><h3>You Might Also Like</h3><ul>{links}</ul></div>'

# ==========================================
# 🚀 INDEXING LOGS
# ==========================================

def submit_to_indexnow(url):
    try:
        host = WEBSITE_URL.replace("https://", "").replace("http://", "")
        data = {"host": host, "key": INDEXNOW_KEY, "keyLocation": f"{WEBSITE_URL}/{INDEXNOW_KEY}.txt", "urlList": [url]}
        r = requests.post("https://api.indexnow.org/indexnow", json=data, timeout=10)
        print(f"      🚀 IndexNow Log: {url} -> {r.status_code}")
    except: pass

def submit_to_google(url):
    if not GOOGLE_JSON_KEY or not GOOGLE_LIBS_AVAILABLE: return
    try:
        creds_dict = json.loads(GOOGLE_JSON_KEY)
        credentials = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, ["https://www.googleapis.com/auth/indexing"])
        service = build("indexing", "v3", credentials=credentials)
        service.urlNotifications().publish(body={"url": url, "type": "URL_UPDATED"}).execute()
        print(f"      🚀 Google Index Log: {url} -> Success")
    except Exception as e:
        print(f"      ❌ Google Index Error: {e}")

# ==========================================
# 🎨 IMAGE ENGINE (GROK FLUX)
# ==========================================

def generate_grok_image(prompt, filename):
    print(f"      🎨 Grok is generating image...")
    # GTA / Vector Cartoon Style
    full_prompt = f"{prompt}, cartoon vector art, gta loading screen style, thick outlines, vibrant flat colors, cel shaded, no photorealism, 8k resolution"
    
    res = grok.call_grok(full_prompt, is_image=True)
    if res and res['image_url']:
        try:
            img_data = requests.get(res['image_url']).content
            img = Image.open(BytesIO(img_data)).convert("RGB")
            
            # Watermark
            draw = ImageDraw.Draw(img)
            text = "@JeepDaily"
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 28)
            except:
                font = ImageFont.load_default()
            
            draw.text((img.size[0]-200, 40), text, fill=(255, 255, 255), font=font)
            
            output_path = f"{IMAGE_DIR}/{filename}"
            img.save(output_path, "WEBP", quality=90)
            return f"/images/{filename}"
        except Exception as e:
            print(f"      ⚠️ Image Save Error: {e}")
    return ""

# ==========================================
# 📝 CONTENT ENGINE (ADSENSE READY)
# ==========================================

def generate_article(title, summary, link):
    author = random.choice(["Rick O'Connell", "Sarah Miller", "Mike Stevens", "Elena Forza"])
    
    prompt = f"""
    You are {author}, an Automotive Engineer and SEO Specialist.
    Write a 1200-word deep-dive article about: "{title}".
    Context: {summary}
    Source: {link}

    STRICT RULES:
    1. Structure: Use H2, H3, and H4 correctly for SEO hierarchy.
    2. Entities: Mention brands like Mopar, Dana Axles, Fox Shocks, or Pentastar engines where relevant.
    3. Technical Table: Include a Markdown table for specs or comparison.
    4. Pro-Tips: Add a 'Pro-Tip' callout box.
    5. External Link: Suggest 1 high-authority external URL (e.g. jeep.com).
    6. Schema: Provide a valid JSON-LD Article Schema.

    OUTPUT ONLY RAW JSON:
    {{
      "seo_title": "...",
      "meta_desc": "...",
      "category": "...",
      "tags": ["..."],
      "content_body": "...",
      "schema_json": {{ "@context": "https://schema.org", "@type": "Article", ... }},
      "image_prompt": "..."
    }}
    """
    
    print(f"      🤖 Grok is writing content...")
    res = grok.call_grok(prompt)
    if res and res['text']:
        try:
            clean_json = re.sub(r'```json|```', '', res['text']).strip()
            return json.loads(clean_json), author
        except: return None, None
    return None, None

# ==========================================
# 🏁 MAIN EXECUTION
# ==========================================

def main():
    os.makedirs(CONTENT_DIR, exist_ok=True)
    os.makedirs(IMAGE_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)

    print(f"🔥 JEEP ENGINE STARTED | TOKENS: {len(GROK_SSO_TOKENS)} 🔥")

    for cat_name, rss_url in RSS_SOURCES.items():
        print(f"\n📡 Reading Source: {cat_name}")
        feed = feedparser.parse(rss_url)
        
        if not feed.entries:
            print(f"      ⚠️ No news found for {cat_name}")
            continue

        # Ambil 1 berita terbaru per kategori
        for entry in feed.entries[:1]:
            clean_title = entry.title.split(" - ")[0]
            slug = slugify(clean_title, max_length=50)
            
            if os.path.exists(f"{CONTENT_DIR}/{slug}.md"):
                print(f"      ⏭️  Skipping: '{slug}' (Already exists)")
                continue

            print(f"      📝 Processing: {clean_title}")
            
            # 1. Generate Article
            data, author = generate_article(clean_title, entry.summary, entry.link)
            if not data:
                print("      ❌ Grok failed to return JSON.")
                continue

            # 2. Generate Image
            img_path = generate_grok_image(data.get('image_prompt', clean_title), f"{slug}.webp")

            # 3. Internal Links & Schema
            internal_md = get_internal_links_html()
            schema_tag = f'<script type="application/ld+json">\n{json.dumps(data.get("schema_json", {}))}\n</script>'

            # 4. Final Markdown Assembly
            final_md = f"""---
title: "{data.get('seo_title', clean_title).replace('"', "'")}"
date: {datetime.now().strftime("%Y-%m-%dT%H:%M:%S+00:00")}
author: "{author}"
categories: ["{data.get('category', cat_name)}"]
tags: {json.dumps(data.get('tags', []))}
featured_image: "{img_path}"
description: "{data.get('meta_desc', '').replace('"', "'")}"
slug: "{slug}"
url: "/{slug}/"
---

{schema_tag}

{data.get('content_body', '')}

<hr>

{internal_md}

---
*Reference Analysis: [{clean_title}]({entry.link})*
"""
            # Save File
            with open(f"{CONTENT_DIR}/{slug}.md", "w", encoding="utf-8") as f:
                f.write(final_md)
            
            save_link_to_memory(data.get('seo_title', clean_title), slug)

            # 5. INDEXING
            full_url = f"{WEBSITE_URL}/{slug}/"
            submit_to_indexnow(full_url)
            submit_to_google(full_url)

            print(f"      ✅ SUCCESSFULLY PUBLISHED: {slug}")
            
            # Jeda 30 detik agar aman dari rate limit
            time.sleep(30)

if __name__ == "__main__":
    main()
