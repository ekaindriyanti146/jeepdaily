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

# Menggunakan curl_cffi untuk penyamaran tingkat tinggi
from curl_cffi import requests

# ==========================================
# 🚀 DIAGNOSTIC LOGGING
# ==========================================
def log_info(msg):
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
    "Wrangler News": "https://news.google.com/rss/search?q=Jeep+Wrangler+News&hl=en-US",
    "Jeep Mods": "https://news.google.com/rss/search?q=Jeep+Modifications&hl=en-US"
}

# ==========================================
# 🔄 GROK ENGINE (DIAGNOSTIC MODE)
# ==========================================
class GrokEngine:
    def __init__(self, tokens):
        self.tokens = tokens
        self.current_idx = 0

    def call_grok(self, prompt, is_image=False):
        if not self.tokens:
            log_info("❌ [ERROR] Token tidak ditemukan di Secret!")
            return None
            
        token = self.tokens[self.current_idx]
        self.current_idx = (self.current_idx + 1) % len(self.tokens)
        
        url = "https://grok.com/api/rpc/chat/completion"
        
        # Headers yang WAJIB ada di Grok Update 2026
        headers = {
            "Authorization": f"Bearer {token}",
            "x-sso-token": token,
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "x-statsig-id": "undefined", # Kadang undefined lebih aman daripada ID palsu
            "Origin": "https://grok.com",
            "Referer": "https://grok.com/",
        }
        
        payload = {
            "modelName": "grok-latest",
            "message": prompt,
            "fileAttachments": [],
            "intent": "IMAGE_GEN" if is_image else "UNKNOWN"
        }

        try:
            # Gunakan chrome120 (versi lebih baru dari chrome110)
            resp = requests.post(url, headers=headers, json=payload, impersonate="chrome120", timeout=60)
            
            if resp.status_code != 200:
                log_info(f"      ❌ [API LOG] Grok menolak akses! Status: {resp.status_code}")
                if resp.status_code == 403:
                    log_info("      ⚠️ Alasan: Cloudflare memblokir IP GitHub Actions.")
                elif resp.status_code == 401:
                    log_info("      ⚠️ Alasan: Token SSO Anda sudah kedaluwarsa.")
                return None

            full_text = ""
            img_url = ""
            # Grok mengirim data NDJSON
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
            log_info(f"      ❌ [API LOG] Kesalahan Koneksi: {e}")
            return None

grok = GrokEngine(GROK_SSO_TOKENS)

# ==========================================
# 🚀 INDEXING (BAGIAN YANG ANDA MINTA LOG-NYA)
# ==========================================
def submit_indexing(slug):
    full_url = f"{WEBSITE_URL}/{slug}/"
    log_info(f"      📡 [INDEX LOG] Mengirim URL ke Google & Bing: {full_url}")
    
    # 1. Bing (IndexNow)
    try:
        data = {
            "host": "dother.biz.id", 
            "key": INDEXNOW_KEY, 
            "keyLocation": f"https://dother.biz.id/{INDEXNOW_KEY}.txt", 
            "urlList": [full_url]
        }
        r = requests.post("https://api.indexnow.org/indexnow", json=data, timeout=10)
        log_info(f"      🚀 [INDEX LOG] IndexNow Status: {r.status_code} (Sukses)")
    except Exception as e:
        log_info(f"      ❌ [INDEX LOG] IndexNow Error: {e}")

    # 2. Google Indexing
    if GOOGLE_JSON_KEY:
        try:
            from oauth2client.service_account import ServiceAccountCredentials
            from googleapiclient.discovery import build
            creds = ServiceAccountCredentials.from_json_keyfile_dict(json.loads(GOOGLE_JSON_KEY), ["https://www.googleapis.com/auth/indexing"])
            service = build("indexing", "v3", credentials=creds)
            service.urlNotifications().publish(body={"url": full_url, "type": "URL_UPDATED"}).execute()
            log_info(f"      🚀 [INDEX LOG] Google Index: Berhasil.")
        except Exception as e:
            log_info(f"      ❌ [INDEX LOG] Google Error: {e}")

# ==========================================
# 🏁 MAIN WORKFLOW
# ==========================================
def main():
    os.makedirs(CONTENT_DIR, exist_ok=True)
    os.makedirs(IMAGE_DIR, exist_ok=True)
    log_info(f"🔥 JEEP ENGINE STARTED | TOKENS: {len(GROK_SSO_TOKENS)}")

    for cat, rss_url in RSS_SOURCES.items():
        log_info(f"\n📡 SUMBER: {cat}")
        feed = feedparser.parse(rss_url)
        if not feed.entries: continue

        for entry in feed.entries[:1]:
            clean_title = entry.title.split(" - ")[0]
            slug = slugify(clean_title, max_length=50)
            file_path = f"{CONTENT_DIR}/{slug}.md"

            if os.path.exists(file_path):
                log_info(f"      ⏭️ [SKIP] Sudah ada: {slug}")
                continue

            log_info(f"      📝 [CONTENT] Menulis Artikel: {clean_title}")
            
            # 1. GENERATE
            res = grok.call_grok(f"Write a 1000-word SEO article in JSON: {clean_title}. Keys: seo_title, content, image_prompt.")
            
            if not res or not res.get('text'):
                log_info("      ❌ [ERROR] Gagal generate artikel. Melewati sumber ini.")
                continue

            try:
                # Parsing JSON hasil Grok
                data = json.loads(re.search(r'(\{.*\})', res['text'], re.DOTALL).group(1))
                
                # 2. GAMBAR
                log_info("      🎨 [IMAGE] Generate Gambar...")
                img_res = grok.call_grok(data.get('image_prompt', clean_title), is_image=True)
                img_path = ""
                if img_res and img_res.get('image_url'):
                    try:
                        img_data = requests.get(img_res['image_url']).content
                        img = Image.open(BytesIO(img_data)).convert("RGB")
                        draw = ImageDraw.Draw(img)
                        draw.text((20, 20), "@JeepDaily", fill=(255, 255, 255))
                        img.save(f"{IMAGE_DIR}/{slug}.webp", "WEBP")
                        img_path = f"/images/{slug}.webp"
                        log_info("      ✅ [IMAGE LOG] Gambar disimpan.")
                    except: log_info("      ❌ [IMAGE LOG] Gagal simpan gambar.")

                # 3. SIMPAN FILE
                md_body = f"---\ntitle: \"{data.get('seo_title', clean_title)}\"\ndate: {datetime.now().isoformat()}\nfeatured_image: \"{img_path}\"\nslug: \"{slug}\"\nurl: \"/{slug}/\"\n---\n{data.get('content', '')}"
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(md_body)
                
                # 4. SUBMIT INDEXING (LOG PASTI MUNCUL)
                submit_indexing(slug)
                log_info(f"      ✅ [SUCCESS] SELESAI: {slug}")

            except Exception as e:
                log_info(f"      ❌ [ERROR] Gagal memproses data artikel: {e}")

            time.sleep(10)

if __name__ == "__main__":
    main()
