import os
import json
import requests
import feedparser
import time
import re
import random
import warnings
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

# ==========================================
# ⚙️ CONFIGURATION & ENV VARIABLES
# ==========================================

GROK_KEYS_RAW = os.environ.get("GROK_SSO_TOKENS", "") 
GROK_SSO_TOKENS = [k.strip() for k in GROK_KEYS_RAW.split(",") if k.strip()]

WEBSITE_URL = "https://dother.biz.id" 
INDEXNOW_KEY = "e74819b68a0f40e98f6ec3dc24f610f0" 
GOOGLE_JSON_KEY = os.environ.get("GOOGLE_INDEXING_KEY", "") 

CONTENT_DIR = "content/articles" 
IMAGE_DIR = "static/images"
DATA_DIR = "automation/data"
MEMORY_FILE = f"{DATA_DIR}/link_memory.json"

RSS_SOURCES = {
    "Wrangler Life": "https://news.google.com/rss/search?q=Jeep+Wrangler+Review+News&hl=en-US&gl=US&ceid=US:en",
    "Off-road Tips": "https://news.google.com/rss/search?q=Offroad+4x4+Adventure+Tips&hl=en-US&gl=US&ceid=US:en",
    "Jeep Mods": "https://news.google.com/rss/search?q=Jeep+Wrangler+Modifications&hl=en-US&gl=US&ceid=US:en",
    "Classic Jeep": "https://news.google.com/rss/search?q=Classic+Jeep+History+Willys&hl=en-US&gl=US&ceid=US:en"
}

# ==========================================
# 🔄 GROK SSO ENGINE (ROBUST VERSION)
# ==========================================

class GrokEngine:
    def __init__(self, tokens):
        self.tokens = tokens
        self.current_idx = 0
        if not self.tokens:
            print("❌ FATAL ERROR: No GROK_SSO_TOKENS found!")
            exit(1)

    def get_token(self):
        token = self.tokens[self.current_idx]
        self.current_idx = (self.current_idx + 1) % len(self.tokens)
        return token

    def call_rpc(self, prompt, is_image=False):
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
            # GUNAKAN STREAM=FALSE untuk mendapatkan data utuh agar tidak terpotong
            response = requests.post(url, headers=headers, json=payload, timeout=180)
            
            if response.status_code != 200:
                print(f"      ❌ Grok API Error {response.status_code}: {response.text[:200]}")
                return None

            full_text = ""
            image_url = ""

            # Grok RPC mengembalikan NDJSON (Multiple JSON lines)
            for line in response.text.splitlines():
                if not line.strip(): continue
                try:
                    chunk = json.loads(line)
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
            print(f"      ❌ Connection Error: {e}")
            return None

grok = GrokEngine(GROK_SSO_TOKENS)

# ==========================================
# 🧠 UTILS & SEO HELPERS
# ==========================================

def extract_json_from_text(text):
    try:
        # Mencari pola JSON terluar { ... }
        match = re.search(r'(\{.*\})', text, re.DOTALL)
        if match:
            return json.loads(match.group(1))
    except Exception as e:
        print(f"      ⚠️ JSON Parsing Error: {e}")
    return None

def save_link_to_memory(title, slug):
    os.makedirs(DATA_DIR, exist_ok=True)
    mem = {}
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, 'r', encoding='utf-8') as f: mem = json.load(f)
        except: mem = {}
    mem[title] = f"/{slug}/"
    with open(MEMORY_FILE, 'w', encoding='utf-8') as f: json.dump(mem, f, indent=2)

def get_internal_links():
    if not os.path.exists(MEMORY_FILE): return ""
    try:
        with open(MEMORY_FILE, 'r', encoding='utf-8') as f:
            mem = json.load(f)
            if not mem: return ""
            items = list(mem.items())
            selected = random.sample(items, min(len(items), 3))
            links = "".join([f'<li><a href="{u}">{t}</a></li>' for t, u in selected])
            return f'<div class="related-posts"><h3>Related Jeep News</h3><ul>{links}</ul></div>'
    except: return ""

# ==========================================
# 🚀 INDEXING LOGS (PASTI MUNCUL)
# ==========================================

