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
# ⚙️ CONFIGURATION & SSO TOKENS
# ==========================================

# DAFTAR TOKEN SSO GROK ANDA (Bisa banyak untuk rotasi)
GROK_SSO_TOKENS = [
    "ISI_TOKEN_1_ANDA",
    "ISI_TOKEN_2_ANDA",
    "ISI_TOKEN_3_ANDA"
]

WEBSITE_URL = "https://dother.biz.id" 
INDEXNOW_KEY = "e74819b68a0f40e98f6ec3dc24f610f0" 
GOOGLE_JSON_KEY = os.environ.get("GOOGLE_INDEXING_KEY", "") 

CONTENT_DIR = "content/articles" 
IMAGE_DIR = "static/images"
DATA_DIR = "automation/data"
MEMORY_FILE = f"{DATA_DIR}/link_memory.json"

# ==========================================
# 🔄 GROK SSO ENGINE (TOKEN ROTATOR)
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
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Origin": "https://grok.com",
            "Referer": "https://grok.com/"
        }

        payload = {
            "modelName": "grok-latest",
            "message": prompt,
            "fileAttachments": [],
            "intent": "IMAGE_GEN" if is_image else "UNKNOWN"
        }

        try:
            response = requests.post(url, headers=headers, json=payload, stream=True, timeout=90)
            full_text = ""
            image_url = ""

            for line in response.iter_lines():
                if not line: continue
                try:
                    chunk = json.loads(line.decode('utf-8'))
                    res = chunk.get("result", {}).get("response", {})
                    
                    if "token" in res:
                        full_text += res["token"]
                    
                    if "attachments" in res:
                        for att in res["attachments"]:
                            if att.get("type") == "image":
                                image_url = att.get("url")
                except: continue
            
            return {"text": full_text, "image_url": image_url}
        except Exception as e:
            print(f"      ❌ Grok API Error: {e}")
            return None

grok = GrokEngine(GROK_SSO_TOKENS)

# ==========================================
# 📝 SEO CONTENT GENERATOR (H2, H3, H4)
# ==========================================

def generate_article(title, summary, author):
    system_prompt = f"""
    You are {author}, a Senior Automotive SEO Expert. 
    Write a deep-dive, professional article about: "{title}" based on context: {summary}.

    STRICT STRUCTURE RULES:
    1. Use H2 for main sections.
    2. Use H3 for sub-sections.
    3. Use H4 for technical specifications or micro-details.
    4. Include a Markdown Table for technical specs or Comparisons.
    5. Word count: 1000+ words.
    6. TONE: Authoritative, experienced, and helpful.
    7. NO generic phrases like 'In conclusion' or 'Overall'.
    
    OUTPUT MUST BE RAW JSON ONLY:
    {{
      "seo_title": "Unique Title with Keyword",
      "meta_desc": "Max 160 chars",
      "category": "Wrangler Life",
      "tags": ["tag1", "tag2"],
      "content_body": "Full Markdown with H2, H3, H4, Tables, and Lists",
      "image_prompt": "Specific visual prompt for a Jeep {title} in cartoon vector GTA style"
    }}
    """
    
    print(f"      🤖 Grok writing article...")
    res = grok.call_rpc(system_prompt)
    if res and res['text']:
        try:
            # Clean JSON from markdown blocks
            clean_json = re.sub(r'```json|```', '', res['text']).strip()
            return json.loads(clean_json)
        except Exception as e:
            print(f"      ⚠️ JSON Parse Error: {e}")
    return None

# ==========================================
# 🎨 IMAGE GENERATOR (GROK FLUX)
# ==========================================

