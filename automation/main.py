import os
import json
import time
import re
import random
import sys
import uuid
from datetime import datetime
from slugify import slugify
from io import BytesIO
from PIL import Image, ImageDraw
import feedparser

# WAJIB: curl_cffi untuk bypass sidik jari TLS Cloudflare
from curl_cffi import requests

# ==========================================
# 🚀 VERBOSE LOGGING
# ==========================================
def log_event(msg):
    timestamp = datetime.now().strftime('%H:%M:%S')
    print(f"[{timestamp}] {msg}", flush=True)

# ==========================================
# ⚙️ CONFIGURATION
# ==========================================
GROK_KEYS_RAW = os.environ.get("GROK_SSO_TOKENS", "") 
GROK_SSO_TOKENS = [k.strip() for k in GROK_KEYS_RAW.split(",") if k.strip()]
GROK_COOKIES = os.environ.get("GROK_COOKIES", "") # AMBIL COOKIE UTUH DARI BROWSER

WEBSITE_URL = "https://dother.biz.id" 
INDEXNOW_KEY = "e74819b68a0f40e98f6ec3dc24f610f0" 
GOOGLE_JSON_KEY = os.environ.get("GOOGLE_INDEXING_KEY", "") 

CONTENT_DIR = "content/articles" 
IMAGE_DIR = "static/images"

RSS_SOURCES = {
    "Wrangler News": "https://news.google.com/rss/search?q=Jeep+Wrangler+News&hl=en-US",
    "Jeep Mods": "https://news.google.com/rss/search?q=Jeep+Modifications&hl=en-US"
}

# ==========================================
# 🔄 GROK ENGINE (ULTRA STEALTH)
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
        
        # Headers mengikuti struktur backend yang Anda kirim (Stealth Mode)
        headers = {
            "Authorization": f"Bearer {token}",
            "Cookie": GROK_COOKIES,
            "x-sso-token": token,
            "x-statsig-id": str(uuid.uuid4()), # Unik sesuai file config.py
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Origin": "https://grok.com",
            "Referer": "https://grok.com/",
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Sec-Ch-Ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        }
        
        payload = {
            "modelName": "grok-latest",
            "message": prompt,
            "fileAttachments": [],
            "intent": "IMAGE_GEN" if is_image else "UNKNOWN"
        }

        try:
            # Menggunakan impersonate chrome110 (Paling stabil untuk menembus 403)
            response = requests.post(
                url, 
                headers=headers, 
                json=payload, 
                impersonate="chrome110", 
                timeout=120
            )
            
            if response.status_code != 200:
                log_event(f"      ❌ [API LOG] Status {response.status_code}. Cloudflare/Grok memblokir request.")
                return None

            full_text = ""
            image_url = ""
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
            log_event(f"      ❌ [API LOG] Error Koneksi: {e}")
            return None

grok = GrokEngine(GROK_SSO_TOKENS)

# ==========================================
# 🚀 SUBMIT INDEXING (LOG WAJIB MUNCUL SETELAH FILE JADI)
# ==========================================
def submit_indexing(slug):
    full_url = f"{WEBSITE_URL}/{slug}/"
    log_event(f"      📡 [INDEXING] Memproses submit untuk: {full_url}")
    
    # 1. IndexNow (Bing/Yandex)
    try:
        host = "dother.biz.id"
        data = {"host": host, "key": INDEXNOW_KEY, "keyLocation": f"https://{host}/{INDEXNOW_KEY}.txt", "urlList": [full_url]}
        r = requests.post("https://api.indexnow.org/indexnow", json=data, timeout=10)
        log_event(f"      🚀 [INDEX LOG] IndexNow Status: {r.status_code} (Success)")
    except Exception as e:
        log_event(f"      ❌ [INDEX LOG] IndexNow Failed: {e}")

    # 2. Google Indexing API
    if GOOGLE_JSON_KEY:
        try:
            from oauth2client.service_account import ServiceAccountCredentials
            from googleapiclient.discovery import build
            creds = ServiceAccountCredentials.from_json_keyfile_dict(json.loads(GOOGLE_JSON_KEY), ["https://www.googleapis.com/auth/indexing"])
            service = build("indexing", "v3", credentials=creds)
            service.urlNotifications().publish(body={"url": full_url, "type": "URL_UPDATED"}).execute()
            log_event(f"      🚀 [INDEX LOG] Google Index: Berhasil Terkirim.")
        except Exception as e:
            log_event(f"      ❌ [INDEX LOG] Google Index Failed: {e}")

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
                log_event(f"      ⏭️ [SKIP] Sudah ada: {slug}")
                continue

            # 1. GENERATE ARTIKEL
            log_event(f"      📝 [CONTENT] Sedang menulis: {clean_title}")
            res = grok.call_rpc(f"Write a 1000-word SEO article in JSON format about: {clean_title}. Keys: seo_title, content_markdown, image_prompt.")
            
            if not res or not res.get('text'):
                log_event("      ❌ [STOP] Gagal tembus Cloudflare (403). Log Indexing tidak dipanggil karena artikel tidak jadi.")
                continue

            try:
                # Parsing JSON
                data = json.loads(re.search(r'(\{.*\})', res['text'], re.DOTALL).group(1))
                
                # 2. GENERATE GAMBAR
                log_event("      🎨 [IMAGE] Generate Gambar...")
                img_res = grok.call_rpc(data.get('image_prompt', clean_title), is_image=True)
                img_path = ""
                if img_res and img_res.get('image_url'):
                    try:
                        img_data = requests.get(img_res['image_url']).content
                        img = Image.open(BytesIO(img_data)).convert("RGB")
                        draw = ImageDraw.Draw(img)
                        draw.text((20, 20), "@JeepDaily", fill=(255, 255, 255))
                        img.save(f"{IMAGE_DIR}/{slug}.webp", "WEBP")
                        img_path = f"/images/{slug}.webp"
                        log_event("      ✅ [IMAGE LOG] Gambar disimpan.")
                    except: log_event("      ❌ [IMAGE LOG] Simpan gambar gagal.")

                # 3. SIMPAN FILE (Konten Berhasil Terbuat)
                md_body = f"---\ntitle: \"{data.get('seo_title', clean_title)}\"\ndate: {datetime.now().isoformat()}\nfeatured_image: \"{img_path}\"\nslug: \"{slug}\"\nurl: \"/{slug}/\"\n---\n{data.get('content_markdown', 'Error')}"
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(md_body)
                
                # 4. SUBMIT INDEXING (LOG MUNCUL DI SINI)
                submit_indexing(slug)
                log_event(f"      ✅ [SUCCESS] ARTIKEL SELESAI: {slug}")

            except Exception as e:
                log_event(f"      ❌ [ERROR] Gagal memproses data JSON Grok: {e}")

            time.sleep(10)

if __name__ == "__main__":
    main()
