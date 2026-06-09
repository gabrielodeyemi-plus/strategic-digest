# Strategic Intelligence Digest

A daily 7am agent that pulls articles from RSS feeds across topics you define, synthesizes them into a strategic morning briefing using Claude, pushes to Notion, and emails you an HTML digest — automatically, every day.

![python](https://img.shields.io/badge/python-3.9+-blue?style=flat-square) ![claude](https://img.shields.io/badge/claude-opus--4--8-7c3aed?style=flat-square) ![schedule](https://img.shields.io/badge/runs-7am_daily-green?style=flat-square)

---

## What it produces

```
## 🔑 Must-Know Today
Key developments with one-sentence strategic implications each.

## 🔗 The Connecting Thread
The cross-topic pattern or tension no single article contains — Claude's synthesis anchor.

## 📡 What to Watch
2-3 weak signals not yet mainstream but likely to matter in 30-90 days.

## ⚡ Recommended Actions
Specific things to do or decide in the next 48 hours, tied directly to the briefing.
```

Delivered to your inbox as a styled HTML email and saved to Notion for reference.

---

## Architecture

```
topics.yaml   →  fetcher.py   →  synthesizer.py  →  notion_pusher.py
                 (feedparser)     (Claude)             (Notion API)
                                      ↓
                               emailer.py
                               (Gmail SMTP)
```

**Key design decisions:**

- **RSS over news APIs.** No API keys required for sources, no rate limits, fully customizable. feedparser handles the parsing; you control the signal by choosing the feeds.
- **Topics as config, not code.** Add or remove topics by editing `topics.yaml`. No code changes needed to track a new industry, company, or theme.
- **One synthesis call, not many.** All articles from all topics go into a single Claude call with a chief-of-staff prompt. This produces a unified briefing that connects dots across topics — the highest-value output that individual article summaries can't achieve.
- **Gmail App Password, not OAuth.** Sending a daily email is a write-only operation. App passwords are simpler to set up and don't require maintaining OAuth token refresh.

---

## Setup

**Requirements:** macOS, Python 3.9+, Anthropic API key, Notion API token, Gmail account

```bash
git clone https://github.com/gabrielodeyemi-plus/strategic-digest
cd strategic-digest
cp .env.example .env    # fill in your keys (see below)
bash install.sh         # creates venv, installs deps, registers 7am launchd job
```

**Gmail App Password (required for email delivery):**
1. Google Account → Security → 2-Step Verification (enable if not on)
2. Google Account → Security → App passwords
3. Generate one for "Mail" → paste into `.env` as `GMAIL_APP_PASSWORD`

**Notion setup:**
- Reuse an existing database or create one with: `Meeting Title` (title), `Date` (date), `Meeting Type` (select), `Status` (select)
- Digest entries appear with type `Strategic Digest`

**Test immediately (without waiting for 7am):**
```bash
.venv/bin/python main.py
```

---

## Customizing your topics

Edit `topics.yaml` to track what matters to you:

```yaml
topics:
  - name: AI & Technology
    feeds:
      - url: https://techcrunch.com/category/artificial-intelligence/feed/
        label: TechCrunch AI
      - url: https://www.technologyreview.com/feed/
        label: MIT Technology Review

  - name: Your Industry
    feeds:
      - url: https://your-industry-rss-feed.com/feed
        label: Source Name
```

Any public RSS feed works. Most major publications, newsletters, and blogs publish one.

---

## Tech stack

| Layer | Choice | Why |
|---|---|---|
| Feed parsing | feedparser | Battle-tested RSS/Atom parser, no API key needed |
| Synthesis | Claude claude-opus-4-8 | Strategic reasoning across multiple sources |
| Email | smtplib (Gmail SMTP) | Simple, reliable, no OAuth flow required |
| Persistence | Notion API | Searchable archive of every past briefing |
| Scheduling | macOS launchd | Native scheduler, survives reboots |

---

## Project structure

```
main.py           — orchestrator: fetch → synthesize → push → email
fetcher.py        — RSS feed fetcher with 48-hour recency filter
synthesizer.py    — Claude strategic briefing prompt and API call
notion_pusher.py  — Notion page creation from markdown briefing
emailer.py        — HTML email formatter and Gmail SMTP sender
topics.yaml       — topic and feed configuration (edit this)
install.sh        — venv setup + launchd plist generator
```