def submit_indexing(slug):
    full_url = f"{WEBSITE_URL}/{slug}/"
    print(f"      📡 SUBMITTING INDEXING: {full_url}")
    
    # 1. IndexNow
    try:
        host = WEBSITE_URL.replace("https://", "").replace("http://", "")
        data = {"host": host, "key": INDEXNOW_KEY, "keyLocation": f"{WEBSITE_URL}/{INDEXNOW_KEY}.txt", "urlList": [full_url]}
        resp = requests.post("https://api.indexnow.org/indexnow", json=data, timeout=15)
        print(f"      🚀 IndexNow Log: Success ({resp.status_code})")
    except Exception as e:
        print(f"      ❌ IndexNow Log Error: {e}")

    # 2. Google Indexing API
    if GOOGLE_JSON_KEY and GOOGLE_LIBS_AVAILABLE:
        try:
            creds_dict = json.loads(GOOGLE_JSON_KEY)
            credentials = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, ["https://www.googleapis.com/auth/indexing"])
            service = build("indexing", "v3", credentials=credentials)
            service.urlNotifications().publish(body={"url": full_url, "type": "URL_UPDATED"}).execute()
            print(f"      🚀 Google Index Log: Success")
        except Exception as e:
            print(f"      ❌ Google Index Log Error: {e}")
    else:
        print(f"      ⚠️ Google Index Log: Skipped (Key/Libs Missing)")

# ==========================================
# 🎨 IMAGE GENERATOR
# ==========================================

def generate_image(prompt, filename):
    print(f"      🎨 IMAGE GENERATION START: {filename}")
    styled_prompt = f"{prompt}, cartoon vector art, gta loading screen style, thick outlines, flat vibrant colors"
    res = grok.call_rpc(styled_prompt, is_image=True)
    
    if res and res['image_url']:
        try:
            img_data = requests.get(res['image_url']).content
            img = Image.open(BytesIO(img_data)).convert("RGB")
            draw = ImageDraw.Draw(img)
            draw.text((10, 10), "@JeepDaily", fill=(255, 255, 255))
            output_path = f"{IMAGE_DIR}/{filename}"
            img.save(output_path, "WEBP", quality=90)
            print(f"      ✅ IMAGE SAVED: {output_path}")
            return f"/images/{filename}"
        except Exception as e:
            print(f"      ❌ Image Save Error: {e}")
    else:
        print(f"      ❌ Image Generation Failed: Grok returned no URL.")
    return ""

# ==========================================
# 🏁 MAIN WORKFLOW
# ==========================================

def main():
    for d in [CONTENT_DIR, IMAGE_DIR, DATA_DIR]: os.makedirs(d, exist_ok=True)
    print(f"🔥 JEEP ENGINE STARTED | TOKENS: {len(GROK_SSO_TOKENS)} 🔥")

    for cat, rss_url in RSS_SOURCES.items():
        print(f"\n📡 Source Category: {cat}")
        feed = feedparser.parse(rss_url)
        if not feed.entries: continue

        for entry in feed.entries[:1]:
            clean_title = entry.title.split(" - ")[0]
            slug = slugify(clean_title, max_length=50)
            file_path = f"{CONTENT_DIR}/{slug}.md"

            if os.path.exists(file_path):
                print(f"      ⏭️ Skipping: {slug} (Already exists)")
                continue

            print(f"      📝 Processing Article: {clean_title}")
            
            # 1. GENERATE DATA
            prompt = f"Write a 1000-word SEO article in JSON format about: {clean_title}. Context: {entry.summary}. Source: {entry.link}. JSON keys must be: seo_title, meta_desc, content_markdown, schema_json, image_prompt."
            res = grok.call_rpc(prompt)
            
            if not res or not res['text']:
                print(f"      ❌ ERROR: Grok returned empty text for article. Skipping...")
                continue

            data = extract_json_from_text(res['text'])
            if not data:
                print(f"      ❌ ERROR: Could not parse JSON from Grok. Skipping...")
                continue

            # 2. GENERATE IMAGE
            image_url = generate_image(data.get('image_prompt', clean_title), f"{slug}.webp")

            # 3. INTERNAL LINKS & SCHEMA
            internal_links = get_internal_links()
            schema_tag = f'<script type="application/ld+json">\n{json.dumps(data.get("schema_json", {}))}\n</script>'

            # 4. ASSEMBLY & SAVE
            md_content = f"""---
title: "{data.get('seo_title', clean_title).replace('"', "'")}"
date: {datetime.now().strftime("%Y-%m-%dT%H:%M:%S+00:00")}
author: "Rick O'Connell"
categories: ["{cat}"]
featured_image: "{image_url}"
description: "{data.get('meta_desc', '').replace('"', "'")}"
slug: "{slug}"
url: "/{slug}/"
---

{schema_tag}

{data.get('content_markdown', 'Content generation error.')}

<hr>
{internal_links}

---
*Reference: Analysis by Rick O'Connell based on [{clean_title}]({entry.link}).*
"""
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(md_content)
            
            save_link_to_memory(data.get('seo_title', clean_title), slug)
            
            # 5. SUBMIT INDEXING
            submit_indexing(slug)

            print(f"      ✅ SUCCESSFULLY COMPLETED: {slug}")
            time.sleep(15)

if __name__ == "__main__":
    main()
