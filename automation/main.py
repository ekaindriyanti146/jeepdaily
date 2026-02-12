import os
import json
import requests
import feedparser
import time
import re
import random
import warnings 
from urllib.parse import quote
from datetime import datetime
from slugify import slugify
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont

# --- GOOGLE INDEXING LIBS ---
try:
    from oauth2client.service_account import ServiceAccountCredentials
    from googleapiclient.discovery import build
    GOOGLE_LIBS_AVAILABLE = True
except ImportError:
    GOOGLE_LIBS_AVAILABLE = False

# ==========================================
# ⚙️ CONFIGURATION
# ==========================================
GROK_SSO_TOKENS = ["TOKEN_1", "TOKEN_2"] # Tambahkan token Anda
WEBSITE_URL = "https://dother.biz.id" 
INDEXNOW_KEY = "e74819b68a0f40e98f6ec3dc24f610f0"
GOOGLE_JSON_KEY = os.environ.get("GOOGLE_INDEXING_KEY", "") 

CONTENT_DIR = "content/articles" 
IMAGE_DIR = "static/images"
DATA_DIR = "automation/data"
MEMORY_FILE = f"{DATA_DIR}/link_memory.json"

# ==========================================
# 📡 MULTI-SOURCE RSS (Expanded)
# ==========================================
RSS_SOURCES = {
    "Wrangler News": "https://news.google.com/rss/search?q=Jeep+Wrangler+Review+News&hl=en-US&gl=US&ceid=US:en",
    "Maintenance Tips": "https://news.google.com/rss/search?q=Jeep+Wrangler+Maintenance+How+to&hl=en-US&gl=US&ceid=US:en",
    "Offroad Adventure": "https://news.google.com/rss/search?q=Jeep+Offroad+Trail+Guide&hl=en-US&gl=US&ceid=US:en",
    "Jeep Modifications": "https://news.google.com/rss/search?q=Jeep+Wrangler+Aftermarket+Parts&hl=en-US&gl=US&ceid=US:en",
    "Classic Jeeps": "https://news.google.com/rss/search?q=Classic+Jeep+Willys+History&hl=en-US&gl=US&ceid=US:en"
}

# ==========================================
# 🧠 GROK ENGINE
# ==========================================
class GrokEngine:
    def __init__(self, tokens):
        self.tokens = tokens
        self.current_idx = 0

    def get_token(self):
        token = self.tokens[self.current_idx]
        self.current_idx = (self.current_idx + 1) % len(self.tokens)
        return token

    def call_rpc(self, prompt, is_image=False):
        token = self.get_token()
        url = "https://grok.com/api/rpc/chat/completion"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Origin": "https://grok.com",
            "Referer": "https://grok.com/"
        }
        payload = {
            "modelName": "grok-latest",
            "message": prompt,
            "intent": "IMAGE_GEN" if is_image else "UNKNOWN"
        }
        try:
            response = requests.post(url, headers=headers, json=payload, stream=True, timeout=120)
            full_text, image_url = "", ""
            for line in response.iter_lines():
                if not line: continue
                try:
                    chunk = json.loads(line.decode('utf-8'))
                    res = chunk.get("result", {}).get("response", {})
                    if "token" in res: full_text += res["token"]
                    if "attachments" in res:
                        for att in res["attachments"]:
                            if att.get("type") == "image": image_url = att.get("url")
                except: continue
            return {"text": full_text, "image_url": image_url}
        except: return None

grok = GrokEngine(GROK_SSO_TOKENS)

# ==========================================
# 🔗 INTERNAL LINKING MEMORY
# ==========================================
def load_memory():
    if os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, 'r') as f: return json.load(f)
    return {}

def save_memory(title, slug):
    mem = load_memory()
    mem[title] = f"/{slug}/"
    if len(mem) > 200: mem = dict(list(mem.items())[-200:])
    with open(MEMORY_FILE, 'w') as f: json.dump(mem, f)

def get_internal_links():
    mem = load_memory()
    if not mem: return ""
    samples = random.sample(list(mem.items()), min(len(mem), 3))
    links = "\n".join([f"- [Read More: {t}]({u})" for t, u in samples])
    return f"\n\n### Related Articles\n{links}"

