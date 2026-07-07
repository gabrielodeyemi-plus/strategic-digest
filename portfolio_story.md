# StrategicDigest — Portfolio Story

------------------------------------------------------------------------

## Resume Bullet

Built StrategicDigest, a daily AI intelligence and publishing agent that fetches RSS sources across configurable topic areas, synthesizes cross-topic executive briefings with Claude, delivers email and Notion outputs, and converts approved digests into source-grounded blog posts through readiness checks, manual approval gates, and a GitHub PR publishing workflow.

------------------------------------------------------------------------

## Short Resume Version

Built StrategicDigest, a daily AI intelligence agent that synthesizes RSS sources into executive briefings, delivers email and Notion outputs, and converts approved digests into source-grounded blog posts through a guarded publishing workflow.

------------------------------------------------------------------------

## LinkedIn / Portfolio Summary

StrategicDigest is a personal AI intelligence and publishing system I built to turn fragmented daily information into decision-ready analysis.

The system runs as a daily agent. It pulls articles from configurable RSS topic areas, synthesizes them with Claude into a cross-topic executive briefing, sends the result by email, archives it in Notion, and generates a source-grounded blog draft for my personal website.

The important design choice was not simply using AI to summarize articles. The system is built to identify the strategic pattern across topics: what changed, why it matters, what weak signals are emerging, and what actions should follow.

After the initial digest workflow worked, I extended it into a controlled publishing system. The blog pipeline transforms a digest into a polished article, preserves source metadata, enforces a visible Sources section, runs readiness checks, requires explicit approval, copies the approved post to my website repository, and supports a GitHub PR workflow for review before publication.

StrategicDigest demonstrates my ability to move from information overload to an operating system: source ingestion, synthesis, publishing, governance, human review, and deployment control.

------------------------------------------------------------------------

## Interview Story: Behavioral / General

"I was drowning in newsletters, tabs, RSS feeds, market stories, AI updates, and strategy pieces. The problem was not access to information. The problem was synthesis. I did not need more articles. I needed a daily briefing that helped me understand what mattered, what connected across domains, and what I should actually do next.

So I built StrategicDigest.

At first, the system was simple: every morning at 7am, it pulled articles from RSS feeds across the topics I care about, synthesized them with Claude, and sent me a styled HTML email. I also pushed the digest to Notion so I had a searchable archive.

The key design decision was using one synthesis call across all articles rather than summarizing each article separately. Per-article summaries would only give me a faster version of the same information overload. The higher-value output was the insight that exists across topics: the connection between an AI infrastructure story, a markets signal, a business strategy shift, and a leadership implication.

So I wrote the prompt like a chief-of-staff briefing, not a summarization request. The system has to answer: what matters today, what pattern connects the stories, what weak signals should I watch, and what should I do in the next 48 hours?

Once the digest worked, I extended it into a publishing workflow. The system now generates a public blog draft from the digest, preserves the underlying sources, adds a visible Sources section, runs quality and readiness checks, and requires explicit approval before copying the post into my website repository. From there, a GitHub PR workflow can route the article through review before publication.

That evolution matters because it turned the project from a personal productivity tool into a governed AI publishing pipeline. It is not just generating text. It is managing source integrity, quality gates, human approval, version control, and deployment boundaries.

The result is a daily AI intelligence system that moves from raw information to private briefing to public analysis, with safety controls built into the operating model."

------------------------------------------------------------------------

## Technical PM Interview Story

"I would frame StrategicDigest as a product problem because that is how I approached it.

### Problem statement

I was spending 20 to 30 minutes every morning triaging information across newsletters, RSS feeds, websites, and saved articles. The input volume was high, but the output was weak. Reading more did not necessarily improve my decisions.

The product requirement became: build a system that converts raw daily information into a prioritized strategic briefing before I start the day.

The unit of value was not articles read. It was decision quality and actionability.

### MVP scope

I identified three failure modes upfront.

First, information overload: too many articles and no synthesis.

Second, false signal: low-stakes items getting treated as important.

Third, adoption failure: if the system required manual effort every morning, I would stop using it.

The MVP constraints were clear:
- zero manual steps after setup
- daily delivery
- email-first reading experience
- Notion archive
- under four minutes to read
- configurable topics
- low operating cost

Everything else was cut.

### Architecture

The data layer starts with RSS. I chose RSS instead of paid news APIs because RSS is open, cheap, flexible, and puts curation under my control. The signal quality comes from choosing the right sources, not from outsourcing editorial judgment to a third-party news API.

The pipeline is:

RSS feeds → article collection → Claude synthesis → Digest object → Notion output → email output → blog draft pipeline

The blog pipeline is isolated from the original email and Notion path. That means a blog failure cannot break the daily digest. This was an important reliability design decision because the original workflow had to remain intact while I added publishing capability.

### Synthesis design

The central technical choice was single-call synthesis. A naive implementation would summarize each article separately, then combine the summaries. I rejected that.

The reason is that separate summaries preserve the silo structure of the original articles. They do not force the model to reason across domains. I wanted the system to identify the strategic thread across unrelated stories.

So the system passes the day's articles into one synthesis context and asks Claude to brief a senior executive. The output is structured around:
- what matters today
- the connecting thread
- weak signals to watch
- recommended actions

That prompt structure acts like a product spec. It defines the user experience and prevents the output from becoming a generic news summary.

### Blog publishing extension

After the private digest worked, I added a public publishing layer.

The new requirement was: keep the email and Notion digest unchanged, but also transform the digest into a blog-ready article for gabrielodeyemi.com.

I designed this as a separate adapter-based pipeline:

Digest → BlogArticleTransformer → BlogQualityGate → local Markdown draft → approval workflow → website repository → GitHub PR workflow

