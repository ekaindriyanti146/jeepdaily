import os, json, time, re, random, sys
from datetime import datetime
from slugify import slugify
from io import BytesIO
from PIL import Image, ImageDraw
import feedparser
import pytz
from playwright.sync_api import sync_playwright

# --- FIX IMPORT STEALTH ---
try:
    # Coba import stealth_sync (versi terbaru)
    from playwright_stealth import stealth_sync as stealth_func
except (ImportError, AttributeError):
    try:
        # Coba import stealth (versi alternatif)
        from playwright_stealth import stealth as stealth_func
    except (ImportError, AttributeError):
        # Jika gagal semua, buat fungsi dummy agar script tidak crash
        def stealth_func(page): pass
        print("⚠️ Warning: Playwright Stealth function not found, running without it.")

# ==========================================
# 🚀 SYSTEM LOGGING
# ==========================================
def log_event(msg):
    # Menggunakan WITA/WIB (Asia/Jakarta) agar log mudah dibaca
    tz = pytz.timezone('Asia/Jakarta')
    timestamp = datetime.now(tz).strftime('%H:%M:%S')
    print(f"[{timestamp}] {msg}", flush=True)

# ==========================================
# ⚙️ CONFIGURATION
# ==========================================
GROK_SSO_TOKEN = os.environ.get("GROK_SSO_TOKENS", "").split(",")[0]
WEBSITE_URL = "https://dother.biz.id"
INDEXNOW_KEY = "e74819b68a0f40e98f6ec3dc24f610f0"
GOOGLE_JSON_KEY = os.environ.get("GOOGLE_INDEXING_KEY", "")
CONTENT_DIR = "content/articles"
IMAGE_DIR = "static/images"

# ==========================================
# 🚀 SUBMIT INDEXING (LOG UTAMA ANDA)
# ==========================================
def submit_indexing(slug):
    full_url = f"{WEBSITE_URL}/{slug}/"
    log_event(f"      📡 [INDEX LOG] Memulai Submit Indexing: {full_url}")
    
    # 1. IndexNow (Bing/Yandex)
    try:
        import requests
        host = "dother.biz.id"
        data = {
            "host": host, 
            "key": INDEXNOW_KEY, 
            "keyLocation": f"{WEBSITE_URL}/{INDEXNOW_KEY}.txt", 
            "urlList": [full_url]
        }
        resp = requests.post("https://api.indexnow.org/indexnow", json=data, timeout=15)
        log_event(f"      🚀 [INDEX LOG] IndexNow Status: {resp.status_code}")
    except Exception as e:
        log_event(f"      ❌ [INDEX ERROR] IndexNow Gagal: {e}")

    # 2. Google Indexing API
    if GOOGLE_JSON_KEY:
        try:
            from oauth2client.service_account import ServiceAccountCredentials
            from googleapiclient.discovery import build
            creds_dict = json.loads(GOOGLE_JSON_KEY)
            credentials = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, ["https://www.googleapis.com/auth/indexing"])
            service = build("indexing", "v3", credentials=credentials)
            service.urlNotifications().publish(body={"url": full_url, "type": "URL_UPDATED"}).execute()
            log_event(f"      🚀 [INDEX LOG] Google Index: Berhasil.")
        except Exception as e:
            log_event(f"      ❌ [INDEX ERROR] Google Gagal: {e}")

