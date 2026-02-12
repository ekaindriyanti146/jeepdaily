import os, json, time, re, random, sys, uuid
from datetime import datetime
from slugify import slugify
from io import BytesIO
from PIL import Image, ImageDraw
import feedparser
import pytz

# TEKNIK DARI FILE ANDA: Menggunakan curl_cffi untuk request level browser
from curl_cffi import requests

# ==========================================
# 🚀 SYSTEM LOGGING
# ==========================================
def log_event(msg):
    tz = pytz.timezone('Asia/Jakarta')
    timestamp = datetime.now(tz).strftime('%H:%M:%S')
    print(f"[{timestamp}] {msg}", flush=True)

# ==========================================
# ⚙️ CONFIGURATION
# ==========================================
GROK_KEYS_RAW = os.environ.get("GROK_SSO_TOKENS", "") 
GROK_SSO_TOKENS = [k.strip() for k in GROK_KEYS_RAW.split(",") if k.strip()]
GROK_COOKIES = os.environ.get("GROK_COOKIES", "") # WAJIB ADA

WEBSITE_URL = "https://dother.biz.id" 
INDEXNOW_KEY = "e74819b68a0f40e98f6ec3dc24f610f0" 
GOOGLE_JSON_KEY = os.environ.get("GOOGLE_INDEXING_KEY", "") 

CONTENT_DIR = "content/articles" 
IMAGE_DIR = "static/images"

# ==========================================
# 🚀 SUBMIT INDEXING (LOG PASTI MUNCUL)
# ==========================================
def submit_indexing(slug):
    full_url = f"{WEBSITE_URL}/{slug}/"
    log_event(f"      📡 [INDEX LOG] Submit URL: {full_url}")
    
    # 1. IndexNow
    try:
        data = {"host": "dother.biz.id", "key": INDEXNOW_KEY, "keyLocation": f"https://dother.biz.id/{INDEXNOW_KEY}.txt", "urlList": [full_url]}
        # Gunakan requests biasa untuk indexing (tidak perlu impersonate)
        import requests as req
        r = req.post("https://api.indexnow.org/indexnow", json=data, timeout=10)
        log_event(f"      🚀 [INDEX LOG] IndexNow Status: {r.status_code}")
    except Exception as e:
        log_event(f"      ❌ [INDEX ERROR] IndexNow: {e}")

    # 2. Google Indexing
    if GOOGLE_JSON_KEY:
        try:
            from oauth2client.service_account import ServiceAccountCredentials
            from googleapiclient.discovery import build
            creds = json.loads(GOOGLE_JSON_KEY)
            c = ServiceAccountCredentials.from_json_keyfile_dict(creds, ["https://www.googleapis.com/auth/indexing"])
            service = build("indexing", "v3", credentials=c)
            service.urlNotifications().publish(body={"url": full_url, "type": "URL_UPDATED"}).execute()
            log_event(f"      🚀 [INDEX LOG] Google Index: Sukses.")
        except:
            log_event(f"      ❌ [INDEX ERROR] Google Index Gagal.")

# ==========================================
# 🔄 GROK API CLIENT (ADAPTASI DARI FILE ANDA)
# ==========================================
class GrokClient:
    def __init__(self):
        self.token = GROK_SSO_TOKENS[0] if GROK_SSO_TOKENS else None
        self.cookie = GROK_COOKIES
        # Endpoint RPC yang digunakan oleh App Grok
        self.url = "https://grok.com/rest/app-chat/conversations/new" 

    def generate(self, prompt, is_image=False):
        if not self.token or not self.cookie:
            log_event("❌ [CONFIG ERROR] Token atau Cookie kosong!")
            return None

        # Headers meniru App Grok (Chrome 120+)
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Cookie": self.cookie,
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Origin": "https://grok.com",
            "Referer": "https://grok.com/",
            "x-sso-token": self.token, # Kunci penting
        }

        # Payload JSON standar Grok RPC
        payload = {
            "modelName": "grok-latest",
            "message": prompt,
            "timezoneOffset": -420,
            "intent": "IMAGE_GEN" if is_image else "NORMAL",
            "fileAttachments": [],
            "disableSearch": False,
            "enableImageGeneration": True
        }

        try:
            # GUNAKAN CURL_CFFI (Impersonate Chrome)
            session = requests.Session()
            response = session.post(
                "https://grok.com/api/rpc/chat/completion", # Endpoint RPC Stabil
                headers=headers,
                json=payload,
                impersonate="chrome120", # Meniru sidik jari Chrome 120
                timeout=120
            )

            if response.status_code != 200:
                log_event(f"      ❌ [API ERROR] HTTP {response.status_code}. Response: {response.text[:50]}...")
                return None

            # Grok mengirim respon streaming (NDJSON). Kita harus menggabungkannya.
            full_text = ""
            image_url = ""
            
            for line in response.text.splitlines():
                if not line.strip(): continue
                try:
                    chunk = json.loads(line)
                    # Struktur data dari RPC Grok
                    res = chunk.get("result", {}).get("response", {})
                    
                    # Ambil token teks
                    if "token" in res:
                        full_text += res["token"]
                    
                    # Ambil gambar (biasanya di attachments atau imageURL)
                    if "attachments" in res:
                        for att in res["attachments"]:
                            if "url" in att: image_url = att["url"]
                            
                except: continue
            
            return {"text": full_text, "image_url": image_url}

        except Exception as e:
            log_event(f"      ❌ [CONNECTION ERROR] {e}")
            return None

