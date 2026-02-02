# Schoology Educational Data Parser - Implementation Plan

## Research Findings

### API Availability - Not Accessible ⚠️
Schoology provides a REST API, but **access requires administrator privileges** to generate API keys. Since:
- User has parent account (not admin)
- School unlikely to grant API access to parents
- Parent access code is only for account registration, not API authentication

**We must use web automation instead of the API.**

### Parent Account Capabilities ✅
Parent accounts CAN access all required information through the web interface:

**What Parents Can See:**
- All assignments (upcoming and overdue) with due dates
- All grades on assignments, assessments, and discussions
- Calendar events
- Course materials and notes
- Comments from teachers
- Rubric information
- Overall grade percentages per course

**What Parents Cannot See:**
- Names/photos of other students (privacy protection)
- Cannot interact with assignments (read-only view)

### Technical Approach - Web Automation

**Use Playwright for headless browser automation:**

**Why Playwright over Selenium:**
- Modern, faster (290ms vs 536ms in benchmarks)
- Better JavaScript handling (important for Schoology's dynamic content)
- Built-in waiting mechanisms
- More reliable headless mode
- Microsoft-supported, actively maintained

**Architecture:**
- Python + Playwright
- Headless browser automation
- Session persistence (save cookies to minimize logins)
- Scheduled execution via cron
- SQLite for historical data storage
- Email delivery via SMTP

**Key Challenges:**
- Fragile - breaks if UI changes
- Need robust selectors (prefer data attributes, IDs over CSS classes)
- Bot detection possible (though unlikely for authenticated parent access)
- Requires maintenance when Schoology updates interface

---

## Requirements (From User)

### Core Requirements
- **Delivery Method**: Automated email to parent
- **Schedule**: Once daily in the evening (review day's updates + prep for tomorrow)
- **Execution**: Local laptop/desktop
- **Weak Area Threshold**: Grades below 80%
- **Historical Tracking**: Yes - track trends over time
- **Students**: One student only
- **Authentication**: Parent account with access code

### Additional Requirements to Clarify
- Parent email address for delivery
- Preferred time for evening run (e.g., 6 PM, 8 PM)
- Email formatting preference (HTML rich format vs plain text)
- Weekend runs needed?
- How long to retain historical data?

---

## Detailed Implementation Plan

### System Architecture

```
┌──────────────────────────────────────────┐
│   Schoology Web Interface               │
│   (app.schoology.com)                   │
└──────────────┬───────────────────────────┘
               │ Parent Login
               │ (Headless Browser)
┌──────────────▼───────────────────────────┐
│   Web Scraper Module (Playwright)       │
│   - Authenticate with saved session     │
│   - Navigate to assignments page        │
│   - Navigate to grades page             │
│   - Navigate to calendar/upcoming       │
│   - Extract structured data             │
└──────────────┬───────────────────────────┘
               │ Raw HTML → Structured Data
┌──────────────▼───────────────────────────┐
│   Data Storage (SQLite)                  │
│   Tables:                                │
│   - assignments (id, title, due_date,    │
│     description, course, posted_date)    │
│   - grades (assignment_id, score,        │
│     max_points, percentage, date)        │
│   - materials (id, title, type,          │
│     course, posted_date, url)            │
│   - snapshots (run_date, metadata)       │
└──────────────┬───────────────────────────┘
               │
┌──────────────▼───────────────────────────┐
│   Analysis Engine                        │
│   - Compare current vs historical data   │
│   - Identify new assignments             │
│   - Flag weak areas (< 80%)              │
│   - Detect grade trends                  │
│   - Prioritize by urgency                │
└──────────────┬───────────────────────────┘
               │
┌──────────────▼───────────────────────────┐
│   Report Generator                       │
│   - Format as HTML email                 │
│   - Daily summary sections:              │
│     1. Action Items (due soon)           │
│     2. New Assignments                   │
│     3. Recent Grades & Weak Areas        │
│     4. Upcoming Tests/Quizzes            │
│     5. New Study Materials               │
│     6. Trends (week-over-week)           │
└──────────────┬───────────────────────────┘
               │
┌──────────────▼───────────────────────────┐
│   Email Sender (SMTP)                    │
│   - Send via Gmail/Outlook SMTP          │
│   - Include previous report comparison   │
└──────────────────────────────────────────┘

┌──────────────────────────────────────────┐
│   Scheduler (cron)                       │
│   - Run daily at specified time          │
│   - Logging and error alerts             │
└──────────────────────────────────────────┘
```

### Project Structure

```
schoolbot/
├── src/
│   ├── scraper/
│   │   ├── __init__.py
│   │   ├── auth.py              # Login, session management
│   │   ├── assignments.py       # Extract assignments & due dates
│   │   ├── grades.py            # Extract grades & scores
│   │   ├── calendar.py          # Extract upcoming events
│   │   └── materials.py         # Extract study materials/notes
│   ├── database/
│   │   ├── __init__.py
│   │   ├── models.py            # SQLAlchemy models
│   │   └── operations.py        # CRUD operations
│   ├── analysis/
│   │   ├── __init__.py
│   │   ├── weak_areas.py        # Identify weak topics
│   │   ├── trends.py            # Track progress over time
│   │   └── prioritizer.py       # Sort by urgency
│   ├── reporting/
│   │   ├── __init__.py
│   │   ├── email_generator.py   # Create HTML email
│   │   └── smtp_sender.py       # Send via email
│   └── main.py                  # Orchestrator
├── config/
│   ├── config.yaml              # User configuration
│   └── selectors.yaml           # CSS/XPath selectors (easy updates)
├── data/
│   ├── schoology.db             # SQLite database
│   └── session/                 # Saved browser sessions
├── logs/
│   └── schoolbot.log            # Execution logs
├── requirements.txt
├── .env                         # Secrets (email credentials, etc.)
└── README.md
```

### Implementation Phases

#### Phase 1: Authentication & Basic Scraping (Week 1)
**Goal**: Successful login and extraction of assignments from one course

**Tasks:**
1. Set up Python project structure
2. Install Playwright (`pip install playwright`, `playwright install chromium`)
3. Create `auth.py`:
   - Navigate to app.schoology.com
   - Handle login form (email + password)
   - Save session cookies for reuse
   - Error handling for failed login, 2FA (if present)
4. Create `assignments.py`:
   - Navigate to assignments/upcoming page
   - Extract: title, due date, course, description
   - Parse dates into consistent format
5. Test on one course manually

**Critical Files Created:**
- `src/scraper/auth.py`
- `src/scraper/assignments.py`
- `config/selectors.yaml`

#### Phase 2: Complete Data Extraction (Week 1-2)
**Goal**: Extract all required data types

**Tasks:**
1. Create `grades.py`:
   - Navigate to gradebook for each course
   - Extract: assignment name, score, max points, percentage, date graded
   - Handle different grading scales (points, percentage, letter)
2. Create `calendar.py`:
   - Extract upcoming events
   - Identify tests/quizzes (by keyword or category)
   - Get event dates and descriptions
3. Create `materials.py`:
   - Extract posted materials (PDFs, links, notes)
   - Categorize by type
   - Get posting dates
4. Handle multiple courses (iterate through all enrolled courses)

**Critical Files:**
- `src/scraper/grades.py`
- `src/scraper/calendar.py`
- `src/scraper/materials.py`

#### Phase 3: Database & Historical Tracking (Week 2)
**Goal**: Store data for trend analysis

**Tasks:**
1. Design SQLite schema:
   - `assignments` table
   - `grades` table
   - `materials` table
   - `events` table
   - `snapshots` table (metadata about each run)
2. Create `database/models.py` using SQLAlchemy
3. Create `database/operations.py`:
   - Insert new records
   - Update existing records
   - Query historical data
   - Detect changes since last run
4. Modify scrapers to save to database after each run

**Critical Files:**
- `src/database/models.py`
- `src/database/operations.py`

#### Phase 4: Analysis & Intelligence (Week 2-3)
**Goal**: Transform raw data into actionable insights

**Tasks:**
1. Create `analysis/weak_areas.py`:
   - Identify grades < 80%
   - Group by subject/topic if possible
   - Track recurring weak areas
   - Correlate with specific concepts
2. Create `analysis/trends.py`:
   - Compare grades week-over-week
   - Calculate improvement/decline rates
   - Identify patterns (e.g., "struggles with Friday quizzes")
3. Create `analysis/prioritizer.py`:
   - Sort assignments by urgency (due date proximity)
   - Weight by grade importance
   - Flag overdue items

**Critical Files:**
- `src/analysis/weak_areas.py`
- `src/analysis/trends.py`
- `src/analysis/prioritizer.py`

#### Phase 5: Report Generation (Week 3)
**Goal**: Create parent-friendly daily summary email

**Tasks:**
1. Create `reporting/email_generator.py`:
   - HTML email template with sections:
     ```
     DAILY SUMMARY - [Date]

     🎯 TODAY'S PRIORITIES
     - [Assignment 1] due tomorrow in [Course]
     - [Assignment 2] due [Date]

     📝 NEW ASSIGNMENTS (since yesterday)
     - [List of new assignments with due dates]

     📊 RECENT GRADES
     - [Assignment]: [Score] - ✅ Strong / ⚠️ Review Needed

     ⚠️ FOCUS AREAS (< 80%)
     - [Subject/Topic]: Recent scores [X%, Y%, Z%]
     - Suggested action: Review [specific materials]

     📅 UPCOMING TESTS/QUIZZES
     - [Test name] on [Date] in [Course]

     📚 NEW STUDY MATERIALS
     - [Material name] posted in [Course]

     📈 PROGRESS TRENDS
     - Overall average: [X%] (↑/↓ from last week)
     - Improving in: [Subjects]
     - Needs attention: [Subjects]
     ```
   - Make it scannable (emoji, bold, sections)
   - Include actionable next steps
2. Create `reporting/smtp_sender.py`:
   - Configure SMTP (Gmail, Outlook, etc.)
   - Send HTML email
   - Handle authentication securely (app passwords)
   - Retry logic for failed sends

**Critical Files:**
- `src/reporting/email_generator.py`
- `src/reporting/smtp_sender.py`
- Email template

#### Phase 6: Orchestration & Automation (Week 3-4)
**Goal**: Fully automated daily runs

**Tasks:**
1. Create `main.py`:
   - Orchestrate all modules in sequence
   - Error handling for each step
   - Logging to file
   - Graceful degradation (partial data ok)
2. Create `config/config.yaml`:
   - User settings (email address, schedule time, thresholds)
   - Schoology credentials (encrypted)
   - Email SMTP settings
3. Set up logging:
   - Detailed logs for debugging
   - Error notifications (optional: email on failure)
4. Create cron job:
   - Daily execution at specified time
   - Example: `0 18 * * * cd /path/to/schoolbot && /usr/bin/python3 src/main.py`
5. Test full end-to-end workflow

**Critical Files:**
- `src/main.py`
- `config/config.yaml`
- Cron configuration

#### Phase 7: Robustness & Maintenance (Ongoing)
**Goal**: Handle edge cases and UI changes

**Tasks:**
1. Implement robust selectors:
   - Use data attributes when available
   - Fallback selectors (try multiple approaches)
   - Validate extracted data format
2. Add comprehensive error handling:
   - Login failures (wrong password, account locked, 2FA)
   - Page load timeouts
   - Missing elements (teacher didn't post grades yet)
   - Network issues
3. Create selector update guide:
   - Document how to find new selectors when UI changes
   - Make selectors configurable in YAML (non-code changes)
4. Add health checks:
   - Verify expected data structure
   - Alert if no assignments found (suspicious)
   - Alert if repeated failures

**Ongoing Maintenance:**
- Monitor for Schoology UI changes
- Update selectors as needed
- Review logs for errors

---

## Technical Stack

### Core Dependencies
```
playwright==1.41.0           # Headless browser automation
beautifulsoup4==4.12.3       # HTML parsing
lxml==5.1.0                  # XML/HTML parser (faster)
sqlalchemy==2.0.25           # Database ORM
pyyaml==6.0.1                # Configuration files
python-dotenv==1.0.0         # Environment variables
smtplib (built-in)           # Email sending
logging (built-in)           # Logging
```

### Development Dependencies
```
pytest==7.4.4                # Testing
black==24.1.1                # Code formatting
```

### Python Version
- Python 3.10+ (for match/case statements and type hints)

### System Requirements
- Chromium browser (installed via Playwright)
- ~200MB disk space for browser
- Cron or Task Scheduler for automation
- Internet connection
- SMTP access (Gmail app password or similar)

---

## Configuration Files

### config/config.yaml
```yaml
schoology:
  url: "https://app.schoology.com"
  parent_email: "parent@example.com"
  # Password stored in .env for security

student:
  name: "Student Name"

schedule:
  time: "18:00"  # 6 PM daily
  timezone: "America/New_York"
  run_weekends: false

analysis:
  weak_threshold: 80  # Grades below 80% flagged
  urgent_days: 2      # Assignments due within 2 days = urgent

email:
  to: "parent@example.com"
  from: "schoolbot@example.com"
  subject_prefix: "[Schoology Update]"
  smtp_host: "smtp.gmail.com"
  smtp_port: 587
  # SMTP credentials in .env

storage:
  database_path: "data/schoology.db"
  retention_days: 365  # Keep 1 year of history
```

### .env (secrets)
```
SCHOOLOGY_PASSWORD=your_parent_password_here
SMTP_USERNAME=your_email@gmail.com
SMTP_PASSWORD=your_app_password_here
```

### config/selectors.yaml
```yaml
# CSS/XPath selectors for Schoology elements
# Update here if Schoology changes UI
login:
  email_field: "input[name='mail']"
  password_field: "input[name='pass']"
  submit_button: "input[type='submit']"

assignments:
  container: ".upcoming-list"
  title: ".sgy-title"
  due_date: ".due-date"
  course: ".course-name"

# ... more selectors
```

---

## Risk Mitigation

| Risk | Likelihood | Impact | Mitigation Strategy |
|------|------------|--------|---------------------|
| Schoology UI changes break scraper | High | High | - Use flexible selectors (prefer IDs/data attributes)<br>- Store selectors in YAML for easy updates<br>- Implement fallback selectors<br>- Add validation to detect breakage early |
| Login fails (2FA, password change) | Medium | High | - Save session cookies (reduces login frequency)<br>- Graceful error handling with email alert<br>- Manual intervention instructions in error message |
| Bot detection blocks access | Low | High | - Use realistic browser headers<br>- Respect rate limits (reasonable delays)<br>- Authenticated parent access less likely to be flagged<br>- Run headless but with full browser context |
| Email delivery fails | Low | Medium | - Retry logic (3 attempts)<br>- Log error with report content<br>- Fallback to local file if email fails |
| Missing data (teacher hasn't posted) | Medium | Low | - Handle gracefully (note in report)<br>- Don't fail entire run on missing section<br>- Validate data structure before processing |
| Cron job doesn't run (laptop off) | Medium | Medium | - Document in README that laptop must be on<br>- Alternative: Suggest always-on device if needed<br>- Log missed runs for visibility |

---

## Verification & Testing

### Manual Testing Checklist

**Phase 1 (Authentication):**
- [ ] Successfully logs in to Schoology
- [ ] Saves session cookies
- [ ] Reuses session on next run (doesn't re-login)
- [ ] Handles wrong password gracefully
- [ ] Handles 2FA if present

**Phase 2 (Data Extraction):**
- [ ] Extracts all assignments across all courses
- [ ] Due dates parsed correctly
- [ ] Handles missing due dates (unscheduled assignments)
- [ ] Extracts all grades with correct scores
- [ ] Identifies test/quiz events
- [ ] Collects study materials

**Phase 3 (Database):**
- [ ] Data saves to SQLite correctly
- [ ] No duplicates on repeated runs
- [ ] Updates existing records when data changes
- [ ] Detects new assignments since last run

**Phase 4 (Analysis):**
- [ ] Correctly identifies grades < 80%
- [ ] Groups weak areas by subject
- [ ] Calculates trends (week-over-week change)
- [ ] Prioritizes by urgency (due date proximity)

**Phase 5 (Email):**
- [ ] Email sends successfully
- [ ] HTML formatting renders correctly
- [ ] All sections populated with real data
- [ ] Links to Schoology work (if included)
- [ ] Received in inbox (not spam)

**Phase 6 (Automation):**
- [ ] Cron job triggers at scheduled time
- [ ] Complete end-to-end run succeeds
- [ ] Logs written correctly
- [ ] Errors logged with details
- [ ] Report email received automatically

### Edge Case Testing
- [ ] No assignments due (empty list)
- [ ] All assignments overdue
- [ ] Perfect scores (all 100%)
- [ ] Missing grades (not yet graded)
- [ ] Course with no assignments posted
- [ ] Network interruption during scrape
- [ ] Schoology down/maintenance
- [ ] SMTP server unavailable

### Automated Tests (Optional but Recommended)
- Unit tests for date parsing
- Unit tests for percentage calculations
- Unit tests for prioritization logic
- Mock tests for scraper (using saved HTML)

---

## Expected Timeline

**Total Estimated Duration:** 3-4 weeks (part-time work)

- **Week 1**: Authentication + basic assignment scraping + grades (Phases 1-2)
- **Week 2**: Database setup + multi-course support + analysis logic (Phases 3-4)
- **Week 3**: Email generation + testing + cron setup (Phases 5-6)
- **Week 4**: Robustness, edge cases, documentation (Phase 7)

**MVP (Minimum Viable Product):** Week 2 completion
- Can extract assignments and grades
- Can identify weak areas
- Can send basic email report (even if manual trigger)

**Production Ready:** Week 3 completion
- Fully automated daily runs
- Comprehensive error handling
- Polished email format

---

## Success Criteria

The project is successful when:

1. **Automation**: System runs daily without manual intervention
2. **Completeness**: Email includes:
   - All upcoming/overdue assignments
   - All recent grades
   - Identified weak areas (< 80%)
   - Upcoming tests/quizzes
   - New study materials
   - Week-over-week trends
3. **Reliability**: Runs successfully 95%+ of the time over a month
4. **Actionability**: Parent can read report in 2-3 minutes and create clear daily plan
5. **Maintenance**: Can update selectors within 30 minutes when Schoology changes UI

---

## Next Immediate Steps

1. Clarify final requirements (see below)
2. Set up development environment
3. Create project structure
4. Install Playwright and dependencies
5. Begin Phase 1 (authentication)

---

## Final Configuration Details

**Confirmed Settings:**
- **Report email**: Same as Schoology login email
- **Run time**: 6:00 PM daily
- **Schedule**: Weekdays only (Monday - Friday)
- **2FA**: Not enabled (simplifies automation)
- **Weak threshold**: < 80%
- **Historical tracking**: Enabled
- **Data retention**: 1 year (365 days)

**Still Need to Configure During Setup:**
- **Timezone**: Will prompt during setup
- **SMTP provider**: Will configure Gmail app password during setup
- **Schoology login credentials**: Will be stored securely in .env file

---

## References & Resources

### Research Sources
- [Schoology API Documentation](https://developers.schoology.com/api/) - For understanding data structure (even though we can't use it)
- [What Parents Can See in Schoology](https://spsedtech.wordpress.com/2015/09/24/what-parents-can-and-cannot-see-in-schoology/) - Parent account capabilities
- [Playwright Python Documentation](https://playwright.dev/python/) - Automation framework
- [Python Headless Browser Guide](https://www.browsercat.com/post/python-headless-browser-automation-guide) - Best practices

### Key Findings from Research
- Parent accounts can see all assignments, grades, calendar events, materials
- No API access without admin privileges
- Parent access codes are for account registration only
- Web automation is the only viable approach for parent accounts
