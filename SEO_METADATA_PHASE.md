# StrategicDigest: SEO/Discoverability Metadata

Extends blog generation so every future post carries `seo_title`,
`topic_cluster`, `primary_keyword`, `secondary_keywords`,
`internal_link_targets`, and `suggested_related_posts`, validated with a
warn-first, block-on-invalid rollout policy. No website-repo changes; the
July 6 local output was updated in place.

## 1. Implementation summary

**Controlled vocabulary (`blog/seo.py`, new).** Owns the 11 controlled
`TOPIC_CLUSTERS`, the 12-entry `INTERNAL_LINK_TARGET_UNIVERSE`, and the pure
validator `evaluate_seo_metadata(frontmatter, known_post_urls)`. It never
raises: everything becomes a warning or a blocker string. Missing fields
always warn; an invalid `topic_cluster`, structurally malformed metadata, or
a URL not on an allowed list always blocks. `known_blog_posts()` scans
`output_dir` for other local `.md` files (title + canonical URL), so
`suggested_related_posts` can be checked against what StrategicDigest
actually knows about, never an invented post.

**Model (`blog/models.py`).** `BlogPost` gained the six fields (all
empty/`[]` by default, so every existing caller keeps working unmodified).
`to_markdown()` serializes `secondary_keywords` inline like `tags`, and
`internal_link_targets`/`suggested_related_posts` as YAML block sequences of
`{label|title, url, reason?, status?}` objects, matching the task's example
format exactly. A shared `_link_list_block()` helper renders both.

**Transformer (`blog/transformer.py`).** The prompt now states the
discoverability rules explicitly (one controlled cluster, distinct
`seo_title` vs editorial `title`, 3-7 natural secondary keywords, 1-4
internal links copied verbatim from an injected allowed-URL list, 0-3
related posts copied verbatim from an injected known-posts list, never
invent). `transform()` injects the live controlled-cluster list, the link
universe, and the current known-posts list (read from
`config.output_dir`) into the prompt, then defensively filters the model's
JSON response: an invalid `topic_cluster` is dropped to empty (not
invented), out-of-universe `internal_link_targets` entries are dropped,
unknown `suggested_related_posts` entries are dropped, and
`secondary_keywords` is capped at 7. This is defense-in-depth on top of the
prompt, not a replacement for it.

**Readiness gates (`blog/approval.py`, `blog/check.py`).** A shared
`_evaluate_seo_readiness()` in `approval.py` (same pattern as the existing
`_evaluate_sources_readiness`) resolves known posts from `config.output_dir`
and calls `blog.seo.evaluate_seo_metadata`. `blog:check` renders it as a new
"SEO / discoverability" report section (WARN/FAIL/PASS lines, exactly like
the existing sections). `approve_blog_post` calls the same function inside
`_validate_and_approve_markdown` and raises `ApprovalError` if there are any
blockers, so `blog:check` and `blog:approve` can never disagree about
whether a post's discoverability metadata is valid, mirroring how source
readiness already worked.

**`blog:regenerate`.** No code changes were needed: it already runs
`BlogArticleTransformer.transform()` through `BlogPublishingService.publish()`
with `mode="local"` and `default_status="draft"` forced, so once the
transformer and model produce the new fields, regeneration does too, for
free. Verified with a new end-to-end test (see section 4).

**quality.py was deliberately left untouched.** `BlogQualityGate` gates
factual grounding at generation time (the automated retry loop); SEO/
discoverability metadata is a separate, editorial-adjacent concern that
belongs at the human-reviewed `blog:check`/`blog:approve` boundary, which is
also literally what section 3 of the request asked for. Wiring it into the
generation-retry loop as well would be a reasonable future addition but was
out of scope here.

## 2. Files changed

New:
- `blog/seo.py` — controlled vocabulary, known-posts scanning, pure validator
- `tests/test_seo_metadata.py` — 24 new tests (see section 4)
- `SEO_METADATA_PHASE.md` — this file

Modified:
- `blog/models.py` — six new `BlogPost` fields + frontmatter serialization
- `blog/transformer.py` — prompt + `transform()` + four `_clean_*` defensive filters
- `blog/approval.py` — `_evaluate_seo_readiness`, wired into `_validate_and_approve_markdown`
- `blog/check.py` — new `seo_items` section, wired into `run_check`/`render_report`
- `tests/test_approval.py` — shared `markdown()` fixture now includes valid SEO
  metadata by default (with override params), so every pre-existing test that
  didn't know about this feature keeps passing without being rewritten
