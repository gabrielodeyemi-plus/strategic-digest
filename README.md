# Strategic Intelligence Digest

A daily 7am agent that pulls articles from RSS feeds, synthesizes a strategic
morning briefing with Claude, pushes it to Notion, emails an HTML digest, and
creates a publication-ready blog article.

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

The briefing is delivered to your inbox and saved to Notion exactly as before.
After those delivery attempts, an independent blog pipeline transforms it into a
standalone 900-to-1,500-word strategy article and publishes a local Markdown
draft by default.

---

## Architecture

```text
topics.yaml → fetcher.py → synthesizer.py → Digest
                                            ├─ notion_pusher.py
                                            ├─ emailer.py
                                            └─ blog/
                                               ├─ BlogArticleTransformer
                                               ├─ BlogQualityGate
                                               └─ WebsiteBlogPublisher
                                                  ├─ local Markdown
                                                  └─ repository adapter
```

**Key design decisions:**

- **RSS over news APIs.** No API keys required for sources, no rate limits, fully customizable. feedparser handles the parsing; you control the signal by choosing the feeds.
- **Topics as config, not code.** Add or remove topics by editing `topics.yaml`. No code changes needed to track a new industry, company, or theme.
- **One synthesis call, not many.** All articles from all topics go into a single Claude call with a chief-of-staff prompt. This produces a unified briefing that connects dots across topics — the highest-value output that individual article summaries can't achieve.
- **Gmail App Password, not OAuth.** Sending a daily email is a write-only operation. App passwords are simpler to set up and don't require maintaining OAuth token refresh.
- **Blog publishing is an adapter.** The digest generator, Notion publisher, and
  email sender do not depend on website publishing. A blog failure is logged and
  stored as failed metadata, but cannot stop the established outputs.
- **Local-first website integration.** The current website is a separate
  Vite/React/Vercel repository with no `/blog` route or Markdown content loader.
  Local draft output is therefore the safe default until that site can render
  blog content.

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

## Blog publishing

The blog transformer selects the day's central theme and produces:

- a specific headline and one-sentence dek;
- a short excerpt and SEO description;
- a source-grounded article with three to five sections;
- a final `The Strategic Read` section;
- tags, slug, canonical URL, source digest ID/date, and publication status.

It applies deterministic checks for length, structure, banned phrases, em
dashes, unknown source IDs, unknown links, and malformed Markdown. By default, a
second Claude call checks factual grounding against the exact digest and RSS
source cards. A failed article gets one revision attempt, controlled by
`BLOG_MAX_ATTEMPTS`.

The default output is:

```text
output/blog/YYYY-MM-DD-article-slug.md
output/blog/publish-state.json
```

The Markdown file includes portable YAML frontmatter. `publish-state.json` is
keyed by digest date and records title, slug, date, source digest ID/date,
canonical URL, artifact path, publisher, and status.

### SEO and discoverability metadata

Every generated post also carries a second, smaller layer of frontmatter
whose purpose is discoverability rather than editorial content: it clarifies
the article's strategic theme, gives the website material for internal
linking, and lets the site build topic authority over time. This is not
keyword stuffing; `blog/transformer.py`'s prompt is explicit that these
fields must never distort or pad the article to fit them, and that nothing
in them may be invented.

```yaml
seo_title: "AI Trust, Governance, and Competitive Advantage in Enterprise Adoption"
topic_cluster: "AI Governance"
primary_keyword: "AI governance and trust"
secondary_keywords:
  - "enterprise AI adoption"
  - "AI data control"
  - "AI risk management"
  - "AI competitive advantage"
internal_link_targets:
  - label: "Strategic Digest"
    url: "/blog"
    reason: "The post is part of the Strategic Digest analysis archive."
  - label: "AI Strategy & Operations Consulting"
    url: "/ai-consulting"
    reason: "The article discusses AI adoption, governance, and operating advantage."
    status: "planned"
suggested_related_posts:
  - title: "The Trust Gate: Why AI's Winners Will Be Decided by Control, Not Capability"
    url: "/blog/ai-trust-gate-control-not-capability"
    reason: "Related analysis on AI trust and enterprise governance."
```

