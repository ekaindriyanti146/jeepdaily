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
# ⚙️ CONFIGURATION
# ==========================================

# Ambil token dari GitHub Secrets
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
# 🔄 GROK ENGINE (STEALTH MODE TO BYPASS 403)
# ==========================================

class GrokEngine:
    def __init__(self, tokens):
        self.tokens = tokens
        self.current_idx = 0

    def get_token(self):
        if not self.tokens: return None
        token = self.tokens[self.current_idx]
        self.current_idx = (self.current_idx + 1) % len(self.tokens)
        return token

    def call_rpc(self, prompt, is_image=False):
        token = self.get_token()
        if not token: return None
        
        url = "https://grok.com/api/rpc/chat/completion"
        
        # STEALTH HEADERS: Meniru Browser Chrome Asli untuk menembus Cloudflare
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": "https://grok.com",
            "Referer": "https://grok.com/",
            "sec-ch-ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
        }

        payload = {
            "modelName": "grok-latest",
            "message": prompt,
            "fileAttachments": [],
            "intent": "IMAGE_GEN" if is_image else "UNKNOWN"
        }

        try:
            # Gunakan session untuk menghandle cookie otomatis
            session = requests.Session()
            response = session.post(url, headers=headers, json=payload, timeout=120)
            
            if response.status_code == 403:
                print(f"      ❌ Grok 403: Cloudflare Blocked this request. Token might be invalid or IP blacklisted.")
                return None
            
            if response.status_code != 200:
                print(f"      ❌ Grok Error {response.status_code}")
                return None

            full_text = ""
            image_url = ""
            for line in response.text.splitlines():
                if not line.strip(): continue
                try:
                    chunk = json.loads(line)
                    res = chunk.get("result", {}).get("response", {})
                    if "token" in res: full_text += res["token"]
                    if "attachments" in res:
                        for att in res["attachments"]:
                            if att.get("type") == "image": image_url = att.get("url")
                except: continue
            return {"text": full_text, "image_url": image_url}
        except Exception as e:
            print(f"      ❌ Grok RPC Error: {e}")
            return None

grok = GrokEngine(GROK_SSO_TOKENS)

# ==========================================
# 🚀 INDEXING LOGS (PASTI MUNCUL)
# ==========================================

def submit_indexing(slug):
    full_url = f"{WEBSITE_URL}/{slug}/"
    print(f"      📡 SUBMITTING INDEXING LOG:")
    
    # 1. IndexNow
    try:
        host = WEBSITE_URL.replace("https://", "").replace("http://", "")
        data = {"host": host, "key": INDEXNOW_KEY, "keyLocation": f"{WEBSITE_URL}/{INDEXNOW_KEY}.txt", "urlList": [full_url]}
        resp = requests.post("https://api.indexnow.org/indexnow", json=data, timeout=15)
        print(f"      🚀 IndexNow: {full_url} -> Status {resp.status_code}")
    except Exception as e:
        print(f"      ❌ IndexNow Error: {e}")

    # 2. Google Indexing
    if GOOGLE_JSON_KEY and GOOGLE_LIBS_AVAILABLE:
        try:
            creds_dict = json.loads(GOOGLE_JSON_KEY)
            credentials = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, ["https://www.googleapis.com/auth/indexing"])
            service = build("indexing", "v3", credentials=credentials)
            service.urlNotifications().publish(body={"url": full_url, "type": "URL_UPDATED"}).execute()
            print(f"      🚀 Google Index: {full_url} -> Success")
        except Exception as e:
            print(f"      ❌ Google Index Error: {e}")
    else:
        print(f"      ⚠️ Google Index: Skipped (Key/Libs Missing)")

# ==========================================
# 🎨 IMAGE GENERATOR
# ==========================================

def generate_image(prompt, filename):
    print(f"      🎨 GENERATING IMAGE LOG: {filename}")
    # Jika Grok 403, kita butuh fallback agar indexing tetap jalan
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
        except:
            print(f"      ❌ Image Save Failed")
    else:
        print(f"      ❌ Image Gen Failed (Grok 403/Error)")
    return ""

# ==========================================
# 🏁 MAIN WORKFLOW
# ==========================================

def main():
    for d in [CONTENT_DIR, IMAGE_DIR, DATA_DIR]: os.makedirs(d, exist_ok=True)
    print(f"🔥 JEEP ENGINE STARTED | TOKENS: {len(GROK_SSO_TOKENS)} 🔥")

    for cat_name, rss_url in RSS_SOURCES.items():
        print(f"\n📡 Source Category: {cat_name}")
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
            
            # 1. GENERATE CONTENT
            prompt = f"Write a 1000-word SEO article in JSON about: {clean_title}. Keys: seo_title, meta_desc, content_markdown, schema_json, image_prompt."
            res = grok.call_rpc(prompt)
            
            # JIKA GROK 403/GAGAL
            if not res or not res['text']:
                print(f"      ❌ Grok 403 Blocked Article Generation. Skipping to next...")
                continue

            # EKSTRAK JSON
            try:
                match = re.search(r'(\{.*\})', res['text'], re.DOTALL)
                data = json.loads(match.group(1))
            except:
                print(f"      ❌ JSON Parse Error. Grok output was not valid JSON.")
                continue

            # 2. GENERATE IMAGE
            img_url = generate_image(data.get('image_prompt', clean_title), f"{slug}.webp")

            # 3. SAVE MARKDOWN
            schema_tag = f'<script type="application/ld+json">{json.dumps(data.get("schema_json", {}))}</script>'
            md_content = f"""---
title: "{data.get('seo_title', clean_title).replace('"', "'")}"
date: {datetime.now().strftime("%Y-%m-%dT%H:%M:%S+00:00")}
author: "Rick O'Connell"
categories: ["{cat_name}"]
featured_image: "{img_url}"
description: "{data.get('meta_desc', '').replace('"', "'")}"
slug: "{slug}"
url: "/{slug}/"
---
{schema_tag}
{data.get('content_markdown', 'Content Error')}
---
*Analysis by Rick O'Connell based on [{clean_title}]({entry.link}).*
"""
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(md_content)
            
            # 4. SUBMIT INDEXING (LOG PASTI MUNCUL)
            submit_indexing(slug)

            print(f"      ✅ SUCCESSFULLY COMPLETED: {slug}")
            time.sleep(15)

if __name__ == "__main__":
    main()
