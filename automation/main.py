import os, json, requests, feedparser, time, re, random, sys, socket
from urllib.parse import quote
from datetime import datetime
from slugify import slugify
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont

# ==========================================
# ⚙️ CONFIGURATION & SECRETS
# ==========================================
# Ambil dari GitHub Secrets
GROK_KEYS_RAW = os.environ.get("GROK_SSO_TOKENS", "") 
GROK_SSO_TOKENS = [k.strip() for k in GROK_KEYS_RAW.split(",") if k.strip()]
GROK_COOKIES = os.environ.get("GROK_COOKIES", "") # String panjang dari browser

WEBSITE_URL = "https://dother.biz.id" 
INDEXNOW_KEY = "e74819b68a0f40e98f6ec3dc24f610f0" 
GOOGLE_JSON_KEY = os.environ.get("GOOGLE_INDEXING_KEY", "") 

CONTENT_DIR = "content/articles" 
IMAGE_DIR = "static/images"
DATA_DIR = "automation/data"

# Niche RSS Sources
RSS_SOURCES = {
    "Wrangler Life": "https://news.google.com/rss/search?q=Jeep+Wrangler+Review&hl=en-US",
    "Off-road Tips": "https://news.google.com/rss/search?q=Jeep+Offroad+Tips&hl=en-US",
    "Jeep Mods": "https://news.google.com/rss/search?q=Jeep+Modifications&hl=en-US"
}

# Fungsi log agar langsung muncul di GitHub
def log_print(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

# ==========================================
# 🔄 GROK ENGINE (STEALTH MODE)
# ==========================================
class GrokEngine:
    def __init__(self, tokens):
        self.tokens = tokens
        self.current_idx = 0

    def call_grok(self, prompt, is_image=False):
        if not self.tokens: return None
        token = self.tokens[self.current_idx]
        self.current_idx = (self.current_idx + 1) % len(self.tokens)
        
        # Endpoint fleksibel (mencoba rpc atau completions)
        url = "https://grok.com/api/rpc/chat/completion"
        headers = {
            "Authorization": f"Bearer {token}",
            "Cookie": GROK_COOKIES, # Kunci utama tembus 403
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0",
        }
        payload = {"modelName": "grok-latest", "message": prompt, "intent": "IMAGE_GEN" if is_image else "UNKNOWN"}

        try:
            response = requests.post(url, headers=headers, json=payload, timeout=120)
            if response.status_code != 200:
                log_print(f"      ❌ [GROK ERROR] Status: {response.status_code}. Periksa Cookie/Token!")
                return None
            
            # Gabungkan respon streaming
            full_text = ""
            img_url = ""
            for line in response.text.splitlines():
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
            log_print(f"      ❌ [GROK ERROR] {e}")
            return None

grok = GrokEngine(GROK_SSO_TOKENS)

# ==========================================
# 🚀 SUBMIT INDEXING (LOG WAJIB MUNCUL)
# ==========================================
def run_indexing(slug):
    full_url = f"{WEBSITE_URL}/{slug}/"
    log_print(f"      📡 [INDEX LOG] Memulai Submit Indexing: {full_url}")
    
    # 1. IndexNow (Bing/Yandex)
    try:
        host = WEBSITE_URL.replace("https://", "").replace("http://", "")
        payload = {"host": host, "key": INDEXNOW_KEY, "keyLocation": f"{WEBSITE_URL}/{INDEXNOW_KEY}.txt", "urlList": [full_url]}
        r = requests.post("https://api.indexnow.org/indexnow", json=payload, timeout=10)
        log_print(f"      🚀 [INDEX LOG] IndexNow Status: {r.status_code}")
    except: log_print("      ❌ [INDEX LOG] IndexNow Gagal.")

    # 2. Google Indexing
    if GOOGLE_JSON_KEY:
        try:
            from oauth2client.service_account import ServiceAccountCredentials
            from googleapiclient.discovery import build
            creds = ServiceAccountCredentials.from_json_keyfile_dict(json.loads(GOOGLE_JSON_KEY), ["https://www.googleapis.com/auth/indexing"])
            service = build("indexing", "v3", credentials=creds)
            service.urlNotifications().publish(body={"url": full_url, "type": "URL_UPDATED"}).execute()
            log_print(f"      🚀 [INDEX LOG] Google Index: Berhasil Terkirim.")
        except Exception as e: log_print(f"      ❌ [INDEX LOG] Google Error: {e}")

# ==========================================
# 🏁 MAIN WORKFLOW
# ==========================================
def main():
    for d in [CONTENT_DIR, IMAGE_DIR, DATA_DIR]: os.makedirs(d, exist_ok=True)
    log_print(f"🔥 JEEP ENGINE STARTED | TOKENS: {len(GROK_SSO_TOKENS)} 🔥")

    for cat, rss_url in RSS_SOURCES.items():
        log_print(f"\n📡 SUMBER: {cat}")
        feed = feedparser.parse(rss_url)
        if not feed or not feed.entries: continue

        for entry in feed.entries[:1]:
            clean_title = entry.title.split(" - ")[0]
            slug = slugify(clean_title, max_length=50)
            file_path = f"{CONTENT_DIR}/{slug}.md"

            if os.path.exists(file_path):
                log_print(f"      ⏭️ [SKIP] Sudah ada: {slug}")
                continue

            # 1. Teks Artikel
            log_print(f"      📝 [CONTENT] Menulis: {clean_title}")
            res = grok.call_grok(f"Write a 1000-word SEO article in JSON: {clean_title}. Keys: seo_title, meta_desc, content, schema_json, image_prompt.")
            
            if not res or not res.get('text'):
                log_print("      ❌ [CONTENT ERROR] Grok Gagal. Periksa Log Network di browser.")
                continue

            try:
                # Cari JSON di tengah teks
                data = json.loads(re.search(r'(\{.*\})', res['text'], re.DOTALL).group(1))
            except: 
                log_print("      ❌ [CONTENT ERROR] JSON Gagal di-ekstrak.")
                continue

            # 2. Gambar
            log_print(f"      🎨 [IMAGE] Generate Gambar...")
            img_res = grok.call_grok(data.get('image_prompt', clean_title), is_image=True)
            img_path = ""
            if img_res and img_res.get('image_url'):
                try:
                    img_data = requests.get(img_res['image_url']).content
                    img = Image.open(BytesIO(img_data)).convert("RGB")
                    # Watermark
                    draw = ImageDraw.Draw(img)
                    draw.text((20, 20), "@JeepDaily", fill=(255, 255, 255))
                    img.save(f"{IMAGE_DIR}/{slug}.webp", "WEBP")
                    img_path = f"/images/{slug}.webp"
                    log_print(f"      ✅ [IMAGE LOG] Gambar Disimpan.")
                except: log_print("      ❌ [IMAGE LOG] Gagal Simpan.")

            # 3. Simpan File
            schema = f'<script type="application/ld+json">{json.dumps(data.get("schema_json", {}))}</script>'
            md_body = f"---\ntitle: \"{data.get('seo_title', clean_title)}\"\ndate: {datetime.now().strftime('%Y-%m-%dT%H:%M:%S+00:00')}\nfeatured_image: \"{img_path}\"\nslug: \"{slug}\"\nurl: \"/{slug}/\"\n---\n{schema}\n{data.get('content', 'Content Error')}"
            
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(md_body)
            
            # 4. SUBMIT INDEXING (LOG PASTI MUNCUL)
            run_indexing(slug)
            log_print(f"      ✅ [SUCCESS] ARTIKEL SELESAI: {slug}")
            time.sleep(10)

if __name__ == "__main__":
    main()
