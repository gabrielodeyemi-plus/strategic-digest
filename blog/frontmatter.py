"""Shared YAML frontmatter parsing and deterministic serialization."""

import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import yaml

FRONTMATTER_PATTERN = re.compile(
    r"\A---\r?\n(?P<yaml>[\s\S]*?)\r?\n---(?P<after>\r?\n|\Z)"
)

FRONTMATTER_ORDER = (
    "title",
    "subtitle",
    "date",
    "author",
    "slug",
    "tags",
    "excerpt",
    "seo_description",
    "seo_title",
    "topic_cluster",
    "primary_keyword",
    "secondary_keywords",
    "source",
    "source_digest_date",
    "source_digest_id",
    "canonical_url",
    "status",
    "minimum_sources_required",
    "internal_link_targets",
    "suggested_related_posts",
    "sources",
)

_TOP_LEVEL_KEY = re.compile(r"^(?P<key>[A-Za-z_][A-Za-z0-9_-]*)\s*:")


class FrontmatterError(RuntimeError):
    """User-actionable frontmatter failure."""


def duplicate_top_level_keys(yaml_text: str) -> list[str]:
    """Return duplicated top-level keys before PyYAML can overwrite them."""
    seen = set()
    duplicates = []
    duplicate_seen = set()
    for raw_line in yaml_text.splitlines():
        if not raw_line or raw_line[0].isspace() or raw_line.startswith("-"):
            continue
        match = _TOP_LEVEL_KEY.match(raw_line)
        if not match:
            continue
        key = match.group("key")
        if key in seen and key not in duplicate_seen:
            duplicates.append(key)
            duplicate_seen.add(key)
        seen.add(key)
    return duplicates


def assert_no_duplicate_top_level_keys(yaml_text: str, *, action: str) -> None:
    duplicates = duplicate_top_level_keys(yaml_text)
    if not duplicates:
        return
    keys = ", ".join(duplicates)
    if len(duplicates) == 1:
        raise FrontmatterError(
            f"Duplicate frontmatter key: {keys}. "
            f"Remove duplicate {keys} entries before {action}."
        )
    raise FrontmatterError(
        f"Duplicate frontmatter keys: {keys}. "
        f"Remove duplicate entries before {action}."
    )


def parse_markdown_frontmatter(
    markdown: str,
    source_path: Path,
    *,
    action: str,
) -> tuple[dict, re.Match[str]]:
    match = FRONTMATTER_PATTERN.match(markdown)
    if not match:
        raise FrontmatterError(f"{source_path.name} has no valid YAML frontmatter.")
    yaml_text = match.group("yaml")
    assert_no_duplicate_top_level_keys(yaml_text, action=action)
    try:
        parsed = yaml.safe_load(yaml_text)
    except yaml.YAMLError as exc:
        raise FrontmatterError(
            f"{source_path.name} has invalid YAML frontmatter. "
            f"Fix the YAML before {action}: {exc}"
        ) from exc
    if not isinstance(parsed, dict):
        raise FrontmatterError(f"{source_path.name} frontmatter must be an object.")
    return parsed, match


def normalize_markdown_frontmatter(
    markdown: str,
    source_path: Path,
    *,
    status: Optional[str] = None,
    action: str,
) -> tuple[dict, str]:
    parsed, match = parse_markdown_frontmatter(
        markdown, source_path, action=action
    )
    normalized = dict(parsed)
    if status is not None:
        normalized.pop("status", None)
        normalized["status"] = status
    frontmatter = serialize_frontmatter(normalized)
    updated = (
        markdown[: match.start("yaml")]
        + frontmatter
        + markdown[match.end("yaml") :]
    )
    return normalized, updated


def serialize_frontmatter(frontmatter: dict) -> str:
    ordered_keys = [key for key in FRONTMATTER_ORDER if key in frontmatter]
    extra_keys = sorted(key for key in frontmatter if key not in FRONTMATTER_ORDER)
    keys = [*ordered_keys, *extra_keys]
    lines = [_render_field(key, frontmatter[key]) for key in keys]
    return "\n".join(lines)


def _render_field(key: str, value) -> str:
    if isinstance(value, list):
        return _render_list(key, value)
    if isinstance(value, dict):
        dumped = yaml.safe_dump(
            {key: value},
            sort_keys=True,
            allow_unicode=True,
            default_flow_style=False,
        ).strip()
        return dumped
    return f"{key}: {_render_scalar(value)}"


def _render_list(key: str, value: list) -> str:
    if not value:
        return f"{key}: []"
    if all(not isinstance(item, (dict, list)) for item in value):
        items = [_normalize_scalar(item) for item in value]
        return f"{key}: {json.dumps(items, ensure_ascii=False)}"
    lines = [f"{key}:"]
    for item in value:
        if isinstance(item, dict):
            entry_keys = _ordered_entry_keys(item)
            if not entry_keys:
                lines.append("  - {}")
                continue
            first, *rest = entry_keys
            lines.append(f"  - {first}: {_render_scalar(item[first])}")
            for entry_key in rest:
                lines.append(f"    {entry_key}: {_render_scalar(item[entry_key])}")
        else:
            lines.append(f"  - {_render_scalar(item)}")
    return "\n".join(lines)


def _ordered_entry_keys(item: dict) -> list[str]:
    preferred = ("title", "label", "url", "publisher", "date", "reason", "status")
    keys = [key for key in preferred if key in item]
    keys.extend(sorted(key for key in item if key not in preferred))
    return keys


def _normalize_scalar(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _render_scalar(value) -> str:
    value = _normalize_scalar(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    return json.dumps(value, ensure_ascii=False)
