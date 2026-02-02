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

# --- SMTP ---
SMTP_HOST = os.environ["SMTP_HOST"]
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ["SMTP_USER"]
SMTP_PASSWORD = os.environ["SMTP_PASSWORD"]
# EMAIL_TO can be a single address or comma-separated list
EMAIL_TO = [addr.strip() for addr in os.environ["EMAIL_TO"].split(",")]
EMAIL_FROM = os.environ.get("EMAIL_FROM", SMTP_USER)

# --- Thresholds ---
GRADE_WARN_THRESHOLD = float(os.environ.get("GRADE_WARN_THRESHOLD", "80"))

# --- Test Prep ---
ENABLE_TEST_PREP = os.environ.get("ENABLE_TEST_PREP", "false").lower() in ("true", "1", "yes")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")

# --- Paths ---
COOKIES_FILE = PROJECT_ROOT / "cookies.json"
LAST_RUN_FILE = PROJECT_ROOT / "last_run.json"
GRADE_HISTORY_FILE = PROJECT_ROOT / "grade_history.json"
FEEDBACK_HISTORY_FILE = PROJECT_ROOT / "feedback_history.json"
FEEDBACK_HISTORY_DAYS = int(os.environ.get("FEEDBACK_HISTORY_DAYS", "30"))

# --- Selectors ---
_selectors_path = PROJECT_ROOT / "selectors.yaml"


def load_selectors() -> dict:
    with open(_selectors_path) as f:
        return yaml.safe_load(f)
