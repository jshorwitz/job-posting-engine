# Job Posting Growth Engine

Standalone tool that monitors [Sumble.com](https://sumble.com) for companies hiring growth marketing leaders (Head of Growth, VP Growth, etc.), finds the CEO/founder, and sends personalized outreach via **LinkedIn Sales Navigator** or email.

## How It Works

```
Cron (daily) → Sumble Jobs API → Deduplicate → Sumble People API → OpenAI → LinkedIn/Email
```

1. **Discover** — Queries Sumble for new job postings matching "Head of Growth" (configurable)
2. **Deduplicate** — Skips jobs and companies already processed (SQLite)
3. **Enrich** — Finds CEO/founder via Sumble People API (name, title, LinkedIn)
4. **Personalize** — Generates outreach message via OpenAI referencing their hiring signal
5. **Send** — Sends via LinkedIn (InMail or connection request) and/or email
6. **Notify** — Posts run summary to Slack (optional)

## Quick Start

```bash
# Clone and install
pip install -e ".[dev]"

# Install Playwright browsers (first time only)
playwright install chromium

# Configure
cp .env.example .env
# Edit .env with your Sumble API key, OpenAI key, etc.

# Set up LinkedIn session (opens browser for manual login — one time)
python -m engine.outreach.linkedin_sender --setup

# Dry run (logs outreach but doesn't send)
run-engine --dry-run

# Send LinkedIn InMails
run-engine --channel linkedin --linkedin-type inmail

# Send connection requests with notes instead
run-engine --channel linkedin --linkedin-type connection

# Custom query
run-engine --query "VP Growth Marketing" --limit 30

# Both channels (LinkedIn + email drafts)
run-engine --channel both
```

## LinkedIn Sales Navigator Setup

### 1. Install browser

```bash
playwright install chromium
```

### 2. Log in (one-time)

```bash
python -m engine.outreach.linkedin_sender --setup
```

This opens a Chromium browser. Log in to LinkedIn (and navigate to Sales Navigator). Close the browser when done — the session is saved to `data/linkedin-session/state.json`.

### 3. Configure

In `.env`:

```bash
LINKEDIN_OUTREACH_TYPE=inmail    # "inmail" (Sales Nav) or "connection" (regular)
LINKEDIN_DAILY_LIMIT=25          # Max sends per day (keep ≤25)
LINKEDIN_HEADLESS=false          # Set true once stable
LINKEDIN_MIN_DELAY=30            # Min seconds between sends
LINKEDIN_MAX_DELAY=90            # Max seconds between sends
OUTREACH_CHANNEL=linkedin        # "linkedin", "email", or "both"
```

### 4. Safety notes

- **Daily limit:** Defaults to 25/day — LinkedIn flags accounts sending more
- **Human-like delays:** Random 30-90s between messages with variable typing speed
- **Session persistence:** Login cookies are reused — no re-login on each run
- **Error screenshots:** Saved to `data/linkedin-session/screenshots/` for debugging
- **⚠️ LinkedIn ToS:** Browser automation is against LinkedIn's Terms of Service. Use at your own risk. Keep volumes low.

## Credit Costs (Sumble)

| API Call | Credits | Per Run (20 leads) |
|----------|---------|-------------------|
| Jobs find | 3/job | ~180 credits |
| People find | 1/person | ~20 credits |
| **Total** | | **~200 credits** |

Sumble Pro: $99/mo = 9,900 credits → **~49 runs/month**

## Project Structure

```
job-posting-engine/
├── engine/
│   ├── config.py               # Settings via pydantic-settings + .env
│   ├── pipeline.py             # Main orchestrator
│   ├── clients/
│   │   ├── sumble.py           # Sumble v3 API client
│   │   └── slack.py            # Slack webhook
│   ├── db/
│   │   ├── database.py         # SQLite + SQLAlchemy
│   │   └── models.py           # JobPosting, Contact, EmailLog, LinkedInOutreach
│   ├── ai/
│   │   ├── email_writer.py     # OpenAI email generation
│   │   └── linkedin_writer.py  # OpenAI LinkedIn message generation
│   └── outreach/
│       ├── smtp_sender.py      # SMTP email sender
│       └── linkedin_sender.py  # Playwright LinkedIn automation
├── data/                       # SQLite DB + LinkedIn session (gitignored)
├── logs/                       # Log files (gitignored)
├── .env.example
├── pyproject.toml
├── Dockerfile
└── README.md
```

## CLI Flags

| Flag | Values | Default | Description |
|------|--------|---------|-------------|
| `--dry-run` | — | from `.env` | Log but don't send |
| `--channel` | `linkedin`, `email`, `both` | `linkedin` | Outreach channel |
| `--linkedin-type` | `inmail`, `connection` | `inmail` | LinkedIn message type |
| `--query` | string | `Head of Growth` | Job title search query |
| `--limit` | int | `20` | Max outreach per run |

## Email Enrichment (Planned)

Sumble People API returns LinkedIn URLs but not email addresses. To enable email sending, integrate:

- [Apollo.io](https://apollo.io) — Find email from LinkedIn URL
- [Hunter.io](https://hunter.io) — Domain-based email finder
- [Prospeo](https://prospeo.io) — LinkedIn email finder

## Docker

```bash
# One-shot run (note: LinkedIn automation requires headed browser, not ideal for Docker)
docker build -t job-engine .
docker run --env-file .env -v $(pwd)/data:/home/appuser/app/data job-engine

# With cron (add to host crontab)
0 8 * * * docker run --rm --env-file /path/to/.env -v /path/to/data:/home/appuser/app/data job-engine
```
