import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# --- Schoology ---
SCHOOLOGY_DOMAIN = os.environ["SCHOOLOGY_DOMAIN"]
SCHOOLOGY_BASE_URL = f"https://{SCHOOLOGY_DOMAIN}"
SCHOOLOGY_CHILD_ID = os.environ.get("SCHOOLOGY_CHILD_ID", "")
SCHOOLOGY_EMAIL = os.environ.get("SCHOOLOGY_EMAIL", "")
SCHOOLOGY_PASSWORD = os.environ.get("SCHOOLOGY_PASSWORD", "")

# --- SMTP ---
SMTP_HOST = os.environ["SMTP_HOST"]
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ["SMTP_USER"]
SMTP_PASSWORD = os.environ["SMTP_PASSWORD"]
# Recipient lists (comma-separated)
STUDENT_EMAIL_TO = [addr.strip() for addr in os.environ["STUDENT_EMAIL_TO"].split(",")]
PARENT_EMAIL_TO = [addr.strip() for addr in os.environ["PARENT_EMAIL_TO"].split(",")]
EMAIL_FROM = os.environ.get("EMAIL_FROM", SMTP_USER)

# --- Thresholds ---
GRADE_WARN_THRESHOLD = float(os.environ.get("GRADE_WARN_THRESHOLD", "80"))

# --- Test Prep ---
ENABLE_TEST_PREP = os.environ.get("ENABLE_TEST_PREP", "false").lower() in ("true", "1", "yes")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")

# --- Paths ---
MATERIALS_DIR = PROJECT_ROOT / "data" / "materials"
COOKIES_FILE = PROJECT_ROOT / "cookies.json"
LAST_RUN_FILE = PROJECT_ROOT / "last_run.json"
GRADE_HISTORY_FILE = PROJECT_ROOT / "grade_history.json"
FEEDBACK_HISTORY_FILE = PROJECT_ROOT / "feedback_history.json"
FEEDBACK_HISTORY_DAYS = int(os.environ.get("FEEDBACK_HISTORY_DAYS", "30"))

# --- Selectors ---
_selectors_path = PROJECT_ROOT / "selectors.yaml"
OVERDUE_WHITELIST_FILE = PROJECT_ROOT / "overdue_whitelist.yaml"


def load_selectors() -> dict:
    with open(_selectors_path) as f:
        return yaml.safe_load(f)


def load_overdue_whitelist() -> dict:
    if not OVERDUE_WHITELIST_FILE.exists():
        return {"titles": [], "patterns": [], "courses": []}
    with open(OVERDUE_WHITELIST_FILE) as f:
        data = yaml.safe_load(f) or {}
    return {
        "titles": [t.lower() for t in (data.get("titles") or [])],
        "patterns": [p.lower() for p in (data.get("patterns") or [])],
        "courses": [c.lower() for c in (data.get("courses") or [])],
    }
