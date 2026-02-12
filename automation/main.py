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
    from playwright_stealth import stealth_sync as stealth_func
except:
    try:
        from playwright_stealth import stealth as stealth_func
    except:
        def stealth_func(page): pass

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
    
    # 1. IndexNow
    try:
        import requests
        host = "dother.biz.id"
        data = {"host": host, "key": INDEXNOW_KEY, "keyLocation": f"{WEBSITE_URL}/{INDEXNOW_KEY}.txt", "urlList": [full_url]}
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
# 🧠 PLAYWRIGHT ENGINE (ULTRA STEALTH)
# ==========================================
def generate_with_playwright(prompt):
    result_data = None
    img_src = None
    
    with sync_playwright() as p:
        # Gunakan Chrome asli jika memungkinkan, atau Chromium dengan flag stealth
        browser = p.chromium.launch(headless=True, args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-setuid-sandbox"
        ])
        
        context = browser.new_context(
            viewport={'width': 1280, 'height': 720},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        
        page = context.new_page()
        if callable(stealth_func):
            stealth_func(page)

        try:
            log_event("      🌐 Membuka Grok.com...")
            # Kita tidak menunggu networkidle, tapi cukup domcontentloaded
            page.goto("https://grok.com/", wait_until="domcontentloaded", timeout=60000)
            
            log_event("      🔑 Mengatur Session...")
            page.evaluate(f"window.localStorage.setItem('sso-token', '{GROK_SSO_TOKEN}')")
            page.goto("https://grok.com/", wait_until="domcontentloaded", timeout=60000)
            
            # Cek apakah ada Cloudflare Turnstile
            time.sleep(10)
            if "Verify you are human" in page.content():
                log_event("      ⚠️ Cloudflare Turnstile terdeteksi. Mencoba menunggu...")
                time.sleep(15)

            log_event("      ⌨️ Mencari Kotak Input...")
            # Grok sering menggunakan div dengan class ProseMirror atau role textbox
            selectors = ['div[contenteditable="true"]', '[role="textbox"]', 'textarea', '.ProseMirror']
            
            input_found = False
            for selector in selectors:
                try:
                    if page.is_visible(selector):
                        page.click(selector)
                        page.fill(selector, prompt)
                        page.keyboard.press("Enter")
                        input_found = True
                        log_event(f"      ✅ Berhasil mengirim prompt via {selector}")
                        break
                except: continue
            
            if not input_found:
                log_event("      ⚠️ Selector gagal. Mencoba mengetik langsung...")
                page.mouse.click(640, 650) # Klik area bawah layar (input chat)
                page.keyboard.type(prompt)
                page.keyboard.press("Enter")

            log_event("      ⏳ Menunggu AI memproses (90 detik)...")
            # Menunggu teks hasil generate muncul
            time.sleep(90)

            # Ekstrak Teks
            body_text = page.inner_text("body")
            match = re.search(r'(\{.*\})', body_text, re.DOTALL)
            if match:
                try:
                    result_data = json.loads(match.group(1))
                    log_event("      ✅ JSON Konten Berhasil Diekstrak.")
                except: log_event("      ❌ Gagal parse JSON.")

            # Ekstrak Gambar
            images = page.query_selector_all('img')
            for img in images:
                src = img.get_attribute('src')
                if src and ("generated" in src or "assets.grok.com" in src):
                    img_src = src
                    log_event("      🎨 Gambar Berhasil Ditemukan.")
                    break

        except Exception as e:
            log_event(f"      ❌ Playwright Error: {e}")
        
        browser.close()
    return result_data, img_src

# ==========================================
# 🏁 MAIN WORKFLOW
# ==========================================
def main():
    for d in [CONTENT_DIR, IMAGE_DIR]: os.makedirs(d, exist_ok=True)
    log_event("🔥 JEEP ENGINE STARTED (ANTI-TIMEOUT MODE) 🔥")

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
            f"Act as an auto journalist. Write a 1000-word SEO article about: {clean_title}. "
            f"Use H2, H3. Respond ONLY with a valid JSON: "
            f"{{\"seo_title\": \"...\", \"meta_desc\": \"...\", \"content_markdown\": \"...\"}}"
        )
        
        data, img_src = generate_with_playwright(prompt)

        if not data or 'content_markdown' not in data:
            log_event("      ❌ Konten gagal dibuat. Mengakhiri sesi.")
            continue

        # Simpan Gambar
        img_url = ""
        if img_src:
            try:
                import requests
                resp = requests.get(img_src, timeout=20)
                img = Image.open(BytesIO(resp.content)).convert("RGB")
                draw = ImageDraw.Draw(img)
                draw.text((20, 20), "@JeepDaily", fill=(255, 255, 255))
                img.save(f"{IMAGE_DIR}/{slug}.webp", "WEBP")
                img_url = f"/images/{slug}.webp"
                log_event("      ✅ Gambar disimpan.")
            except: pass

        # Simpan Markdown
        md_content = f"""---
title: "{data.get('seo_title', clean_title).replace('"', "'")}"
date: {datetime.now().strftime('%Y-%m-%dT%H:%M:%S+00:00')}
featured_image: "{img_url}"
description: "{data.get('meta_desc', '').replace('"', "'")}"
slug: "{slug}"
url: "/{slug}/"
---
{data.get('content_markdown', '')}
"""
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(md_content)
        
        log_event("      ✅ Artikel Berhasil Ditulis.")

        # --- SUBMIT INDEXING (LOG WAJIB MUNCUL DISINI) ---
        submit_indexing(slug)
        log_event(f"✅ SUCCESS PUBLISH: {slug}")

if __name__ == "__main__":
    main()
