## Project Ecosystem

> **Status: Prototype / Superseded**
> Emre is building a replacement outbound service using **RevenueBase** (contact discovery) and **EmailBison** (email sequencing). That service will be exposed to the synter-media AI agent via MCP. Do not invest in deep integrations or new features for this Python engine — maintain only, or migrate logic to Emre's service when ready.

This is the **jobs-outreach-engine** — a companion outbound service for Synter. It is intentionally a sibling to synter-media, not part of it.

| Project | Relationship | Rules of engagement |
|---------|-------------|---------------------|
| `synter-media` | Parent platform. Shares Doppler config (`synter-media/prd`). This engine generates leads that become Synter customers. | Never read/write synter-media's Postgres DB. Coordinate on Doppler secret naming to avoid collisions. When the outreach engine needs a new agent tool exposed, add it to synter-media's agent route. |
| `mcp-server` | The public API for synter-media. Not related to this engine directly. | No direct dependency. |
| All others | Unrelated. | No cross-project dependencies. |

**This engine's SQLite DB is standalone. Do not attempt to merge it into synter-media's Prisma schema without explicit instruction.**

---

## CRITICAL: Workspace & Account Verification — HIGH RISK PROJECT

**This engine sends real emails, LinkedIn messages, and tweets to real people. A misconfigured run can spam hundreds of contacts and cannot be undone.**

### Required checks before every run

| Check | Expected value | Action if wrong |
|-------|---------------|-----------------|
| Working directory | `/Users/joelhorwitz/work/jobs-outreach-engine/` | STOP — ask user to confirm |
| Doppler project | `synter-media`, config `prd` — intentional for this engine | Warn user if credentials missing |
| Email target | Real leads from Sumble/CSV — NOT Synter team members or test accounts | Verify before sending |
| Twitter account | `@JSHorwitz` personal account only | Never post as @synter or any brand account |
| GitHub | `jobs-outreach-engine` repo only | Do NOT push to synter-media |

### Mandatory safety rules

- **ALWAYS use `--dry-run` by default.** Never remove `--dry-run` unless the user explicitly says "send for real" or "go live".
- **Always show a preview** of what would be sent (lead count, email subject, recipient sample) and ask for confirmation before a live run.
- **Never import or send to Synter employees, investors, or team contacts.**
- **Rate limits**: Max 20 leads/run due to SpyFu limits. Confirm count before running.
- **LinkedIn automation**: Playwright-based — only run when user is present to handle CAPTCHAs.
- **Email send times**: Resend sender auto-schedules emails for business hours (8am-6pm PT, Mon-Fri). If triggered outside that window, emails queue for 9:15am PT next business day. NEVER bypass this guardrail.
- **X API credits**: Pay-per-usage. Check credit balance before bulk pulls (followers, liking_users, retweeted_by). ~$25-50 covers 13K follower pulls + enrichment.

---

# Job Posting Growth Engine — AI Agent Guide

## Project Overview

Automated cold outbound engine that discovers companies hiring growth/marketing
leadership roles (via Sumble), enriches them with competitive intelligence
(SpyFu, BuiltWith, Firecrawl), and sends a narrative-driven email sequence
via Loops.so or exports to Instantly.ai.

## Tech Stack

- **Language:** Python 3.11+
- **Framework:** Plain Python with SQLAlchemy ORM
- **Database:** SQLite (local, file-based)
- **Email:** Loops.so API + Instantly.ai CSV export
- **Enrichment:** SpyFu (PPC/SEO), BuiltWith (tech stack), Firecrawl (homepage)
- **AI:** OpenAI GPT-4o for email generation
- **LinkedIn:** Playwright-based Sales Navigator automation

## API Keys & Secrets

### ⚠️ CRITICAL: All Keys Are in Doppler

**SpyFu, OpenAI, Loops, Hunter, and all other API keys are managed in Doppler.**

