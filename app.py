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

# --- 1. Load credentials ---
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite-preview")

# --- 2. Config ---
MAX_PER_FEED = 7
MAX_TOTAL_ARTICLES = 20
TOP_ARTICLES_TO_SEND = 5
TELEGRAM_DELAY_SECONDS = 2

# --- 3. RSS sources ---
rss_feeds = [
    "https://aviationweek.com/awn-rss/feed",
    "https://www.aerotime.aero/sitemap.rss",
    "https://simpleflying.com/feed",
]


def validate_config():
    required = {
        "SUPABASE_URL": SUPABASE_URL,
        "SUPABASE_KEY": SUPABASE_KEY,
        "GEMINI_API_KEY": GEMINI_API_KEY,
        "TELEGRAM_BOT_TOKEN": BOT_TOKEN,
        "TELEGRAM_CHAT_ID": CHAT_ID,
    }

    missing = [key for key, value in required.items() if not value]
    if missing:
        raise ValueError(f"Missing environment variables: {', '.join(missing)}")


# --- 4. Initialize clients ---
validate_config()
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
client = genai.Client(api_key=GEMINI_API_KEY)


def clean_html(text):
    if not text:
        return ""
    return BeautifulSoup(text, "html.parser").get_text(separator=" ", strip=True)


def fetch_articles():
    articles = []

    for rss_url in rss_feeds:
        try:
            feed = feedparser.parse(rss_url)

            for entry in feed.entries[:MAX_PER_FEED]:
                if len(articles) >= MAX_TOTAL_ARTICLES:
                    break

                try:
                    title = entry.get("title", "Untitled")
                    summary = clean_html(
                        entry.get("summary") or entry.get("description") or ""
                    )
                    url = entry.get("link", "")

                    if not url:
                        continue

                    articles.append(
                        {
                            "title": title,
                            "summary": summary,
                            "url": url,
                        }
                    )
                except Exception as e:
                    print(f"Feed entry error: {rss_url} -> {e}")

        except Exception as e:
            print(f"Feed error: {rss_url} -> {e}")

    return articles


def filter_new_articles(articles):
    new_articles = []

    for article in articles:
        try:
            response = (
                supabase.table("processed_articles")
                .select("url")
                .eq("url", article["url"])
                .execute()
            )

            if len(response.data) == 0:
                new_articles.append(article)

        except Exception as e:
            print(f"DB check error: {e}")

    return new_articles


def strip_code_fences(text):
    text = text.strip()

    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]

    if text.endswith("```"):
        text = text[:-3]

    return text.strip()


def generate_report(news_block):
    prompt = f"""
You are a viral content strategist for an aviation news audience.

You will receive MULTIPLE aviation news articles.

Your task:

1. Analyze EACH news individually
2. Assign:
   - category (Airlines, Aircraft, Airports, Defense, Business, Safety, Technology, Other)
   - virality score (1-10)

3. Select TOP {TOP_ARTICLES_TO_SEND} with highest viral potential (balanced mix)

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
- Start with emoji (✈️🔥🚨🛫📰)
- Emotional + engaging
- Clear English
- End with a question
- Keep it concise

Return ONLY valid JSON in this exact format:

{{
  "report": [
    {{
      "title": "string",
      "category": "string",
      "score": 8,
      "reason": "string",
      "caption": "string",
      "hashtags": ["#tag1", "#tag2", "#tag3", "#tag4", "#tag5"],
      "source_url": "https://example.com/article"
    }}
  ]
}}

News:
{news_block}
"""

    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config={"response_mime_type": "application/json"},
            )

            return strip_code_fences(response.text)

        except Exception as e:
            print(f"Gemini retry {attempt + 1}: {e}")
            time.sleep(3)

    return None


def save_articles(articles):
    for article in articles:
        try:
            supabase.table("processed_articles").insert({"url": article["url"]}).execute()
        except Exception as e:
            print(f"Insert error: {e}")


def send_to_telegram(article):
    hashtags = article.get("hashtags", [])
    if isinstance(hashtags, list):
        hashtags_text = " ".join(hashtags)
    else:
        hashtags_text = str(hashtags)

    message = (
        f"{article.get('caption', '')}\n\n"
        f"Title: {article.get('title', 'Untitled')}\n"
        f"Category: {article.get('category', 'Other')}\n"
        f"Score: {article.get('score', 'N/A')}\n"
        f"Reason: {article.get('reason', '')}\n"
        f"Source: {article.get('source_url', '')}\n\n"
        f"{hashtags_text}"
    )

    response = requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        data={
            "chat_id": CHAT_ID,
            "text": message,
            "disable_web_page_preview": "false",
        },
        timeout=30,
    )
    response.raise_for_status()


def process_news():
    print("🚀 Fetching articles...")

    # --- 1. Fetch ---
    articles = fetch_articles()

    # --- 2. Filter already processed ---
    new_articles = filter_new_articles(articles)

    if not new_articles:
        print("No new articles found.")
        return

    print(f"Processing {len(new_articles)} new articles...")

    # --- 3. Prepare input for Gemini ---
    news_block = "\n\n".join(
        [
            f"Title: {a['title']}\nSummary: {a['summary']}\nSource: {a['url']}"
            for a in new_articles[:MAX_TOTAL_ARTICLES]
        ]
    )

    # --- 4. Generate AI report ---
    report = generate_report(news_block)

    if not report:
        print("Failed to generate report.")
        return

    # --- 5. Parse JSON ---
    try:
        data = json.loads(report)
        top_articles = data["report"]
    except Exception as e:
        print("❌ JSON parse error:", e)
        print("Raw response:", report)
        return

    # --- 6. Send each article to Telegram ---
    for article in top_articles:
        try:
            send_to_telegram(article)
            print(f"✅ Sent: {article.get('title', 'Untitled')}")
            time.sleep(TELEGRAM_DELAY_SECONDS)
        except Exception as e:
            print(f"Telegram send error: {e}")

    # --- 7. Save all fetched new articles as processed ---
    save_articles(new_articles)
    print("✅ Done.")


if __name__ == "__main__":
    process_news()
