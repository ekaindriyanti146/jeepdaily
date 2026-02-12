import os
import json
import time
import re
import random
import sys
from datetime import datetime
from slugify import slugify
from io import BytesIO
from PIL import Image, ImageDraw
import feedparser
import pytz

# ANTI-403: Menggunakan curl_cffi agar terdeteksi sebagai Chrome asli
from curl_cffi import requests

# ==========================================
# 🚀 VERBOSE LOGGING
# ==========================================
def log_event(msg):
    # Menggunakan flush=True agar log langsung muncul di GitHub Actions
    tz = pytz.timezone('Asia/Jakarta')
    timestamp = datetime.now(tz).strftime('%H:%M:%S')
    print(f"[{timestamp}] {msg}", flush=True)

# ==========================================
# ⚙️ CONFIGURATION
# ==========================================
GROK_KEYS_RAW = os.environ.get("GROK_SSO_TOKENS", "") 
GROK_SSO_TOKENS = [k.strip() for k in GROK_KEYS_RAW.split(",") if k.strip()]
GROK_COOKIES = os.environ.get("GROK_COOKIES", "") 

WEBSITE_URL = "https://dother.biz.id" 
INDEXNOW_KEY = "e74819b68a0f40e98f6ec3dc24f610f0" 
GOOGLE_JSON_KEY = os.environ.get("GOOGLE_INDEXING_KEY", "") 

CONTENT_DIR = "content/articles" 
IMAGE_DIR = "static/images"

RSS_SOURCES = {
    "Wrangler Life": "https://news.google.com/rss/search?q=Jeep+Wrangler&hl=en-US",
    "Off-road Tips": "https://news.google.com/rss/search?q=Jeep+Offroad&hl=en-US",
    "Jeep Mods": "https://news.google.com/rss/search?q=Jeep+Modifications&hl=en-US"
}

# ==========================================
# 🔄 GROK STEALTH ENGINE
# ==========================================
class GrokStealth:
    def __init__(self, tokens):
        self.tokens = tokens
        self.current_idx = 0

    def get_token(self):
        token = self.tokens[self.current_idx]
        self.current_idx = (self.current_idx + 1) % len(self.tokens)
        return token

    def call_grok(self, prompt, is_image=False):
        token = self.get_token()
        url = "https://grok.com/api/rpc/chat/completion"
        
        headers = {
            "Authorization": f"Bearer {token}",
            "x-sso-token": token,
            "Cookie": GROK_COOKIES,
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0",
            "Origin": "https://grok.com",
            "Referer": "https://grok.com/",
        }
        
        payload = {
            "modelName": "grok-latest",
            "message": prompt,
            "intent": "IMAGE_GEN" if is_image else "UNKNOWN"
        }

        try:
            # IMPERSONATE CHROME: Kunci utama bypass 403
            response = requests.post(
                url, 
                headers=headers, 
                json=payload, 
                impersonate="chrome110", 
                timeout=180
            )
            
            if response.status_code != 200:
                log_event(f"      ❌ [GROK ERROR] HTTP {response.status_code}. Cloudflare Blocked.")
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
            log_event(f"      ❌ [CONNECTION ERROR] {e}")
            return None

grok = GrokStealth(GROK_SSO_TOKENS)