```bash
# View all secrets
doppler secrets --project synter-media --config prd

# Get specific key
doppler secrets get SPYFU_API_ID --project synter-media --config prd --plain
doppler secrets get SPYFU_SECRET_KEY --project synter-media --config prd --plain

# Run engine with Doppler-injected secrets
doppler run --project synter-media --config prd -- python -m engine.pipeline --followups --dry-run
```

**Key mapping (Doppler → .env):**

| Doppler Key | .env Variable | Description |
|-------------|---------------|-------------|
| `SPYFU_API_ID` | `SPYFU_API_ID` | SpyFu API ID (Basic auth username) |
| `SPYFU_SECRET_KEY` | `SPYFU_SECRET_KEY` | SpyFu secret key (Basic auth password) |
| `OPENAI_API_KEY` | `OPENAI_API_KEY` | OpenAI for email generation |
| `LOOPS_API_KEY` | `LOOPS_API_KEY` | Loops.so email sending |
| `HUNTER_API_KEY` | `HUNTER_API_KEY` | Hunter.io email enrichment |
| `SUMBLE_API_KEY` | `SUMBLE_API_KEY` | Sumble job discovery |

**DO NOT hardcode API keys.** Use Doppler or `.env` file.

## Project Structure

```
growth-engine/
├── engine/
│   ├── ai/
│   │   ├── email_writer.py        # Initial cold email generation
│   │   ├── followup_writer.py     # Follow-up email with SpyFu data
│   │   └── linkedin_writer.py     # LinkedIn message generation
│   ├── clients/
│   │   ├── spyfu.py               # SpyFu API client (PPC/SEO intelligence)
│   │   ├── hunter.py              # Hunter.io email enrichment
│   │   ├── sumble.py              # Sumble job discovery
│   │   ├── slack.py               # Slack notifications
│   │   └── csv_import.py          # CSV lead import
│   ├── db/
│   │   ├── database.py            # SQLite init
│   │   └── models.py              # SQLAlchemy models
│   ├── outreach/
│   │   ├── loops_sender.py        # Loops.so contact upsert + enrichment
│   │   └── linkedin_sender.py     # LinkedIn Sales Navigator automation
│   ├── x/
│   │   ├── content_calendar.json  # 4-week X content calendar
│   │   ├── scheduled_post.py      # Automated posting from calendar
│   │   ├── engagement_scanner.py  # Find high-engagement tweets
│   │   ├── quote_retweet.py       # Quote RT with 3-tier fallback
│   │   ├── post_content.py        # Core tweet publishing
│   │   ├── tweet_lookup.py        # Tweet metrics lookup
│   │   └── get_followers.py       # Follower analysis
│   ├── config.py                  # Pydantic settings
│   └── pipeline.py                # Main pipeline (run, run_followups, main)
├── docs/
│   └── 18-email-sequence.md       # Full email sequence spec
├── data/                          # SQLite DB + LinkedIn session
├── logs/                          # Pipeline logs
├── scripts/                       # Utility scripts
├── templates/                     # MJML email templates
└── tests/                         # Tests
```

## Commands

```bash
# Run initial outreach pipeline
python -m engine.pipeline --channel email --dry-run

# Run follow-up enrichment (SpyFu → Loops contact properties)
python -m engine.pipeline --followups --dry-run

# Run with Doppler secrets
doppler run --project synter-media --config prd -- python -m engine.pipeline --followups

# Check Sumble API connection
python -m engine.pipeline --check

# Import from CSV (bypass Sumble)
python -m engine.pipeline --csv data/leads.csv --csv-contacts data/contacts.csv
```

## SpyFu Client

The SpyFu client (`engine/clients/spyfu.py`) is a Python port of the TypeScript
client at `apps/web/src/lib/spyfu/client.ts` in the synter-media repo.

### Key Methods

