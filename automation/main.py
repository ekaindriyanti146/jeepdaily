import os
import json
import requests
import feedparser
import time
import re
import random
import warnings
import sys
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
# 🔄 GROK SSO ENGINE (DENGAN LOG STATUS HTTP)
# ==========================================

class GrokEngine:
    def __init__(self, tokens):
        self.tokens = tokens
        self.current_idx = 0
        if not self.tokens:
            print("❌ ERROR: No GROK_SSO_TOKENS found!", flush=True)
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
            response = requests.post(url, headers=headers, json=payload, stream=True, timeout=180)
            
            # LOG STATUS UNTUK DEBUG
            if response.status_code != 200:
                print(f"      ⚠️ Grok HTTP Error: {response.status_code}", flush=True)
                return None

            full_text = ""
            image_url = ""

            for line in response.iter_lines():
                if not line: continue
                line_text = line.decode('utf-8')
                if line_text.startswith("data: "):
                    line_text = line_text[6:]
                try:
                    chunk = json.loads(line_text)
                    res = chunk.get("result", {}).get("response", {})
                    if "token" in res:
                        full_text += res["token"]
                    if "attachments" in res:
                        for att in res["attachments"]:
                            if att.get("type") == "image":
                                image_url = att.get("url")
                except:
                    continue
            return {"text": full_text, "image_url": image_url}
        except Exception as e:
            print(f"      ❌ Grok Connection Error: {e}", flush=True)
            return None

grok = GrokEngine(GROK_SSO_TOKENS)

# ==========================================
# 🚀 INDEXING LOGS (WAJIB MUNCUL)
# ==========================================

def submit_indexing(slug):
    full_url = f"{WEBSITE_URL}/{slug}/"
    print(f"      📡 SUBMITTING INDEXING FOR: {full_url}", flush=True)
    
    # 1. IndexNow
    try:
        host = WEBSITE_URL.replace("https://", "").replace("http://", "")
        data = {"host": host, "key": INDEXNOW_KEY, "keyLocation": f"{WEBSITE_URL}/{INDEXNOW_KEY}.txt", "urlList": [full_url]}
        resp = requests.post("https://api.indexnow.org/indexnow", json=data, timeout=15)
        print(f"      🚀 IndexNow Log: Success (HTTP {resp.status_code})", flush=True)
    except Exception as e:
        print(f"      ❌ IndexNow Error: {e}", flush=True)

    # 2. Google Indexing API
    if GOOGLE_JSON_KEY and GOOGLE_LIBS_AVAILABLE:
        try:
            creds_dict = json.loads(GOOGLE_JSON_KEY)
            credentials = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, ["https://www.googleapis.com/auth/indexing"])
            service = build("indexing", "v3", credentials=credentials)
            service.urlNotifications().publish(body={"url": full_url, "type": "URL_UPDATED"}).execute()
            print(f"      🚀 Google Index Log: Success", flush=True)
        except Exception as e:
            print(f"      ❌ Google Index Error: {e}", flush=True)
    else:
        print(f"      ⚠️ Google Index Log: Skipped (Key/Libs missing)", flush=True)

# ==========================================
# 🎨 IMAGE GENERATOR
# ==========================================

def generate_image(prompt, filename):
    print(f"      🎨 Grok Drawing Start: {filename}", flush=True)
    styled_prompt = f"{prompt}, cartoon vector art, gta loading screen style, thick outlines, flat vibrant colors"
    res = grok.call_rpc(styled_prompt, is_image=True)
    
    if res and res.get('image_url'):
        try:
            img_data = requests.get(res['image_url']).content
            img = Image.open(BytesIO(img_data)).convert("RGB")
            draw = ImageDraw.Draw(img)
            draw.text((20, 20), "@JeepDaily", fill=(255, 255, 255))
            output_path = f"{IMAGE_DIR}/{filename}"
            img.save(output_path, "WEBP", quality=90)
            print(f"      ✅ Image Saved: {output_path}", flush=True)
            return f"/images/{filename}"
        except Exception as e:
            print(f"      ❌ Image Save Error: {e}", flush=True)
    else:
        print(f"      ⚠️ Image skipped (Grok returned no URL)", flush=True)
    return ""

# ==========================================
# 📝 ARTICLE GENERATOR
# ==========================================

def generate_article_data(title, summary, source_link):
    author = random.choice(["Rick O'Connell", "Sarah Miller", "Mike Stevens"])
    prompt = f"Write a 1000-word SEO article in JSON about: {title}. Context: {summary}. JSON keys: seo_title, meta_desc, category, tags, content_markdown, schema_json, image_prompt."
    
    print(f"      🤖 Grok Writing Start: {title}", flush=True)
    res = grok.call_rpc(prompt)
    
    if not res:
        print(f"      ❌ Grok returned None (HTTP Error)", flush=True)
        return None, None
    
    if not res['text']:
        print(f"      ❌ Grok returned empty text", flush=True)
        return None, None

    # Ekstrak JSON
    try:
        match = re.search(r'(\{.*\})', res['text'], re.DOTALL)
        data = json.loads(match.group(1))
        return data, author
    except Exception as e:
        print(f"      ❌ JSON Parse Error: {e}", flush=True)
        return None, None

# ==========================================
# 🏁 MAIN WORKFLOW
# ==========================================

def main():
    for d in [CONTENT_DIR, IMAGE_DIR, DATA_DIR]: os.makedirs(d, exist_ok=True)
    print(f"🔥 JEEP ENGINE STARTED | TOKENS: {len(GROK_SSO_TOKENS)} 🔥", flush=True)

    for cat, rss_url in RSS_SOURCES.items():
        print(f"\n📡 Source: {cat}", flush=True)
        feed = feedparser.parse(rss_url)
        if not feed.entries: continue

        for entry in feed.entries[:1]:
            clean_title = entry.title.split(" - ")[0]
            slug = slugify(clean_title, max_length=50)
            file_path = f"{CONTENT_DIR}/{slug}.md"

            if os.path.exists(file_path):
                print(f"      ⏭️ Skipping: {slug} (Already exists)", flush=True)
                continue

            print(f"      📝 Processing: {clean_title}", flush=True)
            
            # 1. GENERATE
            data, author = generate_article_data(clean_title, entry.summary, entry.link)
            
            # Jika data gagal dibuat, kita harus tahu kenapa (Log sudah ada di dalam fungsi)
            if not data:
                continue

            # 2. IMAGE
            image_url = generate_image(data.get('image_prompt', clean_title), f"{slug}.webp")

            # 3. SAVE
            schema_tag = f'<script type="application/ld+json">{json.dumps(data.get("schema_json", {}))}</script>'
            md_content = f"""---
title: "{data.get('seo_title', clean_title).replace('"', "'")}"
date: {datetime.now().strftime("%Y-%m-%dT%H:%M:%S+00:00")}
author: "{author}"
categories: ["{cat}"]
featured_image: "{image_url}"
description: "{data.get('meta_desc', '').replace('"', "'")}"
slug: "{slug}"
url: "/{slug}/"
---
{schema_tag}
{data.get('content_markdown', 'Content error.')}
"""
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(md_content)
            
            # 4. INDEXING (LOG MUNCUL DI SINI)
            submit_indexing(slug)

            print(f"      ✅ SUCCESSFULLY DONE: {slug}", flush=True)
            time.sleep(10)

if __name__ == "__main__":
    main()
