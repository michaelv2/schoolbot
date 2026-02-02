# SchoolBot — Implementation Plan

## Research Findings

### API Availability - Not Accessible
Schoology provides a REST API, but **access requires administrator privileges** to generate API keys. Since:
- User has parent account (not admin)
- School unlikely to grant API access to parents
- Parent access code is only for account registration, not API authentication

**Web automation is the only viable approach.**

### Parent Account Capabilities
Parent accounts CAN access all required information through the web interface:
- All assignments (upcoming and overdue) with due dates
- All grades on assignments, assessments, and discussions
- Calendar events
- Course materials and notes
- Overall grade percentages per course

### Technical Approach - Web Automation

**Playwright** chosen over Selenium for:
- Faster execution and better JavaScript handling
- Built-in waiting mechanisms for dynamic content
- More reliable headless mode
- Active Microsoft-supported development

---

## Requirements

- **Delivery Method**: Automated email to parent (+ student)
- **Schedule**: Once daily in the evening via cron
- **Execution**: Local machine
- **Weak Area Threshold**: Grades below 80% (configurable)
- **Historical Tracking**: Grade history + feedback history
- **Students**: One student
- **Authentication**: Parent account with cookie-based session persistence

---

## Architecture

```
Schoology (web)
    │
    │  Headless Playwright browser
    ▼
┌─────────────────────────────────────────┐
│  scraper.py                             │
│  - Cookie-based session persistence     │
│  - Assignment extraction                │
│  - Grade extraction (JS evaluation)     │
│  - Calendar events (FullCalendar API)   │
│  - Course materials (for test prep)     │
└──────────────┬──────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────┐
│  report.py                              │
│  - Diff against last_run.json           │
│  - New assignment detection             │
│  - Low grade identification (< 80%)     │
│  - Overdue item detection               │
│  - Upcoming test/quiz detection         │
│  - Recent graded items (past 2 weeks)   │
│  - Grade history tracking               │
│  - Feedback history + repetition check  │
│  - Persistent issue detection           │
│  - HTML email rendering                 │
│  - SMTP delivery with attachments       │
└──────────────┬──────────────────────────┘
               │
               ▼ (opt-in: ENABLE_TEST_PREP=true)
┌─────────────────────────────────────────┐
│  testprep.py  (Claude API)              │
│  - Topic summary per upcoming test      │
│  - HTML study guide generation          │
│  - Personalized student feedback        │
│  - Feedback history context in prompt   │
└─────────────────────────────────────────┘

Data files (JSON, git-ignored):
  cookies.json          → Browser session
  last_run.json         → Previous scrape snapshot
  grade_history.json    → Item first-seen dates
  feedback_history.json → Daily feedback + repetition tracking
```

## Project Structure

```
schoolbot/
├── schoolbot/
│   ├── __init__.py
│   ├── config.py        # Env vars, file paths, load_selectors()
│   ├── scraper.py       # Playwright scraping (login, assignments, grades, calendar, materials)
│   ├── report.py        # Analysis, HTML rendering, email delivery, history management
│   └── testprep.py      # Claude API: study guides, topic summaries, student feedback
├── run.py               # CLI entry point (--headed, --scrape-only)
├── setup.sh             # One-time setup (venv, deps, chromium)
├── selectors.yaml       # CSS selectors for Schoology DOM
├── requirements.txt     # playwright, pyyaml, python-dotenv, anthropic
├── .env.example         # Environment variable template
├── .gitignore
├── README.md
├── PLAN.md              # This file
├── TODO.md              # Remaining tasks
├── spike.py             # Dev tool: interactive browser for DOM inspection
└── dump_materials.py    # Dev tool: dump course materials HTML
```

**Design decision:** A flat package with four modules proved simpler and more maintainable than the originally planned deep module tree (`src/scraper/`, `src/database/`, `src/analysis/`, `src/reporting/`). JSON files replaced SQLite since the data volume is small and human-readable files are easier to inspect and debug.

---

## Implementation Phases

### Phase 1: Authentication & Basic Scraping ✅