# ==========================================
# 🚀 SUBMIT INDEXING
# ==========================================
def submit_indexing(slug):
    full_url = f"{WEBSITE_URL}/{slug}/"
    log_event(f"      📡 [INDEXING] MEMULAI SUBMIT UNTUK: {full_url}")
    
    # 1. IndexNow
    try:
        host = WEBSITE_URL.replace("https://", "").replace("http://", "")
        data = {"host": host, "key": INDEXNOW_KEY, "keyLocation": f"{WEBSITE_URL}/{INDEXNOW_KEY}.txt", "urlList": [full_url]}
        r = requests.post("https://api.indexnow.org/indexnow", json=data, timeout=10, impersonate="chrome110")
        log_event(f"      🚀 [INDEX LOG] IndexNow Status: {r.status_code}")
    except Exception as e:
        log_event(f"      ❌ [INDEX LOG] IndexNow Error: {e}")

    # 2. Google Indexing API
    if GOOGLE_JSON_KEY:
        try:
            from oauth2client.service_account import ServiceAccountCredentials
            from googleapiclient.discovery import build
            creds = json.loads(GOOGLE_JSON_KEY)
            c = ServiceAccountCredentials.from_json_keyfile_dict(creds, ["https://www.googleapis.com/auth/indexing"])
            service = build("indexing", "v3", credentials=c)
            service.urlNotifications().publish(body={"url": full_url, "type": "URL_UPDATED"}).execute()
            log_event(f"      🚀 [INDEX LOG] Google Index: Success")
        except Exception as e:
            log_event(f"      ❌ [INDEX LOG] Google Error: {e}")

# ==========================================
# 🏁 MAIN
# ==========================================
def main():
    for d in [CONTENT_DIR, IMAGE_DIR]: os.makedirs(d, exist_ok=True)
    log_event(f"🔥 JEEP ENGINE STARTED | TOKENS: {len(GROK_SSO_TOKENS)}")

    for cat_name, rss_url in RSS_SOURCES.items():
        log_event(f"\n📡 SUMBER: {cat_name}")
        feed = feedparser.parse(rss_url)
        if not feed or not feed.entries: continue

        for entry in feed.entries[:1]:
            clean_title = entry.title.split(" - ")[0]
            slug = slugify(clean_title, max_length=50)
            file_path = f"{CONTENT_DIR}/{slug}.md"

            if os.path.exists(file_path):
                log_event(f"      ⏭️ [SKIP] Judul sudah ada: {slug}")
                continue

            # 1. GENERATE ARTICLE
            log_event(f"      📝 [CONTENT] Sedang menulis: {clean_title}")
            res = grok.call_grok(f"Write a 1200-word SEO article in JSON format about: {clean_title}. Keys: seo_title, content_markdown, image_prompt.")
            
            if not res or not res.get('text'):
                log_event(f"      ❌ [ERROR] Gagal generate teks.")
                continue

            try:
                data = json.loads(re.search(r'(\{.*\})', res['text'], re.DOTALL).group(1))
                
                # 2. GENERATE IMAGE
                log_event(f"      🎨 [IMAGE] Generate Gambar...")
                img_res = grok.call_grok(data.get('image_prompt', clean_title), is_image=True)
                img_path = ""
                if img_res and img_res.get('image_url'):
                    try:
                        img_data = requests.get(img_res['image_url'], impersonate="chrome110").content
                        img = Image.open(BytesIO(img_data)).convert("RGB")
                        draw = ImageDraw.Draw(img)
                        draw.text((20, 20), "@JeepDaily", fill=(255, 255, 255))
                        img.save(f"{IMAGE_DIR}/{slug}.webp", "WEBP")
                        img_path = f"/images/{slug}.webp"
                        log_event(f"      ✅ [IMAGE LOG] Gambar Disimpan.")
                    except: log_event("      ❌ [IMAGE LOG] Gagal Simpan.")

                # 3. SAVE FILE
                md_content = f"""---
title: "{data.get('seo_title', clean_title)}"
date: {datetime.now().strftime('%Y-%m-%dT%H:%M:%S+00:00')}
featured_image: "{img_path}"
slug: "{slug}"
url: "/{slug}/"
---
{data.get('content_markdown', 'Error Content')}
"""
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(md_content)

                # 4. SUBMIT INDEXING
                submit_indexing(slug)
                log_event(f"      ✅ [SUCCESS] ARTIKEL SELESAI: {slug}")

            except Exception as e:
                log_event(f"      ❌ [ERROR] Gagal memproses data: {e}")

if __name__ == "__main__":
    main()