def generate_image(prompt, filename):
    print(f"      🎨 Grok generating image...")
    # Paksa style kartun agar seragam
    full_prompt = f"{prompt}, cartoon vector art, thick outlines, flat vibrant colors, cel shaded, 2d game art, no photorealism, high resolution"
    
    res = grok.call_rpc(full_prompt, is_image=True)
    
    if res and res['image_url']:
        try:
            img_data = requests.get(res['image_url']).content
            img = Image.open(BytesIO(img_data))
            
            # Watermark logic
            img = img.convert("RGB")
            draw = ImageDraw.Draw(img)
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 24)
            except:
                font = ImageFont.load_default()
            
            draw.text((img.size[0]-160, 30), "@JeepDaily", fill=(255,255,255), font=font)
            
            output_path = f"{IMAGE_DIR}/{filename}"
            img.save(output_path, "WEBP", quality=90)
            return f"/images/{filename}"
        except: pass
    return ""

# ==========================================
# 🚀 INDEXING FUNCTIONS
# ==========================================

def submit_to_indexnow(url):
    try:
        host = WEBSITE_URL.replace("https://", "").replace("http://", "")
        data = {"host": host, "key": INDEXNOW_KEY, "keyLocation": f"{WEBSITE_URL}/{INDEXNOW_KEY}.txt", "urlList": [url]}
        requests.post("https://api.indexnow.org/indexnow", json=data, timeout=10)
        print(f"      🚀 IndexNow: OK")
    except: pass

def submit_to_google(url):
    if not GOOGLE_JSON_KEY or not GOOGLE_LIBS_AVAILABLE: return
    try:
        creds_dict = json.loads(GOOGLE_JSON_KEY)
        credentials = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, ["https://www.googleapis.com/auth/indexing"])
        service = build("indexing", "v3", credentials=credentials)
        service.urlNotifications().publish(body={"url": url, "type": "URL_UPDATED"}).execute()
        print(f"      🚀 Google Index: OK")
    except Exception as e: print(f"      ❌ Google Index Error: {e}")

# ==========================================
# 🏁 MAIN WORKFLOW
# ==========================================

def main():
    for d in [CONTENT_DIR, IMAGE_DIR, DATA_DIR]: os.makedirs(d, exist_ok=True)
    
    # Author Profiles
    authors = ["Rick 'Muddy' O'Connell", "Sarah Miller", "Mike Stevens"]
    
    # RSS Sources
    sources = ["https://news.google.com/rss/search?q=Jeep+Wrangler+Review&hl=en-US&gl=US&ceid=US:en"]
    
    print(f"🔥 JEEP ENGINE GROK SSO STARTED (Tokens: {len(GROK_SSO_TOKENS)}) 🔥")

    for url in sources:
        feed = feedparser.parse(url)
        for entry in feed.entries[:2]: # Limit 2 per run
            clean_title = entry.title.split(" - ")[0]
            slug = slugify(clean_title, max_length=50)
            
            if os.path.exists(f"{CONTENT_DIR}/{slug}.md"): continue
            
            author = random.choice(authors)
            print(f"\n📡 Topic: {clean_title}")
            
            # 1. Generate Article via Grok
            data = generate_article(clean_title, entry.summary, author)
            if not data: continue
            
            # 2. Generate Image via Grok
            img_path = generate_image(data.get('image_prompt', clean_title), f"{slug}.webp")
            
            # 3. Build Markdown
            md_content = f"""---
title: "{data['seo_title'].replace('"', "'")}"
date: {datetime.now().strftime("%Y-%m-%dT%H:%M:%S+00:00")}
author: "{author}"
categories: ["{data.get('category', 'Wrangler Life')}"]
tags: {json.dumps(data.get('tags', []))}
featured_image: "{img_path}"
description: "{data['meta_desc'].replace('"', "'")}"
slug: "{slug}"
url: "/{slug}/"
---

{data['content_body']}

---
*Analysis by {author}. Ref: [{clean_title}]({entry.link})*
"""
            with open(f"{CONTENT_DIR}/{slug}.md", "w", encoding="utf-8") as f:
                f.write(md_content)
            
            # 4. Indexing
            full_url = f"{WEBSITE_URL}/{slug}/"
            submit_to_indexnow(full_url)
            submit_to_google(full_url)
            
            print(f"✅ Success: {slug}")
            time.sleep(15) # Safety delay for Grok

if __name__ == "__main__":
    main()