| Method | Endpoint | Cache TTL | Description |
|--------|----------|-----------|-------------|
| `get_domain_stats(domain)` | `/apis/domain_stats_api/v2/getLatestDomainStats` | — | PPC budget, keywords, clicks |
| `get_ad_history(domain)` | `/apis/ad_history_api/v2/getDomainAds` | — | Historical ad copy |
| `get_ppc_keywords(domain)` | `/apis/ppc_api/v2/getDomainPpcKeywords` | — | Keyword list with CPC |
| `get_competitors(domain)` | `/apis/competitors_api/v2/*/getTopCompetitors` | — | PPC + organic competitors |
| `get_seo_metrics(domain)` | `/apis/seo_api/v2/getDomainSeoStats` | — | SEO rankings, click value |
| `get_kombat(domains)` | `/apis/kombat_api/v2/getKombatData` | — | Keyword gap analysis |
| `enrich_domain(domain)` | All of the above | — | Full enrichment in one call |

### Rate Limits

- SpyFu: ~100 requests/hour
- `enrich_domain()` makes 5 API calls per domain → max ~20 leads per run
- 300ms delay between requests

## Email Sequence

The 18-email sequence follows a **cautionary-tale narrative**: "Here's what
happens when you hire a paid media person or agency" — walking the prospect
through the typical 90-day failure arc, then positioning Synter as the
alternative.

See `docs/18-email-sequence.md` for the full spec with templates and
enrichment variable mappings.

## Loops.so Integration

### Contact Properties (Merge Tags)

The `enrich_for_followup()` function upserts 18+ custom properties to each
Loops contact. These are available as `{{propertyName}}` in Loop automations:

| Property | Source | Example |
|----------|--------|---------|
| `monthlyAdSpend` | SpyFu | `$15,000` |
| `annualAdSpend` | SpyFu | `$180,000` |
| `estimatedSavings` | Calculated | `$2,250-$3,750` |
| `ppcKeywords` | SpyFu | `342` |
| `organicKeywords` | SpyFu | `1,205` |
| `topCompetitor` | SpyFu | `acme.com` |
| `competitorSpend` | SpyFu | `$22,000` |
| `domainStrength` | SpyFu | `62` |
| `topHeadline` | SpyFu | `Try Acme Free...` |
| `topAdDays` | SpyFu | `247` |
| `totalAds` | SpyFu | `38` |
| `orgClickValue` | SpyFu | `$12,400` |
| `seoTop10` | SpyFu | `89` |
| `wasteKeywords` | SpyFu | `47` |
| `estimatedSavingsSpyfu` | SpyFu | `$3,000` |

### Important Limitation

Loops.so does NOT support creating or editing Loop automations via API.
The 18-step automation must be created manually in the Loops UI.
The API only handles contact management, events, and transactional emails.

## Database Models

- `JobPosting` — Discovered job postings (dedup by `sumble_job_id`)
- `Contact` — CEO/founder contacts
- `EmailLog` — Email send attempts
- `LinkedInOutreach` — LinkedIn message attempts
- `FollowUpLog` — Follow-up enrichment tracking (SpyFu data)
- `RunLog` — Pipeline execution tracking

## X (Twitter) Growth Engine

Automated content posting and engagement scanning for the @JSHorwitz founder account.

### Module: `engine/x/`

| File | Purpose |
|------|---------|
| `content_calendar.json` | 4-week, 31-post calendar (lowercase founder voice) |
| `scheduled_post.py` | Post next item from calendar, track via `.x_posted_log.json` |
| `engagement_scanner.py` | Scan 10 search queries, rank by engagement score, save candidates |
| `quote_retweet.py` | 3-tier fallback: quote → reply → standalone mention |
| `post_content.py` | Core publishing (single posts, threads, replies) |
| `tweet_lookup.py` | Full tweet metrics and author details lookup |
| `get_followers.py` | Audience analysis with bio keyword filtering |

### CLI Commands

```bash
# List calendar status
python -m engine.pipeline --x-list

# Post next scheduled item
python -m engine.pipeline --x-post

# Dry-run post
python -m engine.pipeline --x-post --dry-run

# Scan for engagement opportunities
python -m engine.pipeline --x-scan

# Engage with scan candidate #0
python -m engine.pipeline --x-engage 0 --x-comment "this is why we built synter"
```

