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

# Menggunakan curl_cffi karena ini yang paling stabil meniru browser
from curl_cffi import requests

# ==========================================
# 🚀 FUNGSI LOGGING (PASTI MUNCUL)
# ==========================================
def log_status(msg):
    # flush=True memaksa log muncul di GitHub Actions detik itu juga
    now = datetime.now().strftime('%H:%M:%S')
    print(f"[{now}] {msg}", flush=True)

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
    "Wrangler News": "https://news.google.com/rss/search?q=Jeep+Wrangler&hl=en-US",
    "Off-road Tips": "https://news.google.com/rss/search?q=Jeep+Offroad&hl=en-US",
    "Jeep Mods": "https://news.google.com/rss/search?q=Jeep+Modifications&hl=en-US"
}

# ==========================================
# 🔄 GROK ENGINE (CARA AWAL ANDA)
# ==========================================
class GrokEngine:
    def __init__(self, tokens):
        self.tokens = tokens
        self.current_idx = 0

    def get_token(self):
        token = self.tokens[self.current_idx]
        self.current_idx = (self.current_idx + 1) % len(self.tokens)
        return token

    def call(self, prompt, is_image=False):
        token = self.get_token()
        url = "https://grok.com/api/rpc/chat/completion"
        
        headers = {
            "Authorization": f"Bearer {token}",
            "x-sso-token": token,
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        }
        
        payload = {
            "modelName": "grok-latest",
            "message": prompt,
            "intent": "IMAGE_GEN" if is_image else "UNKNOWN"
        }

        try:
            # Gunakan curl_cffi untuk impersonate browser
            resp = requests.post(url, headers=headers, json=payload, impersonate="chrome110", timeout=120)
            
            if resp.status_code != 200:
                log_status(f"      ❌ ERROR API: Status {resp.status_code}")
                return None

            full_text = ""
            img_url = ""
            for line in resp.text.splitlines():
                try:
                    chunk = json.loads(line)
                    res = chunk.get("result", {}).get("response", {})
                    if "token" in res: full_text += res["token"]
                    if "attachments" in res:
                        for att in res["attachments"]:
                            if att.get("type") == "image": img_url = att.get("url")
                except: continue
            return {"text": full_text, "image_url": img_url}
        except Exception as e:
            log_status(f"      ❌ ERROR KONEKSI: {e}")
            return None

grok = GrokEngine(GROK_SSO_TOKENS)

# ==========================================
# 🚀 SUBMIT INDEXING (LOG YANG ANDA MINTA)
# ==========================================
def submit_indexing(slug):
    full_url = f"{WEBSITE_URL}/{slug}/"
    log_status(f"      📡 [INDEX LOG] Memproses Submit Indexing: {full_url}")
    
    # 1. IndexNow (Bing/Yandex)
    try:
        host = WEBSITE_URL.replace("https://", "").replace("http://", "")
        data = {"host": host, "key": INDEXNOW_KEY, "keyLocation": f"{WEBSITE_URL}/{INDEXNOW_KEY}.txt", "urlList": [full_url]}
        r = requests.post("https://api.indexnow.org/indexnow", json=data, timeout=10)
        log_status(f"      🚀 [INDEX LOG] IndexNow Status: {r.status_code} (Sukses)")
    except:
        log_status("      ❌ [INDEX LOG] IndexNow Gagal.")

    # 2. Google Indexing API
    if GOOGLE_JSON_KEY:
        try:
            from oauth2client.service_account import ServiceAccountCredentials
            from googleapiclient.discovery import build
            creds = ServiceAccountCredentials.from_json_keyfile_dict(json.loads(GOOGLE_JSON_KEY), ["https://www.googleapis.com/auth/indexing"])
            service = build("indexing", "v3", credentials=creds)
            service.urlNotifications().publish(body={"url": full_url, "type": "URL_UPDATED"}).execute()
            log_status(f"      🚀 [INDEX LOG] Google Index: Berhasil Terkirim.")
        except Exception as e:
            log_status(f"      ❌ [INDEX LOG] Google Index Gagal: {e}")

# ==========================================
# 🏁 MAIN WORKFLOW
# ==========================================
def main():
    os.makedirs(CONTENT_DIR, exist_ok=True)
    os.makedirs(IMAGE_DIR, exist_ok=True)
    
    log_status(f"🔥 JEEP ENGINE STARTED | TOKENS: {len(GROK_SSO_TOKENS)}")

    for cat, rss_url in RSS_SOURCES.items():
        log_status(f"\n📡 SUMBER: {cat}")
        feed = feedparser.parse(rss_url)
        if not feed.entries: continue

        for entry in feed.entries[:1]:
            clean_title = entry.title.split(" - ")[0]
            slug = slugify(clean_title, max_length=50)
            file_path = f"{CONTENT_DIR}/{slug}.md"

            if os.path.exists(file_path):
                log_status(f"      ⏭️ [SKIP] Sudah ada: {slug}")
                continue

            log_status(f"      📝 [CONTENT] Menulis Artikel: {clean_title}")
            
            # 1. GENERATE ARTIKEL
            res = grok.call(f"Write a 1000-word SEO article in JSON format about: {clean_title}. Keys: seo_title, content_markdown, image_prompt.")
            
            if not res or not res.get('text'):
                log_status("      ❌ [ERROR] Grok gagal memberikan respon. Skip.")
                continue

            try:
                # Ambil JSON
                data = json.loads(re.search(r'(\{.*\})', res['text'], re.DOTALL).group(1))
                
                # 2. GENERATE GAMBAR
                log_status(f"      🎨 [IMAGE] Generate Gambar...")
                img_res = grok.call(data.get('image_prompt', clean_title), is_image=True)
                img_path = ""
                if img_res and img_res.get('image_url'):
                    try:
                        img_data = requests.get(img_res['image_url']).content
                        img = Image.open(BytesIO(img_data)).convert("RGB")
                        draw = ImageDraw.Draw(img)
                        draw.text((20, 20), "@JeepDaily", fill=(255, 255, 255))
                        img.save(f"{IMAGE_DIR}/{slug}.webp", "WEBP")
                        img_path = f"/images/{slug}.webp"
                        log_status(f"      ✅ [IMAGE LOG] Gambar disimpan.")
                    except: log_status("      ❌ [IMAGE LOG] Gagal simpan.")

                # 3. SIMPAN FILE
                md_body = f"---\ntitle: \"{data.get('seo_title', clean_title)}\"\ndate: {datetime.now().isoformat()}\nfeatured_image: \"{img_path}\"\nslug: \"{slug}\"\nurl: \"/{slug}/\"\n---\n{data.get('content_markdown', '')}"
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(md_body)
                
                log_status(f"      ✅ [FILE LOG] Berhasil membuat file: {slug}.md")

                # 4. SUBMIT INDEXING (LOG PASTI MUNCUL DISINI)
                submit_indexing(slug)

                log_status(f"      ✅ [SUCCESS] SELESAI: {slug}")

            except Exception as e:
                log_status(f"      ❌ [ERROR] Gagal proses data: {e}")

            time.sleep(10)

if __name__ == "__main__":
    main()
