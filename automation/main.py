import os, json, time, re, random, sys
from datetime import datetime
from slugify import slugify
from io import BytesIO
from PIL import Image, ImageDraw
import feedparser
import pytz
from playwright.sync_api import sync_playwright
from playwright_stealth import stealth # Perbaikan import disini

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
# Ambil token pertama dari secret
GROK_SSO_TOKEN = os.environ.get("GROK_SSO_TOKENS", "").split(",")[0]
WEBSITE_URL = "https://dother.biz.id"
INDEXNOW_KEY = "e74819b68a0f40e98f6ec3dc24f610f0"
GOOGLE_JSON_KEY = os.environ.get("GOOGLE_INDEXING_KEY", "")
CONTENT_DIR = "content/articles"
IMAGE_DIR = "static/images"

# ==========================================
# 🚀 SUBMIT INDEXING (LOG UTAMA)
# ==========================================
def submit_indexing(slug):
    full_url = f"{WEBSITE_URL}/{slug}/"
    log_event(f"      📡 [INDEX LOG] Memulai Submit Indexing: {full_url}")
    
    # 1. IndexNow
    try:
        import requests
        host = "dother.biz.id"
        data = {"host": host, "key": INDEXNOW_KEY, "keyLocation": f"https://{host}/{INDEXNOW_KEY}.txt", "urlList": [full_url]}
        resp = requests.post("https://api.indexnow.org/indexnow", json=data, timeout=15)
        log_event(f"      🚀 [INDEX LOG] IndexNow Status: {resp.status_code}")
    except Exception as e:
        log_event(f"      ❌ [INDEX ERROR] IndexNow Gagal: {e}")

    # 2. Google Indexing
    if GOOGLE_JSON_KEY:
        try:
            from oauth2client.service_account import ServiceAccountCredentials
            from googleapiclient.discovery import build
            creds = ServiceAccountCredentials.from_json_keyfile_dict(json.loads(GOOGLE_JSON_KEY), ["https://www.googleapis.com/auth/indexing"])
            service = build("indexing", "v3", credentials=creds)
            service.urlNotifications().publish(body={"url": full_url, "type": "URL_UPDATED"}).execute()
            log_event(f"      🚀 [INDEX LOG] Google Index: Berhasil.")
        except Exception as e:
            log_event(f"      ❌ [INDEX ERROR] Google Gagal: {e}")

# ==========================================
# 🧠 PLAYWRIGHT ENGINE (STEALTH)
# ==========================================
def generate_with_playwright(prompt):
    result_data = None
    img_src = None
    
    with sync_playwright() as p:
        # Launch browser dengan argumen keamanan untuk GitHub Actions
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-setuid-sandbox"])
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        stealth(page) # Gunakan fungsi stealth yang sudah diperbaiki

        try:
            log_event("      🌐 Membuka Grok.com...")
            page.goto("https://grok.com/", timeout=60000)
            
            # Inject Token
            log_event("      🔑 Mengatur Session Token...")
            page.evaluate(f"window.localStorage.setItem('sso-token', '{GROK_SSO_TOKEN}')")
            page.reload()
            time.sleep(10)

            # Ketik Prompt
            log_event("      ⌨️ Mengirim Instruksi...")
            # Grok menggunakan div contenteditable atau textarea tergantung versi, kita coba keduanya
            if page.query_selector('textarea'):
                page.fill('textarea', prompt)
                page.press('textarea', 'Enter')
            else:
                page.keyboard.type(prompt)
                page.keyboard.press("Enter")

            # Tunggu respon (Grok butuh waktu untuk generate artikel panjang)
            log_event("      ⏳ Menunggu Grok berpikir (60 detik)...")
            time.sleep(60)

            # Ambil seluruh teks halaman
            page_content = page.content()
            
            # Cari JSON di dalam teks
            match = re.search(r'(\{.*\})', page.inner_text("body"), re.DOTALL)
            if match:
                try:
                    result_data = json.loads(match.group(1))
                    log_event("      ✅ Data Artikel berhasil didapat.")
                except:
                    log_event("      ❌ Gagal parsing JSON dari UI.")

            # Cari Gambar (Grok Image Generated)
            images = page.query_selector_all('img')
            for img in images:
                src = img.get_attribute('src')
                if src and ("generated" in src or "assets.grok.com" in src):
                    img_src = src
                    log_event("      🎨 Gambar Grok ditemukan.")
                    break

        except Exception as e:
            log_event(f"      ❌ Playwright Error: {e}")
        
        browser.close()
    return result_data, img_src

# ==========================================
# 🏁 MAIN
# ==========================================
def main():
    os.makedirs(CONTENT_DIR, exist_ok=True)
    os.makedirs(IMAGE_DIR, exist_ok=True)
    log_event("🔥 JEEP ENGINE STARTED (PLAYWRIGHT STEALTH) 🔥")

    # Ambil 1 berita dari RSS
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

        log_event(f"      📝 Memproses: {clean_title}")
        
        prompt = (
            f"Write a 1000-word SEO article about '{clean_title}'. "
            f"Return ONLY a JSON object with these keys: "
            f"'seo_title', 'meta_desc', 'content_markdown'."
        )
        
        data, img_src = generate_with_playwright(prompt)

        if not data:
            log_event("      ❌ Gagal generate konten. Melewati proses.")
            continue

        # Simpan Gambar
        img_url = ""
        if img_src:
            try:
                import requests
                img_data = requests.get(img_src).content
                img = Image.open(BytesIO(img_data)).convert("RGB")
                draw = ImageDraw.Draw(img)
                draw.text((20, 20), "@JeepDaily", fill=(255, 255, 255))
                img.save(f"{IMAGE_DIR}/{slug}.webp", "WEBP")
                img_url = f"/images/{slug}.webp"
            except: pass

        # Simpan Markdown
        md_content = f"""---
title: "{data.get('seo_title', clean_title).replace('"', "'")}"
date: {datetime.now().strftime('%Y-%m-%dT%H:%M:%S+00:00')}
featured_image: "{img_url}"
description: "{data.get('meta_desc', '').replace('"', "'")}"
slug: "{slug}"
---
{data.get('content_markdown', 'Error Content')}
"""
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(md_content)
        
        log_event(f"      ✅ File Berhasil Disimpan: {file_path}")

        # SUBMIT INDEXING (LOG WAJIB MUNCUL DISINI)
        submit_indexing(slug)
        log_event(f"✅ SUCCESS: {slug}")

if __name__ == "__main__":
    main()
