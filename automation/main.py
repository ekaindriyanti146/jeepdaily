import os, json, requests, feedparser, time, re, random, sys
from urllib.parse import quote
from datetime import datetime
from slugify import slugify
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont

# ==========================================
# 🚀 VERBOSE LOGGING (PASTI MUNCUL DI ACTIONS)
# ==========================================
def log_event(msg):
    # Menggunakan sys.stdout.flush() agar log tidak tertahan di buffer
    timestamp = datetime.now().strftime('%H:%M:%S')
    print(f"[{timestamp}] {msg}", flush=True)

# ==========================================
# ⚙️ CONFIGURATION
# ==========================================
GROK_KEYS_RAW = os.environ.get("GROK_SSO_TOKENS", "") 
GROK_SSO_TOKENS = [k.strip() for k in GROK_KEYS_RAW.split(",") if k.strip()]

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
# 🔄 GROK ENGINE (SSO ROTATION MODE)
# ==========================================
class GrokEngine:
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
        
        # Header Stealth: Menggunakan SSO Token di dua tempat (Authorization & x-sso-token)
        # Ini adalah format terbaru yang diminta internal RPC Grok
        headers = {
            "Authorization": f"Bearer {token}",
            "x-sso-token": token,
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            "Accept": "*/*",
            "Origin": "https://grok.com",
            "Referer": "https://grok.com/",
            "sec-ch-ua-platform": '"Windows"',
        }
        
        payload = {
            "modelName": "grok-latest",
            "message": prompt,
            "intent": "IMAGE_GEN" if is_image else "UNKNOWN"
        }

        try:
            # Menggunakan timeout lebih lama karena generate 1000 kata butuh waktu
            response = requests.post(url, headers=headers, json=payload, timeout=180)
            
            if response.status_code == 403:
                log_event(f"      ❌ [API ERROR] 403 Forbidden. Cloudflare memblokir IP GitHub Actions.")
                return None
            
            if response.status_code != 200:
                log_event(f"      ❌ [API ERROR] Status {response.status_code}: {response.text[:100]}")
                return None

            full_text = ""
            image_url = ""
            
            # Parsing NDJSON (Grok mengembalikan data per baris JSON)
            for line in response.text.splitlines():
                if not line.strip(): continue
                try:
                    chunk = json.loads(line)
                    res_part = chunk.get("result", {}).get("response", {})
                    if "token" in res_part:
                        full_text += res_part["token"]
                    if "attachments" in res_part:
                        for att in res_part["attachments"]:
                            if att.get("type") == "image":
                                image_url = att.get("url")
                except: continue
                
            return {"text": full_text, "image_url": image_url}
        except Exception as e:
            log_event(f"      ❌ [EXCEPTION] {e}")
            return None

grok = GrokEngine(GROK_SSO_TOKENS)

# ==========================================
# 🚀 INDEXING LOGS (BAGIAN YANG ANDA MINTA)
# ==========================================
def submit_indexing(slug):
    full_url = f"{WEBSITE_URL}/{slug}/"
    log_event(f"      📡 [INDEXING] Memulai submit untuk: {full_url}")
    
    # 1. IndexNow
    try:
        host = WEBSITE_URL.replace("https://", "").replace("http://", "")
        data = {"host": host, "key": INDEXNOW_KEY, "keyLocation": f"{WEBSITE_URL}/{INDEXNOW_KEY}.txt", "urlList": [full_url]}
        resp = requests.post("https://api.indexnow.org/indexnow", json=data, timeout=15)
        log_event(f"      🚀 [INDEXNOW LOG] Status: {resp.status_code} - Berhasil Terkirim ke Bing/IndexNow")
    except Exception as e:
        log_event(f"      ❌ [INDEXNOW ERROR] {e}")

    # 2. Google Indexing API
    if GOOGLE_JSON_KEY:
        try:
            from oauth2client.service_account import ServiceAccountCredentials
            from googleapiclient.discovery import build
            creds = ServiceAccountCredentials.from_json_keyfile_dict(json.loads(GOOGLE_JSON_KEY), ["https://www.googleapis.com/auth/indexing"])
            service = build("indexing", "v3", credentials=creds)
            service.urlNotifications().publish(body={"url": full_url, "type": "URL_UPDATED"}).execute()
            log_event(f"      🚀 [GOOGLE INDEX LOG] Berhasil Terkirim ke Google Search Console")
        except Exception as e:
            log_event(f"      ❌ [GOOGLE INDEX ERROR] {e}")

# ==========================================
# 🏁 MAIN WORKFLOW
# ==========================================
def main():
    os.makedirs(CONTENT_DIR, exist_ok=True)
    os.makedirs(IMAGE_DIR, exist_ok=True)
    log_event(f"🔥 JEEP ENGINE STARTED | TOKENS: {len(GROK_SSO_TOKENS)}")

    for cat, rss_url in RSS_SOURCES.items():
        log_event(f"\n📡 SUMBER: {cat}")
        feed = feedparser.parse(rss_url)
        if not feed.entries: continue

        for entry in feed.entries[:1]:
            clean_title = entry.title.split(" - ")[0]
            slug = slugify(clean_title, max_length=50)
            file_path = f"{CONTENT_DIR}/{slug}.md"

            if os.path.exists(file_path):
                log_event(f"      ⏭️ [SKIP] Judul sudah ada: {slug}")
                continue

            # 1. GENERATE CONTENT
            log_event(f"      📝 [CONTENT] Sedang menulis artikel: {clean_title}")
            prompt = f"Write a 1000-word SEO article in JSON format about: {clean_title}. Keys: seo_title, meta_desc, content_markdown, schema_json, image_prompt."
            res = grok.call_grok(prompt)
            
            if not res or not res.get('text'):
                log_event(f"      ❌ [ERROR] Gagal generate artikel. Melewati ke sumber berikutnya.")
                continue

            # 2. PARSING & SAVE
            try:
                # Mencari JSON di dalam teks
                match = re.search(r'(\{.*\})', res['text'], re.DOTALL)
                data = json.loads(match.group(1))
                
                # Simpan Markdown
                md = f"""---
title: "{data.get('seo_title', clean_title)}"
date: {datetime.now().strftime('%Y-%m-%dT%H:%M:%S+00:00')}
description: "{data.get('meta_desc', '')}"
slug: "{slug}"
url: "/{slug}/"
---
{data.get('content_markdown', '')}
"""
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(md)
                
                log_event(f"      ✅ [SUCCESS] File berhasil dibuat: {file_path}")

                # 3. SUBMIT INDEXING (LOG MUNCUL DI SINI)
                submit_indexing(slug)

            except Exception as e:
                log_event(f"      ❌ [ERROR] Gagal memproses data artikel: {e}")

            time.sleep(10)

if __name__ == "__main__":
    main()