| Field | Purpose |
| --- | --- |
| `seo_title` | An explicit, search-friendly rendering of the story, distinct from the editorial `title`. `title` can be evocative; `seo_title` states the topic plainly. |
| `topic_cluster` | Exactly one value from a fixed, controlled list (below), so the site can group posts into stable topic hubs instead of an ever-growing free-text tag cloud. |
| `primary_keyword` | One specific, natural phrase describing the article's core topic. |
| `secondary_keywords` | 3 to 7 natural phrases a reader would actually search for. Not a keyword-density list; each entry should read like something a person would type. |
| `internal_link_targets` | 1 to 4 recommended links from a fixed target universe (below), each with a `label`, `url`, `reason`, and an optional `status: "planned"` for pages that don't exist on the site yet. |
| `suggested_related_posts` | 0 to 3 links to *other* existing StrategicDigest posts, each with `title`, `url`, `reason`. Never invented; see below. |

**Controlled topic clusters** (`blog/seo.py:TOPIC_CLUSTERS`):

AI Operating Systems · AI Agents · Strategy & Operations · AI Governance ·
Logistics & Workflow Automation · Strategic Intelligence · Markets &
Business Models · Public Sector & Policy · Leadership & Organizational
Change · Corporate Strategy · Technology Infrastructure

A `topic_cluster` outside this exact list is treated as invalid, not as a
new cluster to adopt silently, so the taxonomy can't drift post by post.

**Internal link target universe** (`blog/seo.py:INTERNAL_LINK_TARGET_UNIVERSE`):

`/`, `/blog`, `/ai-consulting`, `/projects/vigil`, `/projects/strategicdigest`,
`/projects/churnagent`, `/blog/tag/artificial-intelligence`,
`/blog/tag/enterprise-governance`, `/blog/tag/corporate-strategy`,
`/blog/tag/strategy-operations`, `/blog/tag/logistics-workflow-automation`,
`/blog/tag/strategic-intelligence`

Some of these pages (e.g. `/ai-consulting`) don't exist on the live site
yet. They're still valid recommendations, marked `status: "planned"`, since
the point is to record the *intended* information architecture as posts are
written, not to only ever link to what already happens to exist.
`suggested_related_posts` works the other way around: it may only reference
posts StrategicDigest already knows about (every other `.md` file in
`output/blog/`), resolved automatically at generation and check time. A post
can never suggest a URL for content that doesn't exist anywhere.

**Where this is validated, and the warn-vs-blocker policy.** `blog/seo.py`
holds the pure validation logic; `blog/approval.py` and `blog/check.py` share
it through `_evaluate_seo_readiness` so `blog:check` and `blog:approve` can
never disagree, the same pattern already used for source-coverage checks.
The policy is rollout-safe on purpose, so every post generated before this
feature existed keeps passing both commands unmodified:

- **Warning only** (visible in the report, never blocks): any of the six
  fields is missing entirely, or `secondary_keywords`/`internal_link_targets`/
  `suggested_related_posts` has fewer or more entries than the recommended
  range.
- **Blocks `blog:check` and `blog:approve`**: `topic_cluster` is present but
  not one of the controlled values; any field is present but structurally
  malformed (wrong type, missing required keys); or a URL in
  `internal_link_targets` or `suggested_related_posts` is not on an allowed
  list (an invented internal path, or a related post that doesn't actually
  exist).

`blog:check`'s report gets a new section for this:

```text
SEO / discoverability:
PASS discoverability metadata present and valid
```

or, for an older/incomplete draft:

```text
SEO / discoverability:
WARN seo_title is missing.
WARN topic_cluster is missing.
WARN primary_keyword is missing.
WARN secondary_keywords is missing.
WARN internal_link_targets is missing.
```

**How this supports website discoverability.** These fields are the
handoff contract for the website repository to consume when it renders a
post: `topic_cluster` groups posts into stable topic hubs, `internal_link_targets`
and `suggested_related_posts` give it concrete, non-invented internal links
to render, and `seo_title`/`primary_keyword`/`secondary_keywords` describe
the article's intended search identity distinct from its editorial
headline. This task only produces and validates that metadata on the
StrategicDigest side; wiring the website's blog renderer to actually read
and display these new fields is separate, future website-repo work.