The system writes a Markdown file with YAML frontmatter, including title, subtitle, slug, date, tags, SEO description, canonical URL, status, and structured source metadata.

The blog article stays in draft status by default.

### Source integrity and approval gates

One of the most important lessons from this project was that polished AI writing is not enough for public publishing. The article needs visible source grounding.

So I added deterministic source preservation. Source URLs are carried from the RSS article metadata into the digest model, then into the blog frontmatter and a visible Sources section at the bottom of the article.

The approval gate blocks publication unless:
- structured source metadata exists
- valid source URLs are present
- a visible Sources section exists
- minimum source coverage is met
- the quality gate passes
- the destination state is safe

This moved the system from 'AI writes a blog post' to 'AI produces a governed publishing artifact.'

### Operational workflow

The workflow now supports:

- `blog:check`: non-mutating readiness check
- `blog:approve`: explicit approval that changes status to published and copies the post to the website repository
- `blog:pr`: creates a GitHub PR workflow for the approved website change
- `blog:regenerate`: regenerates a blog draft from a persisted digest snapshot

The important operating principle is human editorial control. The system can generate and validate, but it does not silently publish.

### Reliability

The original email and Notion workflow is protected. Blog publishing is isolated. If the blog pipeline fails, the digest still gets emailed and pushed to Notion.

The system also writes metadata about publication state, approval state, and website handoff. Generated artifacts and digest snapshots are ignored by Git, while source, tests, and workflow code are version-controlled.

### Validation

The current system has automated tests covering:
- blog generation
- quality gates
- source preservation
- approval behavior
- duplicate prevention
- readiness checks
- PR workflow safety
- simulated website failure
- regeneration behavior

The system also runs Python compilation validation.

### What I would do differently at scale

If I were productizing this for multiple users, I would move the scheduler from local launchd to a cloud job, likely EventBridge or a similar scheduler. I would store digest state in a database instead of local files. I would add a user-facing configuration UI for topics and sources. I would also add feedback loops so users could mark which briefings were useful, which sources were noisy, and which recommendations led to action.

The scalable version would separate ingestion, synthesis, evaluation, publishing, and analytics into distinct services.

But for the current use case, the local-first architecture is appropriate. It is cheap, inspectable, reliable enough for one user, and easy to modify."

------------------------------------------------------------------------

## Product / Strategy Interpretation

StrategicDigest is not just an automation project. It is a miniature AI operating system.

It combines:
- source ingestion
- editorial judgment
- executive synthesis
- workflow automation
- quality control
- source governance
- approval management
- content publishing
- version control
- deployment handoff

The project demonstrates a broader consulting lesson: AI becomes valuable when it is embedded into a workflow with clear inputs, outputs, controls, and ownership.

The technology is not the differentiator by itself. The operating model is.

------------------------------------------------------------------------

## Consulting Relevance

StrategicDigest is directly relevant to AI consulting because it shows how to move from AI experimentation to governed workflow implementation.

The same pattern applies to client work:

1. Identify a recurring information or workflow problem.
2. Define the business output that matters.
3. Design the AI role in the workflow.
4. Preserve source integrity and auditability.
5. Add human review at the right decision point.
6. Automate the repeatable steps.
7. Build quality gates.
8. Version and deploy safely.
9. Measure whether the workflow improves.

This is the core of serious AI adoption: not just prompting, but operating design.

------------------------------------------------------------------------

## STAR Version

### Situation

I was spending too much time every morning reading fragmented information across AI, business strategy, markets, leadership, and policy sources, but the process did not reliably produce decision-ready insight.

### Task

I wanted to build a daily system that could collect relevant sources, synthesize them into a strategic briefing, deliver the briefing automatically, and eventually support public publishing without sacrificing source integrity or human review.

### Action

I built StrategicDigest as a daily AI agent. It pulls RSS articles from configurable topics, synthesizes them with Claude into an executive-style briefing, emails the digest, pushes it to Notion, and archives the output.

After the original workflow worked, I extended it into a blog publishing system. I added a transformer that converts the digest into a long-form article, a quality gate, deterministic source preservation, a visible Sources section, a readiness check command, an explicit approval command, and a GitHub PR workflow for website publishing.

I also separated the blog pipeline from the original digest delivery path so that publishing failures cannot interrupt email or Notion delivery.

### Result

The system now runs as a daily intelligence workflow and supports a controlled path from private briefing to public blog article. It demonstrates source-grounded AI writing, human approval, publication metadata, website handoff, and PR-based deployment control.

The first Strategic Digest blog post is live on my personal website, and the operational workflow is now version-controlled, tested, and repeatable.

------------------------------------------------------------------------

## One-Minute Interview Version

"I built StrategicDigest because I wanted to solve my own information overload problem. I was reading across AI, strategy, markets, leadership, and policy, but the process produced too much input and not enough synthesis.

So I built a daily AI agent. It pulls RSS articles from configurable topic areas, sends them to Claude in a single synthesis call, and produces an executive-style briefing with the key stories, connecting thread, weak signals, and recommended actions. It emails the briefing to me and archives it in Notion.

Then I extended it into a publishing workflow. The system can now turn a digest into a source-grounded blog draft, preserve source metadata, enforce a visible Sources section, run readiness checks, require manual approval, copy the approved article into my website repo, and support a GitHub PR workflow.

The biggest lesson is that AI value is not just generation. It is workflow design. The system works because the inputs, outputs, quality gates, human approval points, and deployment path are all explicit."

------------------------------------------------------------------------

## Strong Interview Closing Line

"StrategicDigest taught me that the real value of AI is not summarization. It is turning fragmented information into an operating rhythm: collect, synthesize, decide, publish, and improve."
