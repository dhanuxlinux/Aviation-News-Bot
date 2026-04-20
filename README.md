# ✈️ Aviation News Bot

An automated bot that fetches the latest aviation news, ranks them by viral potential using Gemini AI, and sends the top stories directly to a Telegram channel — running on GitHub Actions every 4 hours.

---

## 🚀 How It Works

1. **Fetches** articles from aviation RSS feeds
2. **Filters** out already-processed articles (stored in Supabase)
3. **Sends** the articles to Gemini AI, which scores and selects the top 5
4. **Posts** each story to a Telegram channel with a caption and hashtags
5. **Saves** processed URLs to Supabase to avoid duplicates

---

## 📰 RSS Sources

- [Aviation Week](https://aviationweek.com/awn-rss/feed)
- [Aerotime](https://www.aerotime.aero/sitemap.rss)
- [Simple Flying](https://simpleflying.com/feed)

---

## 🗂️ Project Structure

```
your-repo/
├── .github/
│   └── workflows/
│       └── run_news.yml   # GitHub Actions scheduler
├── app.py                 # Main bot logic
├── requirements.txt       # Python dependencies
├── .gitignore
└── README.md
```

---

## ⚙️ Setup

### 1. Clone the repository

```bash
git clone https://github.com/your-username/your-repo.git
cd your-repo
```

### 2. Add GitHub Secrets

Go to your repo → **Settings** → **Secrets and variables** → **Actions** and add:

| Secret Name | Description |
|---|---|
| `SUPABASE_URL` | Your Supabase project URL |
| `SUPABASE_KEY` | Your Supabase anon/service key |
| `GEMINI_API_KEY` | Your Google Gemini API key |
| `TELEGRAM_BOT_TOKEN` | Your Telegram bot token |
| `TELEGRAM_CHAT_ID` | Your Telegram channel/chat ID |

### 3. Set up Supabase

Create a table called `processed_articles` in your Supabase project with the following column:

| Column | Type |
|---|---|
| `url` | text |

### 4. Push to GitHub

The bot will start running automatically on the schedule. You can also trigger it manually from the **Actions** tab.

---

## 🕐 Schedule

The bot runs automatically **every 4 hours** via GitHub Actions.
To change the schedule, edit the cron expression in `.github/workflows/run_news.yml`:

```yaml
- cron: '0 */4 * * *'
```

---

## 🛠️ Local Development

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Create a `.env` file in the root folder:
```
SUPABASE_URL=your_supabase_url
SUPABASE_KEY=your_supabase_key
GEMINI_API_KEY=your_gemini_key
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

3. Run the bot:
```bash
python app.py
```

---

## 📦 Dependencies

- `feedparser` — RSS feed parsing
- `beautifulsoup4` — HTML cleaning
- `google-genai` — Gemini AI integration
- `supabase` — Database for deduplication
- `python-dotenv` — Local environment variables
- `requests` — Telegram API calls