### Configuration

```dotenv
BLOG_PUBLISH_ENABLED=true
BLOG_PUBLISH_MODE=local
BLOG_AUTHOR="Gabriel Odeyemi"
BLOG_BASE_URL=https://gabrielodeyemi.com
BLOG_OUTPUT_DIR=./output/blog
BLOG_DEFAULT_STATUS=draft
BLOG_EXISTING_POST_ACTION=skip
BLOG_MIN_WORDS=900
BLOG_MAX_WORDS=1500
BLOG_QUALITY_REVIEW_ENABLED=true
BLOG_MAX_ATTEMPTS=2
BLOG_APPROVAL_REQUIRED=true
BLOG_WEBSITE_REPO_PATH=/Users/olugbengaodeyemi/Downloads/personalwebsite
BLOG_WEBSITE_CONTENT_DIR=src/content/blog
```

`BLOG_EXISTING_POST_ACTION=skip` prevents a second transformation or post for
the same digest date. Set it to `update` to replace that day's artifact.

`BLOG_APPROVAL_REQUIRED=true` prevents the daily publisher from writing directly
to the website repository, even if repository mode is selected. Keep this
enabled until live publishing automation has a separately reviewed approval and
deployment design.

No secrets are required for local publishing beyond the existing Anthropic key.
Do not put tokens or API keys in Git.

### Commands

Generate and save the raw digest without sending email, writing Notion, or
creating a blog article:

```bash
.venv/bin/python main.py --digest-only
```

Transform an existing digest into a local draft. `--dry-run` guarantees that no
website repository is touched:

```bash
.venv/bin/python blog_cli.py output/digests/2026-07-06.md \
  --date 2026-07-06 --dry-run
```

Replace an existing same-day local artifact:

```bash
.venv/bin/python blog_cli.py path/to/digest.md \
  --date 2026-07-06 --dry-run --force
```

### Checking readiness before you approve

`blog:check` is a **non-mutating** preflight: it answers "is this draft ready
to approve and publish?" without touching any file, state, or repository. Run
it before every approval:

```bash
.venv/bin/python main.py blog:check --date 2026-07-06
```

Example output:

```text
── Blog readiness check ───────────────────────────────
Title: The Trust Gate: Why AI's Winners Will Be Decided by Control, Not Capability
Date: 2026-07-06
Slug: ai-trust-gate-control-not-capability
Status: draft
Word count: 1,204
Read time: 5 min

Content:
PASS title present
PASS slug valid
PASS date matches requested date
PASS status is draft
PASS article body present
PASS quality gate passed

Sources:
PASS structured frontmatter sources present
PASS 5 valid source URLs
PASS visible "## Sources" section present
PASS source coverage met: 5 valid, 3 expected

Website target:
PASS website repo exists
PASS website content directory exists
WARN destination file already exists; approval requires --force

Result: READY with warnings
```

`blog:check` reuses the exact same source-readiness, quality-gate, and
website-path logic as `blog:approve`, so it and `blog:approve --dry-run` can
never disagree about whether a post is ready.

**Warning vs. failure semantics:**

- `PASS` / `FAIL` lines are pass/fail checks. Any `FAIL` blocks approval and
  produces a non-zero exit code (missing/invalid frontmatter, a date
  mismatch, a failed quality gate, missing or insufficient sources, a missing
  website repo or content directory, no post found, or more than one post
  found for the date).
- `WARN` lines are advisories that do **not** block approval and do **not**
  change the exit code — for example, the destination file already existing
  (approval will require `--force`) or the post's status already being
  `"published"` (re-approving will re-copy over the live file).
- Exit code `0` means approval-ready, even with warnings. Exit code `2` means
  a real blocker exists and `blog:approve` will fail for the same reason.

**Recommended workflow:**

```bash
.venv/bin/python main.py blog:check --date 2026-07-06
# review the Markdown draft
.venv/bin/python main.py blog:approve --date 2026-07-06
# build/commit/push/PR the website repo
```

