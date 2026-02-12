import os, json, time, re, random, sys
from datetime import datetime
from slugify import slugify
from io import BytesIO
from PIL import Image, ImageDraw
import feedparser
from playwright.sync_api import sync_playwright
from playwright_stealth import stealth_sync

# ==========================================
# 🚀 SYSTEM LOGGING
# ==========================================
def log_event(msg):
    timestamp = datetime.now().strftime('%H:%M:%S')
    print(f"[{timestamp}] {msg}", flush=True)

# ==========================================
# ⚙️ CONFIGURATION
# ==========================================
GROK_SSO_TOKEN = os.environ.get("GROK_SSO_TOKENS", "").split(",")[0] # Ambil 1 token utama
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
    log_event(f"      📡 [INDEXING] Memulai proses submit untuk: {full_url}")
    
    # 1. IndexNow
    try:
        import requests
        host = "dother.biz.id"
        data = {"host": host, "key": INDEXNOW_KEY, "keyLocation": f"{WEBSITE_URL}/{INDEXNOW_KEY}.txt", "urlList": [full_url]}
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
# 🧠 PLAYWRIGHT ENGINE (BYPASS CLOUDFLARE)
# ==========================================
def generate_with_playwright(prompt):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True) # Headless=True untuk GitHub Actions
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        stealth_sync(page) # Menghapus sidik jari bot

        # 1. Buka Grok & Set Token
        log_event("      🌐 Membuka Grok.com...")
        page.goto("https://grok.com/")
        
        # Masukkan token ke LocalStorage (cara Grok menyimpan session)
        page.evaluate(f"window.localStorage.setItem('sso-token', '{GROK_SSO_TOKEN}')")
        page.reload()
        time.sleep(5)

        # 2. Ketik Prompt
        log_event("      ⌨️ Mengetik prompt ke Grok...")
        page.fill('textarea', prompt)
        page.press('textarea', 'Enter')

        # 3. Tunggu respon selesai (biasanya ditandai tombol 'stop' hilang atau teks berhenti mengalir)
        log_event("      ⏳ Menunggu Grok menulis (biasanya 30-60 detik)...")
        time.sleep(45) 

        # 4. Ambil Konten
        content = page.inner_text('body') # Mengambil seluruh teks halaman
        
        # Cari pola JSON dalam halaman
        match = re.search(r'(\{.*\})', content, re.DOTALL)
        result = None
        if match:
            try:
                result = json.loads(match.group(1))
                log_event("      ✅ Konten JSON berhasil diambil.")
            except:
                log_event("      ❌ Gagal parse JSON dari teks browser.")
        
        # 5. Cari Image URL (Grok Image Tag)
        image_url = ""
        images = page.query_selector_all('img')
        for img in images:
            src = img.get_attribute('src')
            if "generated" in src or "assets.grok.com" in src:
                image_url = src
                log_event(f"      🎨 Gambar ditemukan: {image_url[:50]}...")
                break

        browser.close()
        return result, image_url

# ==========================================
# 🏁 MAIN WORKFLOW
# ==========================================
def main():
    os.makedirs(CONTENT_DIR, exist_ok=True)
    os.makedirs(IMAGE_DIR, exist_ok=True)
    log_event("🔥 JEEP ENGINE STARTED (PLAYWRIGHT MODE) 🔥")

    # RSS Logic
    feed = feedparser.parse("https://news.google.com/rss/search?q=Jeep+Wrangler&hl=en-US")
    
    for entry in feed.entries[:1]: # 1 Artikel per run
        clean_title = entry.title.split(" - ")[0]
        slug = slugify(clean_title, max_length=50)
        file_path = f"{CONTENT_DIR}/{slug}.md"

        if os.path.exists(file_path):
            log_event(f"      ⏭️ [SKIP] {slug} sudah ada.")
            continue

        log_event(f"      📝 Memproses: {clean_title}")
        
        # GENERATE PAKAI BROWSER ASLI
        prompt = f"Write a 1000-word SEO article in JSON format about: {clean_title}. Keys: seo_title, meta_desc, content_markdown."
        data, img_src = generate_with_playwright(prompt)

        if not data:
            log_event("      ❌ Grok Gagal. Cloudflare Turnstile mungkin muncul.")
            continue

        # DOWNLOAD GAMBAR
        img_path = ""
        if img_src:
            try:
                import requests
                img_data = requests.get(img_src).content
                img = Image.open(BytesIO(img_data)).convert("RGB")
                draw = ImageDraw.Draw(img)
                draw.text((10, 10), "@JeepDaily", fill=(255, 255, 255))
                img.save(f"{IMAGE_DIR}/{slug}.webp", "WEBP")
                img_path = f"/images/{slug}.webp"
                log_event("      ✅ Gambar disimpan.")
            except: pass

        # SAVE MARKDOWN
        md_content = f"""---
title: "{data.get('seo_title', clean_title)}"
date: {datetime.now().strftime('%Y-%m-%dT%H:%M:%S+00:00')}
featured_image: "{img_path}"
description: "{data.get('meta_desc', '')}"
slug: "{slug}"
---
{data.get('content_markdown', 'Error')}
"""
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(md_content)
        
        # SUBMIT INDEXING (LOG PASTI MUNCUL)
        submit_indexing(slug)
        log_event(f"✅ SUCCESS: {slug}")

if __name__ == "__main__":
    main()