- `README.md` — new "SEO and discoverability metadata" section
- `output/blog/2026-07-06-ai-trust-gate-control-not-capability.md` — new
  fields added; `status: "published"` and all 5 sources preserved exactly.
  This file is git-ignored local output, not committed, and the website repo
  was not touched.

Not changed: `blog/quality.py`, `blog/pr.py`, `blog/publishers.py`,
`blog/config.py`, `main.py`, any website-repo file.

## 3. New frontmatter example

From the updated July 6 file (values chosen to match this specific article's
actual content: AI governance, enterprise trust, data control):

```yaml
seo_title: "AI Trust, Governance, and Competitive Advantage in Enterprise Adoption"
topic_cluster: "AI Governance"
primary_keyword: "AI governance and trust"
secondary_keywords: ["enterprise AI adoption", "AI data control", "AI risk management", "AI competitive advantage"]
internal_link_targets:
  - label: "Strategic Digest"
    url: "/blog"
    reason: "The post is part of the Strategic Digest analysis archive."
  - label: "AI Strategy & Operations Consulting"
    url: "/ai-consulting"
    reason: "The article discusses AI adoption, governance, and operating advantage."
    status: "planned"
suggested_related_posts: []
```

`suggested_related_posts` is empty because this is currently the only post
in the corpus; there is nothing genuine to relate it to yet, and inventing
one would violate the "never invent a related post" rule.

## 4. Validation results

**Full test suite:** `90 tests, OK` (was 62 before this phase; all 62
pre-existing tests still pass unmodified in behavior, plus 28 new tests in
`tests/test_seo_metadata.py` covering: BlogPost frontmatter serialization
(2), pure `evaluate_seo_metadata` policy (9), transformer output and
defensive filtering (5), `blog:check` warn/block behavior (6), approval
blocking/non-blocking (5), and `blog:regenerate` end-to-end (1)).

**Python compilation:** `python -m py_compile` on every changed/new `.py`
file (`blog/seo.py`, `blog/models.py`, `blog/transformer.py`,
`blog/approval.py`, `blog/check.py`, `tests/test_approval.py`,
`tests/test_check.py`, `tests/test_seo_metadata.py`, `main.py`,
`blog_cli.py`) — clean, no errors.

**`blog:check --date 2026-07-06`** (run against the updated local file):

```
SEO / discoverability:
PASS discoverability metadata present and valid
```

Confirms the new metadata section passes its own validation. The overall
result is `BLOCKED`, but for two reasons unrelated to this feature and
specific to this sandboxed session, not the code: (1) the publish-state
metadata's recorded `artifact_path` is an absolute Mac path
(`/Users/olugbengaodeyemi/StrategicDigest/...`) that does not textually
match how this file resolves inside this session's mounted filesystem
(`/sessions/.../mnt/StrategicDigest/...`), tripping the pre-existing
metadata-consistency check; (2) the website repository
(`/Users/olugbengaodeyemi/Downloads/personalwebsite`) is not mounted in this
session, so the pre-existing website-repo-exists check fails. Both checks
predate this feature, are untouched by it, and will pass normally when run
natively on the Mac where the paths and the website repo actually match.

## 5. Remaining blockers/limitations

- The website's blog renderer does not yet read `seo_title`, `topic_cluster`,
  `internal_link_targets`, or `suggested_related_posts` -- this phase only
  produces and validates that metadata on the StrategicDigest side, per the
  instruction not to touch the website repo. Wiring the website to actually
  render topic-cluster hub pages and the new internal/related links is
  separate future work there.
- `secondary_keywords`/`internal_link_targets`/`suggested_related_posts`
  count-out-of-range is intentionally a warning, never a blocker (see
  README policy table); revisit if stricter enforcement is wanted later.
- `blog/quality.py`'s generation-time retry loop does not check SEO
  metadata, so a model that repeatedly returns invalid metadata will not
  trigger a revision attempt the way a factual-grounding failure would; it
  will simply reach `blog:check` with warnings/blockers for a human to see.
- Two environment-only items from this sandboxed session, not from the
  code: a stale, empty `.git/index.lock` I could not delete due to a
  filesystem permission quirk (run `rm -f .git/index.lock` locally before
  your next `git add`/`commit`), and the `blog:check` "BLOCKED" result
  above being an artifact of running outside the Mac's real path/repo
  layout.
