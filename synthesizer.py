"""
Synthesizes a strategic morning briefing from fetched articles using Claude.
"""

import os
from datetime import date

import anthropic

_SYSTEM = """You are a chief of staff briefing a senior executive each morning.
Your job is to turn raw news into strategic intelligence — not a news summary,
but a curated read on what matters and why.

Principles:
- Signal over noise. Ignore incremental, obvious, or low-stakes items.
- Connect dots across topics. The most valuable insights often live at the intersection.
- Be direct. No filler phrases, no "it's worth noting", no passive voice.
- Every point must pass the "so what" test. If you can't say why it matters, cut it.
- Executive length: something they can read in under 4 minutes."""

_PROMPT_TEMPLATE = """Today is {date}.

Below are the latest articles across your tracked topics. Produce a strategic morning briefing with exactly these sections:

---

## 🔑 Must-Know Today
3-5 bullet points. Each one: a single sentence that states the development + one sentence on why it matters strategically. No fluff.

## 🔗 The Connecting Thread
One paragraph (4-6 sentences). Identify the single most important pattern or tension that cuts across multiple topics today. This is the insight no individual article contains but the aggregate reveals. Be bold — stake a position.

## 📡 What to Watch
2-3 emerging signals that are not yet mainstream but could matter in 30-90 days. One sentence each: what it is + why you're flagging it now.

## ⚡ Recommended Actions
1-3 specific, concrete things the reader should do or decide in the next 48 hours based on today's intelligence. Not generic advice — tied directly to what's in the briefing.

---

ARTICLES BY TOPIC:

{articles_block}

Return only the briefing. No preamble, no "Here is your briefing:", no sign-off."""


def synthesize(articles_by_topic: dict) -> str:
    today = date.today().strftime("%A, %B %d, %Y")

    # Build the articles block
    parts = []
    total = 0
    for topic, articles in articles_by_topic.items():
        if not articles:
            continue
        parts.append(f"### {topic}")
        for a in articles:
            parts.append(f"**{a['title']}** ({a['source']})")
            if a.get("summary"):
                parts.append(a["summary"])
            parts.append("")
            total += 1

    if total == 0:
        return "No articles fetched today. Check your RSS feeds in topics.yaml."

    articles_block = "\n".join(parts)

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    response = client.messages.create(
        model=os.environ.get("CLAUDE_MODEL", "claude-opus-4-8"),
        max_tokens=2048,
        system=_SYSTEM,
        messages=[{
            "role": "user",
            "content": _PROMPT_TEMPLATE.format(date=today, articles_block=articles_block),
        }],
    )
    return response.content[0].text
