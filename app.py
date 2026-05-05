import os
import json
import time
import requests
import feedparser
from bs4 import BeautifulSoup
from google import genai
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

# --- 1. Load Credentials ---
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

print(f"🔗 Supabase URL: {SUPABASE_URL[:40]}...")

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
    if not text:
        return ""
    return BeautifulSoup(text, "html.parser").get_text()

def get_entry_description(entry):
    """Safely get description from a feed entry — different feeds use different fields."""
    for field in ["description", "summary", "content", "title"]:
        value = getattr(entry, field, None)
        if value:
            if isinstance(value, list):
                return clean_html(value[0].get("value", ""))
            return clean_html(str(value))
    return ""

def fetch_articles():
    articles = []
    for rss_url in rss_feeds:
        try:
            feed = feedparser.parse(rss_url)
            count = 0
            for entry in feed.entries:
                if len(articles) >= MAX_TOTAL_ARTICLES:
                    break
                if count >= MAX_PER_FEED:
                    break
                url = getattr(entry, "link", None)
                title = getattr(entry, "title", None)
                if not url or not title:
                    continue
                summary = get_entry_description(entry)
                articles.append({
                    "title": title,
                    "summary": summary,
                    "url": url
                })
                count += 1
            print(f"📡 {rss_url} → {count} articles")
        except Exception as e:
            print(f"❌ Feed error {rss_url}: {e}")
    print(f"📥 Fetched {len(articles)} articles total.")
    return articles

def get_processed_urls():
    """Load ALL already-processed URLs from Supabase into a set."""
    try:
        response = supabase.table("processed_articles").select("url").execute()
        urls = {row["url"] for row in response.data}
        print(f"📋 Found {len(urls)} already-processed URLs in Supabase.")
        return urls
    except Exception as e:
        print(f"❌ Could not load processed URLs: {e}")
        return set()

def save_urls(urls):
    """Save a list of URLs to Supabase."""
    saved = 0
    for url in urls:
        try:
            supabase.table("processed_articles")\
                .insert({"url": url})\
                .execute()
            print(f"💾 Saved: {url}")
            saved += 1
        except Exception as e:
            print(f"⚠️ Could not save {url}: {e}")
    print(f"✅ Saved {saved}/{len(urls)} URLs to Supabase.")

def generate_report(news_block):
    prompt = f"""
You are a viral content strategist.

You will receive MULTIPLE news articles.

Your task:

1. Analyze EACH news individually
2. Assign:
   - category (Aviation, Technology, Safety, Industry, Weird)
   - virality score (1-10)

3. Select TOP 2 with highest viral potential (balanced mix)
   - If multiple articles cover the same event or story, treat them as ONE and pick only the best written one

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
                config={"response_mime_type": "application/json"}
            )
            return response.text.strip()
        except Exception as e:
            print(f"⚠️ Gemini retry {attempt + 1}: {e}")
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
        else:
            print(f"📨 Sent to Telegram OK")
    except Exception as e:
        print(f"❌ Telegram error: {e}")

def process_news():
    print("🚀 Starting Aviation News Bot...")

    # --- 1. Fetch articles from RSS ---
    articles = fetch_articles()
    if not articles:
        print("❌ No articles fetched. Stopping.")
        return

    # --- 2. Load already-processed URLs from Supabase ---
    processed_urls = get_processed_urls()

    # --- 3. Filter out already seen articles ---
    new_articles = [a for a in articles if a["url"] not in processed_urls]
    print(f"🔍 {len(new_articles)} new articles after filtering.")

    if not new_articles:
        print("✅ No new articles today. All caught up!")
        return

    # --- 4. Save new URLs to Supabase RIGHT NOW before anything else ---
    print(f"💾 Saving {len(new_articles)} new URLs to Supabase...")
    save_urls([a["url"] for a in new_articles])

    # --- 5. Prepare news block for Gemini ---
    news_block = "\n\n".join([
        f"Title: {a['title']}\nSummary: {a['summary']}\nSource: {a['url']}"
        for a in new_articles[:MAX_TOTAL_ARTICLES]
    ])

    # --- 6. Generate AI report ---
    print("🤖 Asking Gemini to pick top stories...")
    report = generate_report(news_block)

    if not report:
        print("❌ Gemini failed to respond. Stopping.")
        return

    # --- 7. Parse JSON from Gemini ---
    try:
        data = json.loads(report)
        top_articles = data["report"]
        print(f"🏆 Gemini picked {len(top_articles)} top articles.")
    except Exception as e:
        print(f"❌ JSON parse error: {e}")
        print(f"Raw Gemini response: {report}")
        return

    # --- 8. Send to Telegram ---
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

    print(f"✅ All done! {len(top_articles)} articles sent to Telegram.")

if __name__ == "__main__":
    process_news()
