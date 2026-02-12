import os, json, time, re, random, sys, socket
from datetime import datetime
from slugify import slugify
from io import BytesIO
from PIL import Image, ImageDraw
import feedparser

# GUNAKAN curl_cffi UNTUK MENIRU BROWSER (IMPERSONATE)
# Ini adalah teknik dari file videos.py yang Anda kirim
from curl_cffi import requests

# ==========================================
# 🚀 SYSTEM LOGGING
# ==========================================
def log_event(msg):
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
# 🔄 GROK STEALTH ENGINE (CURL_CFFI MODE)
# ==========================================
class GrokStealth:
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
        
        # Headers hasil observasi dari file config.py & videos.py
        # Menambahkan impersonasi Chrome 110-133
        headers = {
            "Authorization": f"Bearer {token}",
            "x-sso-token": token,
            "Content-Type": "application/json",
            "Origin": "https://grok.com",
            "Referer": "https://grok.com/",
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
        }
        
        payload = {
            "modelName": "grok-latest",
            "message": prompt,
            "fileAttachments": [],
            "intent": "IMAGE_GEN" if is_image else "UNKNOWN"
        }

        try:
            # IMPERSONATE CHROME (Kunci utama tembus 403)
            with requests.Session() as s:
                response = s.post(
                    url, 
                    headers=headers, 
                    json=payload, 
                    timeout=120,
                    impersonate="chrome110" # <--- INI TEKNIK DARI FILE ANDA
                )
                
                if response.status_code == 403:
                    log_event(f"      ❌ [STEALTH ERROR] Status 403: Cloudflare mendeteksi IP GitHub Actions.")
                    return None
                
                if response.status_code != 200:
                    log_event(f"      ❌ [STEALTH ERROR] Status {response.status_code}")
                    return None

                full_text = ""
                image_url = ""
                # Parsing NDJSON
                for line in response.text.splitlines():
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
            log_event(f"      ❌ [STEALTH ERROR] {e}")
            return None

grok = GrokStealth(GROK_SSO_TOKENS)

# ==========================================
# 🚀 SUBMIT INDEXING (LOG PASTI MUNCUL)
# ==========================================
def submit_indexing(slug):
    full_url = f"{WEBSITE_URL}/{slug}/"
    log_event(f"      📡 [INDEX LOG] Memulai Submit Indexing: {full_url}")
    
    # 1. IndexNow
    try:
        host = WEBSITE_URL.replace("https://", "").replace("http://", "")
        data = {"host": host, "key": INDEXNOW_KEY, "keyLocation": f"{WEBSITE_URL}/{INDEXNOW_KEY}.txt", "urlList": [full_url]}
        r = requests.post("https://api.indexnow.org/indexnow", json=data, timeout=10, impersonate="chrome110")
        log_event(f"      🚀 [INDEX LOG] IndexNow Status: {r.status_code}")
    except: log_event("      ❌ [INDEX LOG] IndexNow Gagal.")

    # 2. Google Indexing
    if GOOGLE_JSON_KEY:
        try:
            from oauth2client.service_account import ServiceAccountCredentials
            from googleapiclient.discovery import build
            creds = ServiceAccountCredentials.from_json_keyfile_dict(json.loads(GOOGLE_JSON_KEY), ["https://www.googleapis.com/auth/indexing"])
            service = build("indexing", "v3", credentials=creds)
            service.urlNotifications().publish(body={"url": full_url, "type": "URL_UPDATED"}).execute()
            log_event(f"      🚀 [INDEX LOG] Google Index: Berhasil.")
        except Exception as e: log_event(f"      ❌ [INDEX LOG] Google Error: {e}")

# ==========================================
# 🏁 MAIN WORKFLOW
# ==========================================
def main():
    for d in [CONTENT_DIR, IMAGE_DIR]: os.makedirs(d, exist_ok=True)
    log_event(f"🔥 JEEP ENGINE STARTED | TOKENS: {len(GROK_SSO_TOKENS)}")

    for cat, rss_url in RSS_SOURCES.items():
        log_event(f"\n📡 SUMBER: {cat}")
        feed = feedparser.parse(rss_url)
        if not feed or not feed.entries: continue

        for entry in feed.entries[:1]:
            clean_title = entry.title.split(" - ")[0]
            slug = slugify(clean_title, max_length=50)
            file_path = f"{CONTENT_DIR}/{slug}.md"

            if os.path.exists(file_path):
                log_event(f"      ⏭️ [SKIP] Sudah ada: {slug}")
                continue

            # 1. Teks Artikel
            log_event(f"      📝 [CONTENT] Menulis Artikel: {clean_title}")
            res = grok.call(f"Write a 1000-word SEO article in JSON: {clean_title}. Keys: seo_title, content_markdown, image_prompt.")
            
            if not res or not res.get('text'):
                log_event("      ❌ [CONTENT ERROR] Grok Gagal Tembus Cloudflare.")
                continue

            try:
                data = json.loads(re.search(r'(\{.*\})', res['text'], re.DOTALL).group(1))
            except: 
                log_event("      ❌ [CONTENT ERROR] JSON Gagal Diambil.")
                continue

            # 2. Gambar
            log_event(f"      🎨 [IMAGE] Generate Gambar...")
            img_res = grok.call(data.get('image_prompt', clean_title), is_image=True)
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
                except: log_event("      ❌ [IMAGE LOG] Gagal.")

            # 3. Simpan File
            md_body = f"---\ntitle: \"{data.get('seo_title', clean_title)}\"\ndate: {datetime.now().isoformat()}\nfeatured_image: \"{img_path}\"\nslug: \"{slug}\"\nurl: \"/{slug}/\"\n---\n{data.get('content_markdown', 'Error')}"
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(md_body)
            
            # 4. SUBMIT INDEXING (LOG PASTI MUNCUL)
            submit_indexing(slug)
            log_event(f"      ✅ [SUCCESS] ARTIKEL SELESAI: {slug}")
            time.sleep(10)

if __name__ == "__main__":
    main()