- [x] Project structure and dependencies
- [x] Playwright setup with Chromium
- [x] Cookie-based session persistence (`cookies.json`)
- [x] Interactive login fallback (`--headed` mode)
- [x] Assignment extraction from `/home/upcoming`
- [x] Parent account URL handling (`SCHOOLOGY_CHILD_ID`)

### Phase 2: Complete Data Extraction ✅

- [x] Grade extraction with JS evaluation (categories, weights, periods)
- [x] Calendar event extraction via FullCalendar JS API
- [x] Course materials extraction (folders, pages, assignments, documents)
- [x] Multi-course support
- [x] Test/quiz identification via keyword pattern matching
- [x] Calendar event timezone correction (Schoology UTC offset)

### Phase 3: Historical Tracking ✅ (simplified)

Originally planned SQLite + SQLAlchemy. Implemented with JSON files instead:

- [x] `last_run.json` — full scrape snapshot for diffing
- [x] `grade_history.json` — tracks when graded items first appeared
- [x] `feedback_history.json` — daily feedback with context and components
- [x] New assignment detection (diff current vs previous run)
- [x] Recently graded items (items appearing in last 2 weeks)
- [x] Automatic history pruning (configurable retention period)
- [ ] ~~SQLite database~~ (deferred — JSON sufficient at current scale)
- [ ] ~~SQLAlchemy models~~ (deferred)

### Phase 4: Analysis & Intelligence ✅ (partial)

- [x] Low grade detection (configurable threshold, default 80%)
- [x] Overdue item detection (ungraded items past due date)
- [x] New assignment detection (diff against previous run)
- [x] Urgency sorting by due date
- [x] Upcoming test/quiz detection (from assignments + calendar)
- [x] Persistent issue tracking (multi-day overdue, sustained low grades)
- [x] Weighted grade calculation (category weights, period breakdowns)
- [ ] Week-over-week trend calculation
- [ ] Improvement/decline rate tracking
- [ ] Pattern detection (e.g. "struggles with Friday quizzes")

### Phase 5: Report Generation ✅

- [x] HTML email with structured sections:
  - Student feedback (personalized encouragement + joke)
  - Low-grade warnings
  - Upcoming tests/quizzes (with AI topic summaries)
  - Upcoming assignments sorted by due date
  - Overdue assignments
  - Course grades with quarter/period breakdowns
  - Recently graded items (past 2 weeks)
- [x] SMTP delivery (Gmail app password support)
- [x] Multiple recipients (comma-separated `EMAIL_TO`)
- [x] Study guide HTML attachments
- [ ] Color coding for grade levels
- [ ] Improved email formatting (spacing, section styling)

### Phase 6: Orchestration & Automation ✅

- [x] CLI entry point (`run.py`) with `--headed` and `--scrape-only` flags
- [x] Environment-based configuration (`.env` + `config.py`)
- [x] Graceful degradation (partial data OK, API failures non-fatal)
- [x] Error handling throughout pipeline
- [x] Cron setup documented in README
- [x] Configurable selectors in YAML
- [ ] Formal `logging` module (currently uses `print()`)
- [ ] Error alert emails on failure

### Phase 7: Robustness & Maintenance ✅ (partial)

- [x] Selectors externalized in `selectors.yaml`
- [x] Error handling for login failures, timeouts, missing elements
- [x] Graceful degradation for missing data
- [x] Dev tools for DOM inspection (`spike.py`, `dump_materials.py`)
- [ ] Fallback selectors (try multiple approaches per element)
- [ ] Health check alerts (e.g. "no assignments found")
- [ ] Automated tests

### Beyond Original Plan ✅

Features added that were not in the original design:

- [x] **Test prep** — Claude API generates topic summaries and HTML study guides for upcoming tests
- [x] **Student feedback** — Daily personalized motivational message with joke
- [x] **Feedback history tracking** — Stores past feedback with context snapshots
- [x] **3-tier repetition detection** — Exact match, joke similarity, context+encouragement similarity
- [x] **Persistent issue override** — Allows repeated emphasis for multi-day problems
- [x] **Feedback component extraction** — Separates encouragement from joke for comparison
- [x] **Calendar timezone correction** — Fixes Schoology's UTC all-day event offset
- [x] **Day-of-week annotation** — Test dates shown with weekday name in Claude prompt

