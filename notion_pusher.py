"""
Pushes the daily strategic digest to a Notion database page.
"""

import os
import re
from datetime import date

from notion_client import Client


def push(briefing: str) -> str:
    """Create a Notion page for today's digest. Returns the page URL."""
    client = Client(auth=os.environ["NOTION_TOKEN"])
    database_id = os.environ["NOTION_DATABASE_ID"]
    today = date.today()
    title = f"Strategic Digest — {today.strftime('%B %d, %Y')}"

    blocks = _markdown_to_blocks(briefing)

    page = client.pages.create(
        parent={"database_id": database_id},
        properties={
            "Meeting Title": {"title": [{"text": {"content": title}}]},
            "Date": {"date": {"start": today.isoformat()}},
            "Meeting Type": {"select": {"name": "Strategic Digest"}},
            "Status": {"select": {"name": "Complete"}},
        },
        children=blocks[:100],
    )
    page_id = page["id"]

    for start in range(100, len(blocks), 100):
        client.blocks.children.append(
            block_id=page_id,
            children=blocks[start:start + 100],
        )

    return page.get("url", "")


# ---------------------------------------------------------------------------
# Markdown → Notion blocks (lightweight, digest-specific)
# ---------------------------------------------------------------------------

def _markdown_to_blocks(text: str) -> list[dict]:
    blocks = []
    for line in text.splitlines():
        stripped = line.rstrip()

        if stripped.startswith("## "):
            blocks.append(_heading2(stripped[3:]))
        elif stripped.startswith("### "):
            blocks.append(_heading3(stripped[4:]))
        elif stripped.startswith("---"):
            blocks.append({"object": "block", "type": "divider", "divider": {}})
        elif stripped.startswith("- ") or stripped.startswith("• "):
            blocks.append(_bullet(stripped[2:]))
        elif stripped == "":
            pass  # skip blank lines
        else:
            blocks.append(_paragraph(stripped))

    return blocks


def _rich(text: str) -> list:
    parts = []
    segments = re.split(r"(\*\*[^*]+\*\*)", text)
    for seg in segments:
        if seg.startswith("**") and seg.endswith("**"):
            parts.append({
                "type": "text",
                "text": {"content": seg[2:-2]},
                "annotations": {"bold": True},
            })
        elif seg:
            parts.append({"type": "text", "text": {"content": seg}})
    return parts or [{"type": "text", "text": {"content": text}}]


def _heading2(text: str) -> dict:
    return {"object": "block", "type": "heading_2",
            "heading_2": {"rich_text": [{"type": "text", "text": {"content": text}}]}}


def _heading3(text: str) -> dict:
    return {"object": "block", "type": "heading_3",
            "heading_3": {"rich_text": [{"type": "text", "text": {"content": text}}]}}


def _bullet(text: str) -> dict:
    return {"object": "block", "type": "bulleted_list_item",
            "bulleted_list_item": {"rich_text": _rich(text)}}


def _paragraph(text: str) -> dict:
    return {"object": "block", "type": "paragraph",
            "paragraph": {"rich_text": _rich(text)}}
