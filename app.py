import os
import json
import time
import requests
import feedparser
from bs4 import BeautifulSoup
from google import genai
from dotenv import load_dotenv

load_dotenv()
from supabase import create_client, Client

# --- 1. Load Credentials ---
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# --- 2. Initialize Clients ---
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
client = genai.Client(api_key=GEMINI_API_KEY)

# --- CONFIG ---
MAX_PER_FEED = 7
MAX_TOTAL_ARTICLES = 20

# --- RSS SOURCES ---
rss_feeds = [
    "https://aviationweek.com/awn-rss/feed",
    "https://www.aerotime.aero/sitemap.rss",
    "https://simpleflying.com/feed"
]

def clean_html(text):
    return BeautifulSoup(text, "html.parser").get_text()

def fetch_articles():
    articles = []

    for rss_url in rss_feeds:
        feed = feedparser.parse(rss_url)

        for entry in feed.entries[:MAX_PER_FEED]:
            if len(articles) >= MAX_TOTAL_ARTICLES:
                break

            try:
                articles.append({
                    "title": entry.title,
                    "summary": clean_html(entry.description),
                    "url": entry.link
                })
            except Exception as e:
                print(f"Feed error: {rss_url} → {e}")

    print(f"📥 Fetched {len(articles)} total articles from feeds.")
    return articles

def is_already_processed(url):
    try:
        response = supabase.table("processed_articles")\
            .select("url")\
            .eq("url", url)\
            .execute()
        return len(response.data) > 0
    except Exception as e:
        print(f"⚠️ DB check error for {url}: {e}")
        return False  # If check fails, treat as new to avoid skipping

def filter_new_articles(articles):
    new_articles = []
    for article in articles:
        if not is_already_processed(article["url"]):
            new_articles.append(article)
    print(f"🔍 {len(new_articles)} new articles after filtering.")
    return new_articles

def save_url(url):
    """Save a single URL to Supabase immediately."""
    try:
        supabase.table("processed_articles")\
            .upsert({"url": url}, on_conflict="url")\
            .execute()
        print(f"💾 Saved: {url}")
        return True
    except Exception as e:
        print(f"❌ Save error for {url}: {e}")
        return False

def generate_report(news_block):
    prompt = f"""
You are a viral content strategist.

You will receive MULTIPLE news articles.

Your task:

1. Analyze EACH news individually
2. Assign:
   - category (Aviation, Technology, Safety, Industry, Weird)
   - virality score (1-10)

3. Select TOP 5 with highest viral potential (balanced mix)

4. For each selected news return:

- title
- category
- score
- reason
- caption
- hashtags (exactly 5)
- source_url

---

Caption rules:
- Start with emoji (🔥 🚨 👀)
- Emotional + engaging
- End with a question

---

Return ONLY a valid JSON object in this format:
{{
  "report": [
    {{
      "title": "...",
      "category": "...",
      "score": 0,
      "reason": "...",
      "caption": "...",
      "hashtags": ["...", "...", "...", "...", "..."],
      "source_url": "..."
    }}
  ]
}}

---

News:
{news_block}
"""

    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model='gemini-3.1-flash-lite-preview',
                contents=prompt,
                config={
                    "response_mime_type": "application/json"
                }
            )
            return response.text.strip()

        except Exception as e:
            print(f"Gemini retry {attempt + 1}: {e}")
            time.sleep(3)

    return None

def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    }
    try:
        r = requests.post(url, json=payload)
        if r.status_code != 200:
            print(f"⚠️ Telegram error {r.status_code}: {r.text}")
    except Exception as e:
        print(f"❌ Telegram error: {e}")

def process_news():
    print("🚀 Starting Aviation News Bot...")

    # --- 1. Fetch ---
    articles = fetch_articles()
    if not articles:
        print("No articles fetched.")
        return

    # --- 2. Filter already processed ---
    new_articles = filter_new_articles(articles)

    if not new_articles:
        print("✅ No new articles found. All caught up!")
        return

    # --- 3. Save ALL new articles to Supabase IMMEDIATELY
    #        This prevents duplicates even if Gemini or Telegram fails later
    print(f"💾 Saving {len(new_articles)} new article URLs to Supabase...")
    for article in new_articles:
        save_url(article["url"])

    # --- 4. Prepare input for Gemini ---
    news_block = "\n\n".join([
        f"Title: {a['title']}\nSummary: {a['summary']}\nSource: {a['url']}"
        for a in new_articles[:MAX_TOTAL_ARTICLES]
    ])

    # --- 5. Generate AI report ---
    print("🤖 Generating AI report...")
    report = generate_report(news_block)

    if not report:
        print("❌ Failed to generate report after 3 attempts.")
        return

    # --- 6. Parse JSON ---
    try:
        data = json.loads(report)
        top_articles = data["report"]
    except Exception as e:
        print("❌ JSON parse error:", e)
        print("Raw response:", report)
        return

    # --- 7. Send each article to Telegram ---
    print(f"📨 Sending {len(top_articles)} articles to Telegram...")
    for article in top_articles:
        message = (
            f"✈️ <b>{article['title']}</b>\n\n"
            f"📂 Category: {article['category']}\n"
            f"🔥 Virality Score: {article['score']}/10\n\n"
            f"{article['caption']}\n\n"
            f"🏷️ {' '.join(article['hashtags'])}\n\n"
            f"🔗 <a href='{article['source_url']}'>Read more</a>"
        )
        send_telegram_message(message)
        time.sleep(1)

    print(f"✅ Done! Sent {len(top_articles)} articles to Telegram.")

if __name__ == "__main__":
    process_news()