# ==========================================
# 📝 PREMIUM CONTENT PROMPT (AdSense Ready)
# ==========================================
def generate_premium_content(title, summary, source_url):
    author = random.choice(["Rick O'Connell", "Sarah Miller", "Mike Stevens"])
    
    prompt = f"""
    You are an Automotive Engineer and SEO Content Strategist.
    Topic: {title}
    Context: {summary}
    Source: {source_url}

    TASKS:
    1. Content Length: 1200+ words.
    2. Hierarchy: Proper H2, H3, and H4 tags.
    3. Entities: Include specific technical terms (e.g., 'Dana 44 Axles', 'Pentastar V6', 'Mopar', 'Rock-Trac').
    4. External Link: Mention and link to a high-authority site (e.g., Jeep.com or CarAndDriver.com) naturally.
    5. Schema: Generate a JSON-LD Article Schema.
    6. Unique Value: Add a "Pro-Tip" section and a technical comparison table.

    RETURN RAW JSON ONLY:
    {{
      "seo_title": "...",
      "meta_desc": "...",
      "category": "...",
      "content_body": "Markdown here...",
      "schema_json": {{ "context": "https://schema.org", "type": "Article", ... }},
      "image_prompt": "Vector cartoon GTA style Jeep {title}..."
    }}
    """
    
    res = grok.call_rpc(prompt)
    try:
        clean_json = re.sub(r'```json|```', '', res['text']).strip()
        return json.loads(clean_json), author
    except: return None, None

# ==========================================
# 🏁 MAIN ENGINE
# ==========================================
def main():
    os.makedirs(CONTENT_DIR, exist_ok=True)
    os.makedirs(IMAGE_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)

    print("🔥 JEEP MULTI-SOURCE ENGINE STARTED 🔥")

    for source_name, rss_url in RSS_SOURCES.items():
        print(f"📡 Source: {source_name}")
        feed = feedparser.parse(rss_url)
        
        for entry in feed.entries[:1]: # 1 Artikel per kategori per run
            clean_title = entry.title.split(" - ")[0]
            slug = slugify(clean_title, max_length=50)
            
            if os.path.exists(f"{CONTENT_DIR}/{slug}.md"): continue

            # 1. Generate Content
            data, author = generate_premium_content(clean_title, entry.summary, entry.link)
            if not data: continue

            # 2. Generate Image
            image_fn = f"{slug}.webp"
            img_path = ""
            res_img = grok.call_rpc(data['image_prompt'] + ", cartoon gta style, 2d vector", is_image=True)
            if res_img and res_img['image_url']:
                try:
                    img_data = requests.get(res_img['image_url']).content
                    img = Image.open(BytesIO(img_data)).convert("RGB")
                    draw = ImageDraw.Draw(img)
                    draw.text((10, 10), "@JeepDaily", fill=(255,255,255))
                    img.save(f"{IMAGE_DIR}/{image_fn}", "WEBP")
                    img_path = f"/images/{image_fn}"
                except: pass

            # 3. Assemble Internal Links & Schema
            internal_links = get_internal_links()
            schema_script = f"<script type=\"application/ld+json\">\n{json.dumps(data['schema_json'])}\n</script>"

            # 4. Save Markdown
            md_content = f"""---
title: "{data['seo_title'].replace('"', "'")}"
date: {datetime.now().strftime("%Y-%m-%dT%H:%M:%S+00:00")}
author: "{author}"
categories: ["{data['category']}"]
featured_image: "{img_path}"
description: "{data['meta_desc'].replace('"', "'")}"
slug: "{slug}"
url: "/{slug}/"
---

{schema_script}

{data['content_body']}

{internal_links}

---
*Disclaimer: Original reporting from [{source_name}]({entry.link}). Analysis and technical insights by {author}.*
"""
            with open(f"{CONTENT_DIR}/{slug}.md", "w") as f:
                f.write(md_content)

            save_memory(data['seo_title'], slug)
            
            # 5. Indexing
            full_url = f"{WEBSITE_URL}/{slug}/"
            # (Panggil fungsi submit_to_google & submit_to_indexnow di sini)
            print(f"✅ Published: {slug}")
            time.sleep(20)

if __name__ == "__main__":
    main()
