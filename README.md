# SchoolBot

Automated daily school report for Schoology. Scrapes assignments, grades, and calendar events, then emails a summary with optional AI-generated study guides and personalized student feedback.

Built for a parent account tracking an 8th-grader, but adaptable to any Schoology setup.

## Features

- **Daily email report** with assignments, grades, overdue work, and upcoming tests
- **Grade tracking** with low-grade warnings and quarter-by-quarter breakdowns
- **New assignment detection** by diffing against the previous run
- **Test prep** (opt-in) — uses Claude to generate topic summaries and HTML study guides for upcoming tests
- **Student feedback** (opt-in) — personalized motivational messages with joke, tracked across days to avoid repetition
- **Session persistence** — saves browser cookies so login is only needed once

## How It Works

```
Schoology (web) ──▶ Playwright scraper ──▶ Data extraction
                                              │
                          ┌───────────────────┤
                          ▼                   ▼
                    Grade analysis      Test prep (Claude API)
                          │                   │
                          ▼                   ▼
                    HTML email ◀──── Study guides + feedback
                          │
                          ▼
                    SMTP delivery
```

1. **Scrape** — Playwright opens Schoology, extracts assignments, grades, calendar events, and (optionally) course materials
2. **Analyze** — Identifies new assignments, low grades, overdue items, upcoming tests, and recent scores
3. **Generate** — If test prep is enabled, sends course materials to Claude for study guide generation and student feedback
4. **Report** — Renders an HTML email with all findings, attaches study guides as HTML files
5. **Send** — Delivers via SMTP to one or more recipients

## Setup

```bash
# Clone and enter the project
git clone <repo-url> && cd schoolbot

# Run setup (creates venv, installs deps, installs Chromium)
bash setup.sh

# Activate the virtual environment
source .venv/bin/activate

# Configure environment
cp .env.example .env
# Edit .env with your credentials (see Configuration below)
```

### First Run

The first run requires a manual browser login to establish cookies:

```bash
python run.py --headed
```

A browser window will open. Log in to Schoology manually, then the script will save your session cookies for future headless runs.

## Configuration

Copy `.env.example` to `.env` and fill in:

| Variable | Required | Description |
|---|---|---|
| `SCHOOLOGY_DOMAIN` | Yes | Your school's Schoology domain (e.g. `app.schoology.com`) |
| `SCHOOLOGY_CHILD_ID` | If parent | Student ID (required for parent accounts) |
| `SMTP_HOST` | Yes | SMTP server (e.g. `smtp.gmail.com`) |
| `SMTP_PORT` | No | SMTP port (default `587`) |
| `SMTP_USER` | Yes | SMTP login username |
| `SMTP_PASSWORD` | Yes | SMTP password or app password |
| `EMAIL_TO` | Yes | Recipient(s), comma-separated |
| `EMAIL_FROM` | No | Sender address (defaults to `SMTP_USER`) |
| `GRADE_WARN_THRESHOLD` | No | Low-grade warning threshold (default `80`) |
| `ENABLE_TEST_PREP` | No | Enable AI study guides and feedback (`true`/`false`, default `false`) |
| `ANTHROPIC_API_KEY` | If test prep | API key for Claude |
| `ANTHROPIC_MODEL` | No | Claude model (default `claude-sonnet-4-20250514`) |
| `FEEDBACK_HISTORY_DAYS` | No | Days of feedback history to retain (default `30`) |

### Gmail Setup

For Gmail, create an [App Password](https://myaccount.google.com/apppasswords) and use it as `SMTP_PASSWORD`.

## Usage

```bash
# Standard run (headless scrape + email)
python run.py

# Visible browser (for debugging or re-login)
python run.py --headed

# Scrape only, print data, no email
python run.py --scrape-only
```

### Automation

Run daily with cron:

```cron
0 18 * * 1-5 cd /path/to/schoolbot && .venv/bin/python run.py >> /var/log/schoolbot.log 2>&1
```

## Project Structure

```
schoolbot/
  __init__.py
  config.py          # Environment + file path configuration
  scraper.py         # Playwright-based Schoology scraper
  report.py          # Grade analysis, HTML rendering, email delivery
  testprep.py        # Claude API integration for study guides + feedback
run.py               # CLI entry point
setup.sh             # One-time setup script
selectors.yaml       # CSS selectors for Schoology DOM elements
.env.example         # Environment variable template
```

### Runtime Files (git-ignored)

These are created automatically and contain student data:

| File | Purpose |
|---|---|
| `cookies.json` | Saved browser session |
| `last_run.json` | Previous scrape snapshot (for new-assignment detection) |
| `grade_history.json` | Tracks when graded items first appeared |
| `feedback_history.json` | Daily student feedback with repetition tracking |

### Dev Tools

| File | Purpose |
|---|---|
| `spike.py` | Interactive browser session for inspecting Schoology HTML |
| `dump_materials.py` | Dumps course materials pages for selector development |

## Selectors

Schoology's DOM structure is captured in `selectors.yaml`. If Schoology updates their UI, update the selectors there rather than in Python code. The scraper reads them at runtime via `config.load_selectors()`.

## Privacy

This tool processes student educational records locally on your machine. No data is sent to third parties except:

- **SMTP server** — the email report
- **Anthropic API** — course materials and grade context (only if `ENABLE_TEST_PREP=true`)

All runtime data files (`cookies.json`, `last_run.json`, `grade_history.json`, `feedback_history.json`) are git-ignored and stay local.

## License

MIT