### Approving a post for the website

Generated articles remain local drafts until Gabriel explicitly approves one.
Preview the handoff without changing either repository:

```bash
.venv/bin/python main.py blog:approve --date 2026-07-06 --dry-run
```

The dry run displays the title, slug, current status, source, destination, and
whether a destination file already exists.

Approve and copy a reviewed draft:

```bash
.venv/bin/python main.py blog:approve --date 2026-07-06
```

The approval command:

1. Requires exactly one generated Markdown file for the requested date.
2. Validates YAML frontmatter, required title/date/status fields, slug, and date.
3. Requires publication metadata proving the article passed editorial review.
4. Changes only the frontmatter status from `draft` to `published`.
5. Updates the local generated artifact and copies the same approved content to
   the website's `src/content/blog/` directory.
6. Records approval and website handoff metadata in `publish-state.json`.
7. Stops without committing, pushing, or deploying anything.

If the destination already exists, approval stops before modifying either file.
After reviewing the collision, allow replacement explicitly:

```bash
.venv/bin/python main.py blog:approve --date 2026-07-06 --force
```

Successful approval records:

- `approved_at`
- `approved_file_path`
- `website_repo_path`
- `website_content_path`
- `website_slug`
- `website_local_url`
- `status` and `publish_status` as `copied_to_website_repo`

It then prints the manual validation and release commands:

```bash
cd /Users/olugbengaodeyemi/Downloads/personalwebsite
npm run build
git diff
git add src/content/blog/YYYY-MM-DD-slug.md
git commit -m "Publish Strategic Digest: YYYY-MM-DD"
git push
```

The existing Vercel deployment workflow handles the site after the reviewed Git
push. `blog:approve` itself does not run Git or Vercel commands — it stops
after copying the file. The optional `blog:pr` command below automates the
Git/GitHub half of that handoff; production deployment always stays manual.

### Opening a GitHub PR (`blog:pr`)

`blog:pr` automates the Git/GitHub mechanics for a post that has **already**
been approved and copied into the website repo by `blog:approve`. It never
generates or approves content, and it never runs a production deploy — it
opens a pull request so Gabriel can review the Vercel preview and merge
manually.

```bash
.venv/bin/python main.py blog:pr --date 2026-07-06
```

Optional flags: `--dry-run`, `--force`, `--branch-name <name>`, `--base main`,
`--no-push`, `--no-build`.

**What it checks, in order (enforced in both dry-run and real runs unless
noted):**

1. Exactly one post exists for the date and its frontmatter `status` is
   `"published"` (i.e. `blog:approve` has already run).
2. `publish-state.json` shows `publish_status: copied_to_website_repo`.
3. The approved Markdown file actually exists in
   `BLOG_WEBSITE_CONTENT_DIR` inside the website repo.
4. The website repo has no dirty changes other than that one file (`git
   status --porcelain`); anything else blocks unless `--force`.
5. The target branch does not already exist, unless `--force`.
6. *(Real runs only)* `gh --version` and `gh auth status` succeed. If `gh`
   isn't installed or isn't authenticated, the command fails with install /
   `gh auth login` instructions **before** touching Git.
7. *(Real runs only, unless `--no-build`)* `npm run build` succeeds in the
   website repo. A failed build blocks branch creation, commit, and push.

**On success it:**

1. Creates a deterministic branch, e.g.
   `strategic-digest/2026-07-06-ai-trust-gate-control-not-capability`
   (override with `--branch-name`).
2. Stages **only** the one approved blog post file — never `git add -A` or
   unrelated infrastructure files.
3. Commits as `Publish Strategic Digest: 2026-07-06`.
4. Pushes the branch (unless `--no-push`) and opens a PR against
   `BLOG_PR_BASE_BRANCH` (default `main`, override with `--base`) with a body
   containing the post title, date, slug, file paths, source-readiness
   summary, build result, and a manual review checklist (article body,
   Sources section, `/blog` and `/blog/:slug` Vercel previews, then merge).

**Dry run** (`--dry-run`) reports the branch name, the file(s) that would be
staged, whether the build would run, and whether `gh` is available/
authenticated — without creating a branch, committing, pushing, or opening a
PR. A successful dry run is a reliable signal the real run will also succeed
structurally.