### Scheduler (`scripts/x_scheduler.py`)

Long-lived process for Railway deployment. Posts 3x daily (9am, 2pm, 4pm PT) and scans every 4 hours.

```bash
# Run as long-lived scheduler
python scripts/x_scheduler.py

# Run once for testing
python scripts/x_scheduler.py --once post
python scripts/x_scheduler.py --once scan
```

### Authentication

- **Posting:** OAuth 1.0a via `JOEL_X_CONSUMER_KEY/SECRET` + `JOEL_X_ACCESS_TOKEN/SECRET`
- **Search:** Bearer token via `X_API_BEARER_TOKEN`
- All credentials stored in Doppler (`synter-media` project, `prd` config)

### Railway Deployment

Two Railway services from the same repo:

1. **Enrichment service** (cron): `doppler run -- python -m engine.pipeline --enrich --export loops`
2. **X scheduler service** (long-lived): `doppler run -- python scripts/x_scheduler.py`

Both need a `/data` volume mount for persistent state files (posted log, scan candidates).

### Persistence Files (on `/data` volume)

| File | Purpose |
|------|---------|
| `.x_posted_log.json` | Tracks which calendar items have been posted |
| `.x_scan_candidates.json` | Latest engagement scan results |
| `.x_engaged_log.json` | Tweets already engaged with (dedup) |
| `.x_quote_targets.json` | Monitored accounts for quote retweeting |

### Influencer / Amplifier Outreach

Scripts in `scripts/` for analyzing competitor followers and enriching engagers:

| Script | Purpose |
|--------|---------|
| `fetch_tweet_engagers.py` | Pull liking/retweeting users from a single tweet |
| `fetch_all_tweet_engagers.py` | Pull engagers from all high-engagement tweets of a user |
| `reenrich_engagers.py` | Re-run Apollo enrichment on previously pulled engagers |

**Outreach drafts** live in `data/amplifier_outreach_drafts.md`. Enriched contact data in `data/tweet_engagers_enriched.csv`.

**Apollo.io enrichment** (API key in Doppler as `APOLLO_API_KEY`): Use `POST https://api.apollo.io/api/v1/people/match` with `first_name`, `last_name`, `domain` in JSON body. Pass `reveal_personal_emails: true` for email results. Credits are consumed per lookup.

### X Algorithm Reference (from open-sourced twitter/the-algorithm)

Key ranking signals for content calendar optimization:

| Signal | Weight |
|--------|--------|
| Reply-to-reply chains | 75x a like |
| Reposts | 20x a like |
| Quote tweets | 15x a like |
| Replies | 13.5-27x a like |
| Profile clicks | 12x a like |
| Bookmarks | 10x a like |

- **First 30 minutes** determine a post's reach. Visibility decays 50% every 6hrs.
- **External links** carry a 50-90% reach penalty. Post links in replies, not the main tweet.
- **API-posted tweets are NOT penalized** vs native app tweets (confirmed in source code).
- **Content calendar** (`engine/x/content_calendar.json`) supports threads via `"thread": [...]` array.
- All posts must be <=280 chars. The scheduler validates this before posting.

### Known Blockers

- **DM outreach:** X Developer App needs "Direct Message" permission + token regeneration
- **Follower scanning:** X App needs to be attached to a "Project" in the Developer Portal
- **Liking users endpoint:** Returns 0 results on Basic tier. Only `retweeted_by` works for engager pulls. Need Pro tier ($5K/mo) or use the bearer token with sufficient credits.

## Common Issues

### SpyFu returns no data
Some domains are too small for SpyFu tracking. The pipeline falls back
to a generic follow-up email when `estimated_monthly_spend < $100`.

### Rate limiting
If you see `[SpyFu] Rate limited (429)`, reduce `MAX_EMAILS_PER_RUN`
or add delay between runs.

### Loops property limits
Loops limits custom property values to ~500 chars. Email body previews
are automatically truncated to 497 chars.