---

## Technical Stack

### Actual Dependencies
```
playwright>=1.40        # Headless browser automation
pyyaml>=6.0             # Selector configuration
python-dotenv>=1.0      # Environment variable loading
anthropic>=0.40         # Claude API client (test prep + feedback)
```

### Python Version
- Python 3.10+ (type union syntax `dict | None`)

### System Requirements
- Chromium (installed via `playwright install chromium`)
- Internet connection
- SMTP access (Gmail app password or similar)
- Cron or equivalent for scheduling

---

## Configuration

All configuration via environment variables (`.env` file):

```bash
# Schoology
SCHOOLOGY_DOMAIN=app.schoology.com
SCHOOLOGY_CHILD_ID=              # Required for parent accounts

# SMTP
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=you@gmail.com
SMTP_PASSWORD=your-app-password
EMAIL_TO=parent@example.com      # Comma-separated for multiple recipients
EMAIL_FROM=you@gmail.com

# Thresholds
GRADE_WARN_THRESHOLD=80

# Test Prep (opt-in)
ENABLE_TEST_PREP=false
ANTHROPIC_API_KEY=
ANTHROPIC_MODEL=claude-sonnet-4-20250514

# Feedback history
FEEDBACK_HISTORY_DAYS=30
```

---

## Risk Mitigation

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Schoology UI changes | High | High | Selectors in YAML; dev tools for quick inspection |
| Login/session expiry | Medium | High | Cookie persistence; `--headed` fallback for re-login |
| Bot detection | Low | High | Authenticated parent session; realistic browser context |
| Email delivery fails | Low | Medium | Error logged; report still generated locally |
| Missing data | Medium | Low | Graceful degradation; sections omitted if empty |
| Claude API failure | Low | Low | Returns empty string; report sends without feedback/guides |

---

## Verification

### Verified Through Live Usage

**Scraping:**
- [x] Login and cookie reuse
- [x] Assignment extraction across all courses
- [x] Grade extraction with categories, weights, periods
- [x] Calendar event extraction
- [x] Course materials extraction
- [x] Test/quiz identification

**Analysis:**
- [x] New assignment detection
- [x] Low grade identification (< 80%)
- [x] Overdue item detection
- [x] Recently graded items
- [x] Upcoming test detection from calendar + assignments

**Report:**
- [x] HTML email renders correctly
- [x] Email delivers to inbox (not spam)
- [x] Study guide attachments
- [x] Student feedback generation
- [x] Feedback varies across runs (repetition detection working)

**History:**
- [x] grade_history.json created and updated
- [x] feedback_history.json created with context + components
- [x] Repetition detection triggers regeneration
- [x] History pruning removes old entries
- [x] Persistent issue tracking (consecutive day counting)

### Not Yet Verified
- [ ] Behavior when Schoology is down/maintenance
- [ ] SMTP failure handling
- [ ] Behavior with no assignments (empty state)
- [ ] All assignments overdue edge case
- [ ] Long-running trend accuracy over weeks

### Not Implemented
- [ ] Automated unit tests
- [ ] Mock scraper tests with saved HTML
- [ ] CI/CD pipeline

---

## Remaining Work

### TODO (from TODO.md)
- [ ] Color coding for grades in email
- [ ] Improved email formatting (spacing, section styling)
- [ ] Overdue assignment whitelist (ignore known exceptions)

### Future Enhancements
- [ ] Week-over-week grade trend calculation
- [ ] Formal `logging` module with log file rotation
- [ ] Error notification emails on script failure
- [ ] Fallback selectors for resilience to UI changes
- [ ] Health checks (alert if data looks suspicious)
- [ ] Configurable similarity thresholds for feedback detection
- [ ] Automated tests with saved HTML fixtures

---

## References

- [Schoology API Documentation](https://developers.schoology.com/api/)
- [Playwright Python Documentation](https://playwright.dev/python/)
- [What Parents Can See in Schoology](https://spsedtech.wordpress.com/2015/09/24/what-parents-can-and-cannot-see-in-schoology/)