**`--no-push`** creates the local branch and commit but stops before pushing
or opening a PR — useful for inspecting the commit locally first.

StrategicDigest never runs a Vercel production deploy. `blog:pr` relies on
GitHub/Vercel preview deployment; Gabriel reviews the preview and merges the
PR manually.

**Configuration:**

```dotenv
BLOG_PR_ENABLED=true
BLOG_PR_BASE_BRANCH=main
BLOG_PR_BRANCH_PREFIX=strategic-digest
BLOG_PR_RUN_BUILD=true
```

(`BLOG_WEBSITE_REPO_PATH` and `BLOG_WEBSITE_CONTENT_DIR` are the same
variables `blog:approve` already uses.)

**Requirements:** [GitHub CLI](https://cli.github.com) installed and
authenticated (`gh auth login`). No GitHub token is stored in this project —
`gh` handles authentication using your existing local session.

**Recommended end-to-end workflow:**

```bash
# 1. Generate the digest normally (cron or manual run)
# 2. Preflight check — non-mutating
.venv/bin/python main.py blog:check --date 2026-07-06
# 3. Review the Markdown draft
# 4. Approve and copy to the website repo
.venv/bin/python main.py blog:approve --date 2026-07-06
# 5. Open the PR
.venv/bin/python main.py blog:pr --date 2026-07-06
# 6. Review the GitHub PR and Vercel preview
# 7. Merge manually
```

Run tests:

```bash
.venv/bin/python -m unittest discover -v
```

### Failure behavior

- Notion, email, and blog delivery each have independent error handling.
- The blog path always runs after the existing Notion and email attempts.
- Blog configuration, transformation, review, or publisher failures never
  propagate into those existing outputs.
- Failures are logged and recorded in `publish-state.json` when possible.
- A missing or unusable website repository falls back to local Markdown.
- Approval failures are CLI-only and cannot affect the scheduled digest,
  Notion, or email workflow.

## Connecting gabrielodeyemi.com

The website lives separately at
`gabrielodeyemi-plus/gabrielodeyemi.com`. It is a static React 19 SPA built by
Vite and deployed on Vercel. Its `/blog` and `/blog/:slug` routes load Markdown
from `src/content/blog/` at build time and exclude drafts from production.

The explicit approval command (`blog:approve`) is the cross-repository
boundary; `blog:pr` (see above) automates the Git/GitHub half of the handoff
— branch, commit, push, PR — but only after a human has approved the post.
Production deployment remains manual by design until these decisions are
made:

1. Who gives final editorial approval and how that approval is authenticated.
2. ~~Whether approved posts should open pull requests or commit directly~~ —
   resolved: `blog:pr` always opens a PR against `BLOG_PR_BASE_BRANCH`; it
   never commits directly to that branch.
3. Which CI checks and Vercel preview must pass before production deployment.
4. How failed builds, rejected posts, and deployment rollbacks are reported.

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
| Persistence | Notion API + local JSON | Searchable digest archive and idempotent blog state |
| Scheduling | macOS launchd | Native scheduler, survives reboots |

---

## Project structure

```
main.py           — orchestrator: fetch → synthesize → Notion → email → blog
fetcher.py        — RSS feed fetcher with 48-hour recency filter
synthesizer.py    — Claude strategic briefing prompt and API call
notion_pusher.py  — Notion page creation from markdown briefing
emailer.py        — HTML email formatter and Gmail SMTP sender
digest_models.py  — typed Digest and source-card model
blog/             — transformer, quality gate, state, and publisher adapters
  approval.py     — blog:approve: validates and copies a draft to the website repo
  check.py        — blog:check: non-mutating readiness preflight (reuses approval.py logic)
  pr.py           — blog:pr: opens a GitHub PR for an already-approved, already-copied post
blog_cli.py       — existing-digest blog dry-run/local publish command
tests/            — blog reliability, approval, readiness-check, and PR-workflow tests
topics.yaml       — topic and feed configuration (edit this)
install.sh        — venv setup + launchd plist generator
```