# ==========================================
# 🧠 PLAYWRIGHT ENGINE (STEALTH MODE)
# ==========================================
def generate_with_playwright(prompt):
    result_data = None
    img_src = None
    
    with sync_playwright() as p:
        # Launch browser khusus untuk GitHub Actions (Linux)
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-setuid-sandbox"])
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        
        # Jalankan stealth agar tidak terdeteksi bot Cloudflare
        if callable(stealth_func):
            try:
                stealth_func(page)
            except:
                pass

        try:
            log_event("      🌐 Membuka Grok.com...")
            page.goto("https://grok.com/", timeout=90000)
            
            # Inject Token ke LocalStorage
            log_event("      🔑 Mengatur Session...")
            page.evaluate(f"window.localStorage.setItem('sso-token', '{GROK_SSO_TOKEN}')")
            page.reload()
            time.sleep(15)

            # Ketik Prompt
            log_event("      ⌨️ Mengirim Instruksi ke AI...")
            # Grok kadang butuh waktu untuk merender input box
            page.wait_for_selector('textarea', timeout=30000)
            page.fill('textarea', prompt)
            page.press('textarea', 'Enter')

            # Tunggu respon artikel (Grok butuh waktu lama untuk artikel 1000 kata)
            log_event("      ⏳ Menunggu Grok generate artikel (70 detik)...")
            time.sleep(70)

            # Ekstrak konten body
            raw_text = page.inner_text("body")
            
            # Cari JSON di dalam hasil chat
            match = re.search(r'(\{.*\})', raw_text, re.DOTALL)
            if match:
                try:
                    result_data = json.loads(match.group(1))
                    log_event("      ✅ Data Artikel berhasil didapatkan.")
                except:
                    log_event("      ❌ Gagal memproses JSON dari browser.")
            else:
                log_event("      ❌ JSON tidak ditemukan di halaman.")

            # Cari Gambar yang di-generate Grok
            log_event("      🔎 Mencari URL Gambar...")
            images = page.query_selector_all('img')
            for img in images:
                src = img.get_attribute('src')
                if src and ("generated" in src or "assets.grok.com" in src):
                    img_src = src
                    log_event("      🎨 Gambar ditemukan!")
                    break

        except Exception as e:
            log_event(f"      ❌ Browser Error: {e}")
        
        browser.close()
    return result_data, img_src

# ==========================================
# 🏁 MAIN WORKFLOW
# ==========================================
def main():
    # Setup directory
    for d in [CONTENT_DIR, IMAGE_DIR]: os.makedirs(d, exist_ok=True)
    
    log_event("🔥 JEEP ENGINE STARTED (PLAYWRIGHT FIXED) 🔥")

    # Ambil RSS
    feed = feedparser.parse("https://news.google.com/rss/search?q=Jeep+Wrangler&hl=en-US")
    if not feed.entries:
        log_event("❌ RSS Gagal dimuat.")
        return

    for entry in feed.entries[:1]: # Batas 1 artikel agar GitHub Actions tidak timeout
        clean_title = entry.title.split(" - ")[0]
        slug = slugify(clean_title, max_length=50)
        file_path = f"{CONTENT_DIR}/{slug}.md"

        if os.path.exists(file_path):
            log_event(f"      ⏭️ [SKIP] {slug}")
            continue

        log_event(f"      📝 Memproses: {clean_title}")
        
        # PROMPT PREMIUM
        prompt = (
            f"Write a 1000-word SEO article about: {clean_title}. "
            f"Return ONLY a RAW JSON object. "
            f"Keys: 'seo_title', 'meta_desc', 'content_markdown'."
        )
        
        data, img_src = generate_with_playwright(prompt)

        # Hanya lanjut jika artikel berhasil didapat
        if not data or 'content_markdown' not in data:
            log_event("      ❌ Gagal mendapatkan konten. Skip ke tahap Indexing.")
            continue

        # Simpan Gambar jika ada
        img_url = ""
        if img_src:
            try:
                import requests
                img_data = requests.get(img_src).content
                img = Image.open(BytesIO(img_data)).convert("RGB")
                # Tambah Watermark
                draw = ImageDraw.Draw(img)
                draw.text((20, 20), "@JeepDaily", fill=(255, 255, 255))
                img.save(f"{IMAGE_DIR}/{slug}.webp", "WEBP")
                img_url = f"/images/{slug}.webp"
                log_event("      ✅ Gambar Berhasil Disimpan.")
            except Exception as e:
                log_event(f"      ⚠️ Gagal simpan gambar: {e}")

        # Simpan Artikel Markdown
        md_content = f"""---
title: "{data.get('seo_title', clean_title).replace('"', "'")}"
date: {datetime.now().strftime('%Y-%m-%dT%H:%M:%S+00:00')}
featured_image: "{img_url}"
description: "{data.get('meta_desc', '').replace('"', "'")}"
slug: "{slug}"
url: "/{slug}/"
---
{data.get('content_markdown', 'Error loading content')}
"""
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(md_content)
        
        log_event(f"      ✅ File Markdown Berhasil Dibuat: {file_path}")

        # --- SUBMIT INDEXING (LOG MUNCUL DI SINI) ---
        submit_indexing(slug)
        log_event(f"✅ PROSES SELESAI UNTUK: {slug}")

if __name__ == "__main__":
    main()