grok = GrokClient()

# ==========================================
# 🏁 MAIN FLOW
# ==========================================
def main():
    os.makedirs(CONTENT_DIR, exist_ok=True)
    os.makedirs(IMAGE_DIR, exist_ok=True)
    log_event("🔥 JEEP ENGINE STARTED (API MODE) 🔥")

    feed = feedparser.parse("https://news.google.com/rss/search?q=Jeep+Wrangler&hl=en-US")
    if not feed.entries:
        log_event("❌ RSS Kosong.")
        return

    for entry in feed.entries[:1]:
        clean_title = entry.title.split(" - ")[0]
        slug = slugify(clean_title, max_length=50)
        file_path = f"{CONTENT_DIR}/{slug}.md"

        if os.path.exists(file_path):
            log_event(f"      ⏭️ [SKIP] {slug}")
            continue

        # 1. GENERATE ARTIKEL
        log_event(f"      📝 [CONTENT] Request API: {clean_title}")
        prompt = (
            f"Write a 1200-word SEO article about: {clean_title}. "
            f"Output must be VALID JSON with keys: 'seo_title', 'meta_desc', 'content_markdown', 'image_prompt'."
        )
        
        data = grok.generate(prompt)
        
        if not data or not data.get('text'):
            log_event("      ❌ [API GAGAL] Tidak ada respon teks. (Cek Cookie/Token)")
            continue

        try:
            # Bersihkan Markdown Code Block jika ada (```json ... ```)
            clean_json = re.sub(r'```json|```', '', data['text']).strip()
            article_data = json.loads(clean_json)
            
            # 2. GENERATE GAMBAR
            log_event("      🎨 [IMAGE] Request Gambar...")
            img_prompt = article_data.get('image_prompt', clean_title)
            img_res = grok.generate(f"{img_prompt}, cartoon vector art style", is_image=True)
            
            final_img_url = ""
            if img_res and img_res.get('image_url'):
                try:
                    # Download gambar menggunakan curl_cffi juga
                    img_bytes = requests.get(img_res['image_url'], impersonate="chrome120").content
                    img = Image.open(BytesIO(img_bytes)).convert("RGB")
                    draw = ImageDraw.Draw(img)
                    draw.text((20, 20), "@JeepDaily", fill=(255, 255, 255))
                    img.save(f"{IMAGE_DIR}/{slug}.webp", "WEBP")
                    final_img_url = f"/images/{slug}.webp"
                    log_event("      ✅ [IMAGE] Gambar Tersimpan.")
                except: pass

            # 3. SAVE FILE
            md_content = f"""---
title: "{article_data.get('seo_title', clean_title).replace('"', "'")}"
date: {datetime.now().strftime('%Y-%m-%dT%H:%M:%S+00:00')}
featured_image: "{final_img_url}"
description: "{article_data.get('meta_desc', '').replace('"', "'")}"
slug: "{slug}"
url: "/{slug}/"
---
{article_data.get('content_markdown', '')}
"""
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(md_content)
            
            log_event("      ✅ [FILE] Artikel Disimpan.")

            # 4. INDEXING (LOG MUNCUL DISINI)
            submit_indexing(slug)
            log_event(f"✅ DONE: {slug}")

        except Exception as e:
            log_event(f"      ❌ [PARSE ERROR] JSON Rusak: {e}")

if __name__ == "__main__":
    main()
