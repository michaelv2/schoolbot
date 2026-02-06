import json
import re
import smtplib
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from difflib import SequenceMatcher as _SequenceMatcher

from schoolbot import config

_TEST_PATTERN = re.compile(r"\b(test|quiz|quest|exam)\b", re.IGNORECASE)


def _load_last_run() -> dict | None:
    if config.LAST_RUN_FILE.exists():
        return json.loads(config.LAST_RUN_FILE.read_text())
    return None


def _save_run(data: dict) -> None:
    # Exclude internal browser references (non-serializable)
    saveable = {k: v for k, v in data.items() if not k.startswith("_")}
    config.LAST_RUN_FILE.write_text(json.dumps(saveable, indent=2))


def _load_grade_history() -> dict:
    """Load {item_key: first_seen_date_str} mapping."""
    if config.GRADE_HISTORY_FILE.exists():
        return json.loads(config.GRADE_HISTORY_FILE.read_text())
    return {}


def _save_grade_history(history: dict) -> None:
    config.GRADE_HISTORY_FILE.write_text(json.dumps(history, indent=2))


def _load_feedback_history() -> dict:
    """Load feedback history or return empty structure."""
    if config.FEEDBACK_HISTORY_FILE.exists():
        try:
            return json.loads(config.FEEDBACK_HISTORY_FILE.read_text())
        except Exception as e:
            print(f"  Warning: corrupted feedback history, starting fresh: {e}")
            return {"feedback_history": [], "persistent_issues": {}}
    return {"feedback_history": [], "persistent_issues": {}}


def _save_feedback_history(history: dict) -> None:
    """Save feedback history with automatic pruning of old entries."""
    cutoff_date = datetime.now() - timedelta(days=config.FEEDBACK_HISTORY_DAYS)
    cutoff_str = cutoff_date.strftime("%Y-%m-%d")

    # Prune old entries
    history["feedback_history"] = [
        entry for entry in history["feedback_history"]
        if entry.get("date", "") >= cutoff_str
    ]

    config.FEEDBACK_HISTORY_FILE.write_text(json.dumps(history, indent=2))


def _build_feedback_context(
    grades: list[dict],
    overdue: list[dict],
    tests: list[dict],
    recent: list[dict]
) -> dict:
    """Extract context snapshot for tracking feedback relevance."""
    low_grades = []
    for g in grades:
        numeric = g.get("grade_numeric")
        if numeric and numeric < config.GRADE_WARN_THRESHOLD:
            low_grades.append(f"{g.get('course', '')} {g.get('letter', '')}".strip())

    recent_high = []
    recent_low = []
    for r in recent[:5]:  # Just top 5 for context
        pct_str = r.get("pct", "")
        if pct_str and "%" in pct_str:
            try:
                pct = float(pct_str.rstrip("%"))
                course = r.get("course", "")
                if pct >= 90:
                    recent_high.append(f"{course}: {pct_str}")
                elif pct < config.GRADE_WARN_THRESHOLD:
                    recent_low.append(f"{course}: {pct_str}")
            except ValueError:
                pass

    return {
        "overdue_count": len(overdue),
        "upcoming_tests": [t.get("title", "") for t in tests[:3]],
        "low_grades": low_grades[:3],
        "recent_high_scores": recent_high,
        "recent_low_scores": recent_low,
    }


def _extract_feedback_components(feedback: str) -> dict:
    """Parse feedback into encouragement + joke components."""
    # Split by double newline first (common separator between encouragement and joke)
    parts = [p.strip() for p in feedback.split("\n\n") if p.strip()]

    if not parts:
        return {"encouragement": "", "joke": ""}

    # If we have 2+ parts, last one is likely the joke
    if len(parts) >= 2:
        return {
            "encouragement": parts[0],
            "joke": parts[-1]
        }

    # Otherwise, split by single newline
    lines = [line.strip() for line in feedback.split("\n") if line.strip()]

    if not lines:
        return {"encouragement": "", "joke": ""}

    # Simple heuristic: last line is usually the joke if it's a question or short
    if len(lines) >= 2 and (lines[-1].endswith("?") or len(lines[-1]) < 80):
        return {
            "encouragement": " ".join(lines[:-1]),
            "joke": lines[-1]
        }

    # Otherwise, treat it all as encouragement
    return {
        "encouragement": " ".join(lines),
        "joke": ""
    }


def _detect_persistent_issues(context: dict, history: dict) -> dict:
    """Track multi-day problems that deserve repeated emphasis."""
    issues = history.get("persistent_issues", {})
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    # Helper: check if this issue was already counted today (avoid inflation
    # when the script runs multiple times in one day).
    def _already_counted_today(issue_data: dict) -> bool:
        return issue_data.get("last_counted") == today

    # Overdue assignments: 5+ items for 3+ consecutive days
    overdue_count = context.get("overdue_count", 0)
    if overdue_count >= 5:
        if "overdue_assignments" in issues:
            if _already_counted_today(issues["overdue_assignments"]):
                # Already incremented today; update count but don't inflate days
                issues["overdue_assignments"]["count_history"][-1] = overdue_count
            else:
                # Check if yesterday had overdue too (continuity)
                last_entries = [e for e in history.get("feedback_history", [])
                                if e.get("date") == yesterday]
                if last_entries and last_entries[-1].get("context", {}).get("overdue_count", 0) >= 5:
                    issues["overdue_assignments"]["consecutive_days"] += 1
                    issues["overdue_assignments"]["count_history"].append(overdue_count)
                else:
                    issues["overdue_assignments"] = {
                        "first_detected": today,
                        "consecutive_days": 1,
                        "count_history": [overdue_count],
                    }
                issues["overdue_assignments"]["last_counted"] = today
        else:
            issues["overdue_assignments"] = {
                "first_detected": today,
                "consecutive_days": 1,
                "count_history": [overdue_count],
                "last_counted": today,
            }
    else:
        issues.pop("overdue_assignments", None)

    # Low grades: same course below threshold for 5+ consecutive days
    low_grades = context.get("low_grades", [])
    current_low_courses = set()

    for low_grade in low_grades:
        course_key = f"low_grade_{low_grade.replace(' ', '_')}"
        current_low_courses.add(course_key)

        if course_key in issues:
            if _already_counted_today(issues[course_key]):
                pass  # Already counted today
            else:
                last_entries = [e for e in history.get("feedback_history", [])
                                if e.get("date") == yesterday]
                if last_entries and low_grade in last_entries[-1].get("context", {}).get("low_grades", []):
                    issues[course_key]["consecutive_days"] += 1
                else:
                    issues[course_key] = {
                        "first_detected": today,
                        "consecutive_days": 1,
                    }
                issues[course_key]["last_counted"] = today
        else:
            issues[course_key] = {
                "first_detected": today,
                "consecutive_days": 1,
                "last_counted": today,
            }

    # Clear resolved low grades
    for key in list(issues.keys()):
        if key.startswith("low_grade_") and key not in current_low_courses:
            issues.pop(key)

    return issues


def _similar_strings(s1: str, s2: str, threshold: float = 0.8) -> bool:
    """Check if two strings are similar using difflib."""
    ratio = _SequenceMatcher(None, s1.lower(), s2.lower()).ratio()
    return ratio >= threshold


def _similar_context(ctx1: dict, ctx2: dict) -> bool:
    """Compare context dicts for similarity."""
    # Contexts are similar if key metrics match
    return (
        ctx1.get("overdue_count") == ctx2.get("overdue_count")
        and ctx1.get("upcoming_tests") == ctx2.get("upcoming_tests")
        and ctx1.get("low_grades") == ctx2.get("low_grades")
    )


def _is_feedback_repetitive(
    feedback: str,
    context: dict,
    history: dict,
    persistent_issues: dict
) -> bool:
    """Three-tier detection with persistent issue override."""

    # If there are persistent issues (3+ days), allow repetition
    has_persistent = any(
        issue.get("consecutive_days", 0) >= 3
        for issue in persistent_issues.values()
    )
    if has_persistent:
        return False

    feedback_entries = history.get("feedback_history", [])
    if not feedback_entries:
        return False

    # Tier 1: Exact match in last 7 days
    seven_days_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    recent_7d = [e for e in feedback_entries if e.get("date", "") >= seven_days_ago]

    for entry in recent_7d:
        if entry.get("feedback_text", "") == feedback:
            return True

    # Tier 2: Similar joke in last 14 days
    fourteen_days_ago = (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d")
    recent_14d = [e for e in feedback_entries if e.get("date", "") >= fourteen_days_ago]

    current_components = _extract_feedback_components(feedback)
    current_joke = current_components.get("joke", "")

    if current_joke:
        for entry in recent_14d:
            past_joke = entry.get("components", {}).get("joke", "")
            if past_joke and _similar_strings(current_joke, past_joke, threshold=0.7):
                return True

    # Tier 3: Similar context (today or yesterday) + similar encouragement
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    recent_entries = [e for e in feedback_entries
                      if e.get("date") in (today, yesterday)]

    current_encouragement = current_components.get("encouragement", "")
    if current_encouragement:
        for entry in recent_entries:
            entry_context = entry.get("context", {})
            if _similar_context(context, entry_context):
                past_encouragement = entry.get("components", {}).get("encouragement", "")
                if past_encouragement and _similar_strings(
                    current_encouragement, past_encouragement, threshold=0.75
                ):
                    return True

    return False


def _item_key(course: str, title: str) -> str:
    """Unique key for a graded item."""
    return f"{course}||{title}"


def _update_grade_history(grades: list[dict]) -> dict:
    """Update history with any newly-observed scored items. Returns the history.

    On the first run (no history file), seeds all existing items with a
    sentinel date so they won't appear in the 'recent' section. Only
    genuinely new items on subsequent runs get today's date.
    """
    is_first_run = not config.GRADE_HISTORY_FILE.exists()
    history = _load_grade_history()
    today = datetime.now().strftime("%Y-%m-%d")
    # Sentinel date far in the past so seeded items never count as "recent"
    seed_date = "2000-01-01"

    for g in grades:
        for item in g.get("items", []):
            try:
                awarded = float(item["awarded"])
                max_pts = float(item["max"])
                if max_pts <= 0:
                    continue
            except (ValueError, KeyError):
                continue
            key = _item_key(g["course"], item["title"])
            if key not in history:
                history[key] = seed_date if is_first_run else today
    _save_grade_history(history)
    return history


def _find_new_assignments(current: list[dict], previous: list[dict]) -> list[dict]:
    prev_titles = {a["title"] for a in previous}
    return [a for a in current if a["title"] not in prev_titles]


def _effective_grade(g: dict) -> float | None:
    """Get the course grade: Schoology's value if available, otherwise computed."""
    if g["grade"] is not None:
        return g["grade"]
    pct_str = _compute_overall_pct(g.get("items", []))
    if pct_str == "—":
        return None
    try:
        return float(pct_str.replace("%", ""))
    except ValueError:
        return None


def _low_grades(grades: list[dict]) -> list[dict]:
    results = []
    for g in grades:
        eff = _effective_grade(g)
        if eff is not None and eff < config.GRADE_WARN_THRESHOLD:
            results.append(g)
    return results


def _sort_by_due_date(assignments: list[dict]) -> list[dict]:
    def sort_key(a):
        try:
            return datetime.strptime(a["due_date"], "%b %d, %Y")
        except (ValueError, KeyError):
            return datetime.max
    return sorted(assignments, key=sort_key)


def _filter_future_assignments(assignments: list[dict]) -> list[dict]:
    """Remove assignments whose due date is today or earlier."""
    tomorrow = (datetime.now() + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    results = []
    for a in assignments:
        due = a.get("due_date", "")
        dt = None
        for fmt in ("%b %d, %Y", "%m/%d/%y"):
            try:
                dt = datetime.strptime(due, fmt)
                break
            except ValueError:
                continue
        if dt is None:
            results.append(a)  # keep items with unparseable dates
            continue
        if dt >= tomorrow:
            results.append(a)
    return results


def _assignments_from_calendar(calendar_events: list[dict]) -> list[dict]:
    """Extract assignment-type calendar entries as upcoming assignments.

    Parent accounts can't see /home/upcoming, so calendar assignment events
    serve as the fallback source for the upcoming assignments section.
    """
    now = datetime.now()
    results = []
    for ev in calendar_events:
        if ev.get("type") != "assignment":
            continue
        try:
            dt = datetime.fromisoformat(ev["start"].replace("Z", "+00:00"))
            # Strip timezone for comparison with naive datetime.now()
            dt = dt.replace(tzinfo=None)
            if ev.get("all_day", False) or dt.hour < 6:
                dt = dt - timedelta(hours=5)
            # Only include future assignments
            if dt < now:
                continue
            due_date = dt.strftime("%b %d, %Y")
        except (ValueError, KeyError, TypeError):
            due_date = ""
        # Try to extract course_id from event URL (e.g. /course/123/...)
        course_id = ""
        url = ev.get("url", "")
        if "/course/" in url:
            m = re.search(r"/course/(\d+)/", url)
            if m:
                course_id = m.group(1)

        results.append({
            "title": ev["title"],
            "course": "",
            "course_id": course_id,
            "due_date": due_date,
        })
    return results


def _upcoming_tests(assignments: list[dict], calendar_events: list[dict]) -> list[dict]:
    """Find upcoming tests/quizzes/exams from both assignments and calendar events."""
    tests = []

    # From assignments page
    for a in assignments:
        if _TEST_PATTERN.search(a["title"]):
            tests.append(a)

    # From calendar events
    now = datetime.now()
    for ev in calendar_events:
        if not _TEST_PATTERN.search(ev["title"]):
            continue
        # Parse ISO date and convert to local time
        try:
            dt = datetime.fromisoformat(ev["start"].replace("Z", "+00:00"))
            # For all-day events, Schoology stores them as UTC timestamps
            # that are off by one day. Subtract 5 hours to convert to EST/CDT.
            # This handles the common case where all-day events have time ~04:59:59Z
            if ev.get("all_day", False) or dt.hour < 6:
                dt = dt - timedelta(hours=5)
            event_date = dt.strftime("%-m/%d/%y")
        except (ValueError, KeyError, TypeError):
            event_date = ""

        # Check if this test already exists from assignments
        matching_test = next((t for t in tests if t["title"] == ev["title"]), None)
        if matching_test:
            # Update the due_date to use the calendar's date (more accurate)
            if event_date:
                matching_test["due_date"] = event_date
            continue

        tests.append({
            "title": ev["title"],
            "course": "",
            "due_date": event_date,
        })

    return tests


def _period_label(period_str: str) -> str:
    """Extract short label like 'Q1' from 'Q1: 2025-09-02 - 2025-11-07'."""
    return period_str.split(":")[0].strip() if period_str else ""


def _compute_period_pct(items: list[dict], period_prefix: str) -> str:
    """Compute weighted grade for items in a given period.

    Groups items by category, computes each category's simple percentage,
    then applies category weights. Falls back to unweighted if weights
    are missing.
    """
    # Filter to this period
    period_items = [
        i for i in items
        if _period_label(i.get("period", "")) == period_prefix
    ]
    if not period_items:
        return "—"

    # Group by category
    categories: dict[str, list[dict]] = {}
    for item in period_items:
        cat = item.get("category", "")
        categories.setdefault(cat, []).append(item)

    # Compute per-category percentage and collect weights
    cat_results = []  # (percentage, weight_or_None)
    for cat_name, cat_items in categories.items():
        total_a = 0
        total_m = 0
        weight = None
        for item in cat_items:
            try:
                a = float(item["awarded"])
                m = float(item["max"])
                if m > 0:
                    total_a += a
                    total_m += m
            except (ValueError, KeyError):
                continue
            if weight is None and item.get("category_weight") is not None:
                weight = item["category_weight"]
        if total_m > 0:
            cat_results.append((total_a / total_m * 100, weight))

    if not cat_results:
        return "—"

    # If all categories have weights, compute weighted average
    all_have_weights = all(w is not None for _, w in cat_results)
    if all_have_weights and len(cat_results) > 1:
        total_weight = sum(w for _, w in cat_results)
        if total_weight > 0:
            weighted = sum(pct * w / total_weight for pct, w in cat_results)
            return f"{weighted:.0f}%"

    # Fallback: simple unweighted average across categories
    avg = sum(pct for pct, _ in cat_results) / len(cat_results)
    return f"{avg:.0f}%"


def _compute_overall_pct(items: list[dict]) -> str:
    """Compute weighted overall grade across all items (all periods combined)."""
    categories: dict[str, list[dict]] = {}
    for item in items:
        cat = item.get("category", "")
        categories.setdefault(cat, []).append(item)

    cat_results = []
    for cat_name, cat_items in categories.items():
        total_a = 0
        total_m = 0
        weight = None
        for item in cat_items:
            try:
                a = float(item["awarded"])
                m = float(item["max"])
                if m > 0:
                    total_a += a
                    total_m += m
            except (ValueError, KeyError):
                continue
            if weight is None and item.get("category_weight") is not None:
                weight = item["category_weight"]
        if total_m > 0:
            cat_results.append((total_a / total_m * 100, weight))

    if not cat_results:
        return "—"

    all_have_weights = all(w is not None for _, w in cat_results)
    if all_have_weights and len(cat_results) > 1:
        total_weight = sum(w for _, w in cat_results)
        if total_weight > 0:
            weighted = sum(pct * w / total_weight for pct, w in cat_results)
            return f"{weighted:.0f}%"

    avg = sum(pct for pct, _ in cat_results) / len(cat_results)
    return f"{avg:.0f}%"


def _parse_item_date(due_date: str) -> datetime | None:
    """Parse grade item due_date like '1/23/26 2:00pm' into a datetime."""
    if not due_date:
        return None
    try:
        return datetime.strptime(due_date.strip().upper(), "%m/%d/%y %I:%M%p")
    except ValueError:
        pass
    # Some dates may lack the time portion
    try:
        return datetime.strptime(due_date.strip(), "%m/%d/%y")
    except ValueError:
        return None


def _overdue_items(grades: list[dict], max_age_days: int = 30) -> list[dict]:
    """Find grade items with a past due date and no score.

    Excludes 'class preparation' and 'class participation' items,
    plus anything matched by overdue_whitelist.yaml.
    """
    whitelist = config.load_overdue_whitelist()
    # Normalize whitespace in whitelist titles to handle Schoology quirks
    wl_titles = [re.sub(r'\s+', ' ', t) for t in whitelist["titles"]]
    now = datetime.now()
    cutoff = now - timedelta(days=max_age_days)
    results = []
    for g in grades:
        course_name = g.get("course", "")
        if course_name.lower() in whitelist["courses"]:
            continue
        for item in g.get("items", []):
            title = item.get("title", "").lower()
            # Normalize whitespace for matching
            title_normalized = re.sub(r'\s+', ' ', title)
            # Skip class preparation and participation items
            if "class preparation" in title or "class participation" in title:
                continue
            if title_normalized in wl_titles:
                continue
            if any(p in title_normalized for p in whitelist["patterns"]):
                continue

            dt = _parse_item_date(item.get("due_date", ""))
            if dt is None or dt >= now or dt < cutoff:
                continue
            # Check if it has no score
            try:
                float(item["awarded"])
                m = float(item["max"])
                if m > 0:
                    continue  # Has a score — not overdue
            except (ValueError, KeyError, TypeError):
                pass
            results.append({
                "course": g["course"],
                "title": item["title"],
                "due_date": dt,
                "due_display": dt.strftime("%-m/%d"),
            })
    results.sort(key=lambda r: r["due_date"])
    return results


def _recent_graded_items(grades: list[dict], history: dict, days: int = 14) -> list[dict]:
    """Collect graded items from the last N days across all courses.

    Uses due_date when available, otherwise falls back to the first-seen
    date recorded in grade_history.json.
    """
    cutoff = datetime.now() - timedelta(days=days)
    results = []
    for g in grades:
        course = g["course"]
        for item in g.get("items", []):
            # Only include items with actual numeric scores
            try:
                awarded = float(item["awarded"])
                max_pts = float(item["max"])
                if max_pts <= 0:
                    continue
            except (ValueError, KeyError):
                continue

            # Hybrid date: prefer due_date, fall back to history
            dt = _parse_item_date(item.get("due_date", ""))
            if dt is None:
                key = _item_key(course, item["title"])
                first_seen = history.get(key)
                if first_seen:
                    try:
                        dt = datetime.strptime(first_seen, "%Y-%m-%d")
                    except ValueError:
                        continue
                else:
                    continue

            if dt < cutoff:
                continue

            pct = awarded / max_pts * 100
            results.append({
                "course": course,
                "title": item["title"],
                "score": f"{awarded:g}/{max_pts:g}",
                "pct": f"{pct:.0f}%",
                "date": dt,
                "date_display": dt.strftime("%-m/%d"),
            })
    results.sort(key=lambda r: r["date"], reverse=True)
    return results


def _get_period_labels(grades: list[dict]) -> list[str]:
    """Find all unique period short labels (e.g. Q1, Q2) across all courses, sorted."""
    labels = set()
    for g in grades:
        for item in g.get("items", []):
            label = _period_label(item.get("period", ""))
            if label:
                labels.add(label)
    return sorted(labels)


def _todays_focus(
    assignments: list[dict],
    upcoming_tests: list[dict],
    low_grades: list[dict],
    overdue: list[dict],
    recent_items: list[dict],
) -> list[dict]:
    """Select up to 4 focus items for today's work blocks.

    Priority order: overdue → test prep → low-grade review → upcoming homework.
    """
    items: list[dict] = []
    used_titles: set[str] = set()

    def _course_suffix(course: str) -> str:
        return f" ({course})" if course else ""

    # 1. Overdue — nearest-due item
    if overdue:
        o = overdue[0]  # already sorted by due_date
        items.append({
            "action": f"Finish overdue: {o['title']}{_course_suffix(o['course'])}",
            "detail": o["course"],
        })
        used_titles.add(o["title"])

    # 2. Test prep — nearest upcoming test
    if upcoming_tests and len(items) < 4:
        t = upcoming_tests[0]
        items.append({
            "action": f"Study for {t['title']}{_course_suffix(t['course'])}",
            "detail": t["course"],
        })
        used_titles.add(t["title"])

    # 3. Low-grade review — lowest-grade course
    if low_grades and len(items) < 4:
        lowest = min(low_grades, key=lambda g: _effective_grade(g) or 100)
        eff = _effective_grade(lowest)
        pct = f"{eff:.0f}%" if eff is not None else "low"
        items.append({
            "action": f"Review {lowest['course']} \u2014 grade is {pct}",
            "detail": lowest["course"],
        })

    # 4. Upcoming homework — nearest-due that isn't already picked
    if assignments and len(items) < 4:
        for a in assignments:
            if a["title"] not in used_titles:
                items.append({
                    "action": f"Work on {a['title']}{_course_suffix(a['course'])}",
                    "detail": a["course"],
                })
                break

    return items[:4]


def _render_html(
    assignments: list[dict],
    new_assignments: list[dict],
    grades: list[dict],
    low_grades: list[dict],
    upcoming_tests: list[dict],
    recent_items: list[dict],
    overdue: list[dict],
    test_prep: dict | None = None,
    student_feedback: str = "",
    focus_items: list[dict] | None = None,
    variant: str = "student",
) -> str:
    now = datetime.now().strftime("%B %d, %Y %I:%M %p")
    th = 'style="text-align:left;padding:8px;border-bottom:1px solid #ddd;"'
    td = 'style="padding:8px;border-bottom:1px solid #eee;"'

    # Show all quarters that have graded items
    display_periods = _get_period_labels(grades)

    # Assignments table rows
    assignment_rows = ""
    new_titles = {a["title"] for a in new_assignments}
    for a in assignments:
        is_new = a["title"] in new_titles
        marker = ' <span style="color:#e74c3c;font-weight:bold;">NEW</span>' if is_new else ""
        assignment_rows += f"""
        <tr>
            <td {td}>{a['title']}{marker}</td>
            <td {td}>{a['course']}</td>
            <td {td}>{a['due_date']}</td>
        </tr>"""

    # Upcoming tests table rows (with optional topic summaries)
    test_prep = test_prep or {}
    test_rows = ""
    has_study_guides = False
    for t in upcoming_tests:
        prep = test_prep.get(t["title"], {})
        summary = prep.get("summary", "")
        if prep.get("guide"):
            has_study_guides = True

        test_rows += f"""
        <tr>
            <td {td}>{t['title']}</td>
            <td {td}>{t['course']}</td>
            <td {td}>{t['due_date']}</td>
        </tr>"""

        if summary:
            # Convert markdown formatting to HTML
            summary_html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', summary)
            summary_html = re.sub(r'\*(.+?)\*', r'<em>\1</em>', summary_html)
            summary_html = summary_html.replace("\n", "<br>")
            test_rows += f"""
        <tr>
            <td colspan="3" style="padding:8px 8px 16px 24px;border-bottom:1px solid #eee;background:#f0f7ff;">
                <strong style="color:#2980b9;">Topics to Study:</strong><br>
                <span style="font-size:13px;color:#444;">{summary_html}</span>
            </td>
        </tr>"""

    # Grades table rows
    grade_rows = ""
    low_courses = {g["course"] for g in low_grades}
    for g in grades:
        color = "color:#e74c3c;font-weight:bold;" if g["course"] in low_courses else ""
        items = g.get("items", [])

        # Use Schoology's overall if available, otherwise compute from items
        display = g["grade_display"] or ""
        letter = g["letter"] or ""
        if not display and items:
            display = _compute_overall_pct(items)
            letter = ""  # can't reliably assign a letter

        q_cells = ""
        for q in display_periods:
            q_cells += f"\n            <td {td}>{_compute_period_pct(items, q)}</td>"

        grade_rows += f"""
        <tr>
            <td {td}>{g['course']}</td>
            <td {td} style="{color}">{display}</td>
            <td {td} style="{color}">{letter}</td>{q_cells}
        </tr>"""

    # Warnings section
    warnings = ""
    if low_grades:
        items_html = "".join(
            f"<li>{g['course']}: {g['grade_display']} ({g['letter']})</li>"
            for g in low_grades
        )
        warnings = f"""
        <div style="background:#fdf2f2;border-left:4px solid #e74c3c;padding:12px;margin:16px 0;">
            <strong>Grades below {config.GRADE_WARN_THRESHOLD}%:</strong>
            <ul>{items_html}</ul>
        </div>"""

    # Overdue items rows
    overdue_rows = ""
    for o in overdue:
        overdue_rows += f"""
        <tr>
            <td {td}>{o['title']}</td>
            <td {td}>{o['course']}</td>
            <td {td}>{o['due_display']}</td>
        </tr>"""

    # Recent graded items rows
    recent_rows = ""
    for r in recent_items:
        recent_rows += f"""
        <tr>
            <td {td}>{r['date_display']}</td>
            <td {td}>{r['course']}</td>
            <td {td}>{r['title']}</td>
            <td {td}>{r['score']} ({r['pct']})</td>
        </tr>"""

    q_headers = "".join(f'\n                <th {th}>{q}</th>' for q in display_periods)

    # Today's Focus section
    focus_items = focus_items or []
    if focus_items:
        focus_rows = ""
        for fi in focus_items:
            focus_rows += f"""
            <div style="margin-bottom:16px;">
                <span style="font-size:18px;">&#9744;</span>
                <strong>{fi['action']}</strong>
                <div style="color:#888;font-size:13px;margin:4px 0 0 26px;">
                    Write &ldquo;done&rdquo; criteria: ________________________________
                </div>
            </div>"""
        focus_html = f"""
        <h3>Today's Focus</h3>
        <p style="color:#666;font-size:14px;">Plan your work in 15\u201320 min blocks.</p>
        <div style="border-left:4px solid #27ae60;background:#f0faf0;padding:12px 16px;margin:16px 0;">
            {focus_rows}
        </div>"""
    else:
        focus_html = """
        <h3>Today's Focus</h3>
        <div style="border-left:4px solid #27ae60;background:#f0faf0;padding:12px 16px;margin:16px 0;">
            <p style="color:#27ae60;font-size:15px;">All caught up! Nothing urgent today \u2014 great job staying on top of things.</p>
        </div>"""

    is_student = variant == "student"
    bot_name = "SchoolBot" if is_student else "ParentBot"

    # Student-only sections
    feedback_section = ""
    if is_student and student_feedback:
        feedback_section = (
            '<div style="background:#f0f7ff;border-left:4px solid #3498db;'
            'padding:12px 16px;margin:16px 0;font-size:15px;line-height:1.5;">'
            + student_feedback.replace(chr(10), "<br>") + '</div>'
        )

    focus_section = focus_html if is_student else ""

    # Parent-only sections
    grades_section = ""
    recent_section = ""
    if not is_student:
        grades_section = f"""
        <h3>Grades ({len(grades)} courses)</h3>
        {"<p>No grades found.</p>" if not grades else f'''
        <table style="border-collapse:collapse;width:100%;">
            <tr style="background:#f4f4f4;">
                <th {th}>Course</th>
                <th {th}>Overall</th>
                <th {th}>Letter</th>{q_headers}
            </tr>
            {grade_rows}
        </table>'''}"""

        recent_section = f"""
        <h3>Recent Grades (Past 2 Weeks)</h3>
        {"<p>No graded items in the past two weeks.</p>" if not recent_items else f'''
        <table style="border-collapse:collapse;width:100%;">
            <tr style="background:#f4f4f4;">
                <th {th}>Date</th>
                <th {th}>Course</th>
                <th {th}>Item</th>
                <th {th}>Score</th>
            </tr>
            {recent_rows}
        </table>'''}"""

    return f"""
    <html>
    <body style="font-family:sans-serif;max-width:800px;margin:auto;padding:16px;">
        <h2>{bot_name} Report</h2>
        <p style="color:#666;">Generated {now}</p>

        {feedback_section}

        {focus_section}

        {warnings}

        <h3>Upcoming Tests / Quizzes</h3>
        {"<p>No upcoming tests, quizzes, or exams.</p>" if not upcoming_tests else f'''
        {'<p style="color:#2980b9;font-size:13px;">Study guides are attached to this email.</p>' if has_study_guides else ""}
        <table style="border-collapse:collapse;width:100%;">
            <tr style="background:#f4f4f4;">
                <th {th}>Test</th>
                <th {th}>Course</th>
                <th {th}>Due Date</th>
            </tr>
            {test_rows}
        </table>'''}

        <h3>Upcoming Assignments ({len(assignments)})</h3>
        {"<p>No upcoming assignments found.</p>" if not assignments else f'''
        <table style="border-collapse:collapse;width:100%;">
            <tr style="background:#f4f4f4;">
                <th {th}>Assignment</th>
                <th {th}>Course</th>
                <th {th}>Due Date</th>
            </tr>
            {assignment_rows}
        </table>'''}

        {"" if not overdue else f'''
        <h3 style="color:#e74c3c;">Overdue Assignments ({len(overdue)})</h3>
        <table style="border-collapse:collapse;width:100%;">
            <tr style="background:#fdf2f2;">
                <th {th}>Assignment</th>
                <th {th}>Course</th>
                <th {th}>Due Date</th>
            </tr>
            {overdue_rows}
        </table>'''}

        {recent_section}

        {grades_section}

        <p style="color:#999;font-size:12px;margin-top:24px;">
            Sent by {bot_name}
        </p>
    </body>
    </html>
    """


def _send_email(
    subject: str,
    html_body: str,
    recipients: list[str],
    attachments: list[tuple[str, str]] | None = None,
) -> None:
    """Send an HTML email, optionally with file attachments.

    attachments: list of (filename, html_content) tuples for HTML file attachments.
    """
    if attachments:
        msg = MIMEMultipart("mixed")
        body_part = MIMEMultipart("alternative")
        body_part.attach(MIMEText(html_body, "html"))
        msg.attach(body_part)

        for filename, content in attachments:
            att = MIMEText(content, "html")
            att.add_header("Content-Disposition", "attachment", filename=filename)
            msg.attach(att)
    else:
        msg = MIMEMultipart("alternative")
        msg.attach(MIMEText(html_body, "html"))

    msg["Subject"] = subject
    msg["From"] = config.EMAIL_FROM
    msg["To"] = ", ".join(recipients)

    with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT) as server:
        server.starttls()
        server.login(config.SMTP_USER, config.SMTP_PASSWORD)
        server.sendmail(config.EMAIL_FROM, recipients, msg.as_string())


# Map topic keywords found in test titles to school subject names.
# Used when calendar events lack a course field.
_TOPIC_TO_SUBJECT = {
    "energy": "science", "chemistry": "science", "physics": "science",
    "biology": "science", "geology": "science", "lab": "science",
    "atom": "science", "molecule": "science", "element": "science",
    "wave": "science", "rock": "science", "weather": "science",
    "algebra": "math", "geometry": "math", "equation": "math",
    "fraction": "math", "graphing": "math",
    "essay": "english", "reading": "english", "writing": "english",
    "literature": "english", "novel": "english", "vocab": "english",
    "grammar": "english", "poetry": "english",
    "spanish": "spanish", "espanol": "spanish",
    "history": "social studies", "government": "social studies",
    "constitution": "social studies", "war": "social studies",
    "imperialism": "social studies", "revolution": "social studies",
}


def _match_test_to_course_id(test: dict, grades: list[dict]) -> str:
    """Find the course_id for a test by matching its course name to the grades data.

    Falls back to matching keywords from the test title against course names
    and a topic-to-subject mapping when the test has no course field (e.g.
    calendar events).
    """
    test_course = test.get("course", "").lower()

    # 1. Direct match on course name (when available)
    if test_course:
        for g in grades:
            gc = g.get("course", "").lower()
            if test_course in gc or gc in test_course:
                return g.get("course_id", "")
        # Partial word match on course name
        test_words = {w for w in re.split(r'\W+', test_course) if len(w) > 3}
        for g in grades:
            course_words = {w for w in re.split(r'\W+', g.get("course", "").lower()) if len(w) > 3}
            if test_words & course_words:
                return g.get("course_id", "")

    # 2. Match words from the test TITLE against course names
    title = test.get("title", "").lower()
    title_words = {w for w in re.split(r'\W+', title) if len(w) > 3}
    for g in grades:
        course_words = {w for w in re.split(r'\W+', g.get("course", "").lower()) if len(w) > 3}
        if title_words & course_words:
            return g.get("course_id", "")

    # 3. Topic keyword mapping: match title words to subject areas
    for word in re.split(r'\W+', title):
        subject = _TOPIC_TO_SUBJECT.get(word.lower())
        if not subject:
            continue
        for g in grades:
            if subject in g.get("course", "").lower():
                return g.get("course_id", "")

    return ""


def _parse_test_date(test: dict) -> datetime | None:
    """Try to parse a test's due date into a datetime."""
    due = test.get("due_date", "")
    if not due:
        return None
    # Try common formats (strptime uses %m not %-m)
    for fmt in ("%b %d, %Y", "%m/%d/%y"):
        try:
            return datetime.strptime(due, fmt)
        except ValueError:
            continue
    return None


def _sanitize_filename(name: str) -> str:
    """Turn a test title into a safe filename."""
    clean = re.sub(r'[^\w\s-]', '', name)
    clean = re.sub(r'\s+', '_', clean.strip())
    return f"Study_Guide_-_{clean}.html"


def generate_and_send(data: dict, browser_page=None) -> None:
    """Build the report from scraped data, diff against last run, and send email.

    If browser_page is provided and ENABLE_TEST_PREP is on, will scrape
    course materials and generate study guides for upcoming tests.
    """
    grades = data["grades"]
    calendar_events = data.get("calendar_events", [])

    assignments = _sort_by_due_date(data["assignments"])
    if not assignments:
        # Parent accounts can't see /home/upcoming — use calendar events instead
        assignments = _sort_by_due_date(_assignments_from_calendar(calendar_events))
    assignments = _filter_future_assignments(assignments)

    # Fill in course names for calendar-sourced assignments using grades data
    course_id_map = {g.get("course_id", ""): g["course"] for g in grades if g.get("course_id")}
    for a in assignments:
        if not a.get("course") and a.get("course_id"):
            a["course"] = course_id_map.get(a["course_id"], "")

    last = _load_last_run()
    prev_assignments = last["assignments"] if last else []

    new_assignments = _find_new_assignments(assignments, prev_assignments)
    low = _low_grades(grades)
    tests = _filter_future_assignments(_upcoming_tests(assignments, calendar_events))
    history = _update_grade_history(grades)
    recent = _recent_graded_items(grades, history)
    overdue = _overdue_items(grades)

    # --- Test Prep ---
    test_prep = {}  # {test_title: {"summary": str, "guide": str}}
    attachments = []

    if config.ENABLE_TEST_PREP and tests and browser_page is not None:
        from schoolbot import scraper, testprep
        selectors = config.load_selectors()

        for t in tests:
            course_id = _match_test_to_course_id(t, grades)
            if not course_id:
                print(f"  Skipping test prep for '{t['title']}' — no course ID found")
                continue

            test_date = _parse_test_date(t)
            course_name = t.get("course", "Unknown Course")
            test_title = t["title"]
            due_display = t.get("due_date", "")

            print(f"  Scraping materials for '{test_title}' (course {course_id})...")
            try:
                materials = scraper.extract_course_materials(
                    browser_page, course_id, selectors, test_date=test_date,
                )
            except Exception as e:
                print(f"  Warning: materials scraping failed for '{test_title}': {e}")
                continue

            # Check if we got real content or just folder names
            has_real_content = any(
                item.get("text")
                for folder in materials.get("folders", [])
                for item in folder.get("items", [])
            )

            if not has_real_content:
                # No extractable text — show a link to the course materials instead
                materials_link = f"{config.SCHOOLOGY_BASE_URL}/course/{course_id}/materials"
                print(f"  No extractable text for '{test_title}' — using course link")
                test_prep[test_title] = {
                    "summary": f'Review course materials on <a href="{materials_link}">Schoology</a>',
                    "guide": "",
                }
                continue

            print(f"  Generating topic summary for '{test_title}'...")
            summary = testprep.generate_topic_summary(
                materials["text"], course_name, test_title, due_display,
            )

            print(f"  Generating study guide for '{test_title}'...")
            guide = testprep.generate_study_guide(
                materials["text"], course_name, test_title, due_display,
            )

            test_prep[test_title] = {"summary": summary, "guide": guide}

            if guide:
                filename = _sanitize_filename(test_title)
                attachments.append((filename, guide))
                print(f"  Study guide ready: {filename}")

    # --- Student Feedback ---
    student_feedback = ""
    if config.ENABLE_TEST_PREP:
        from schoolbot import testprep

        feedback_history = _load_feedback_history()
        feedback_context = _build_feedback_context(grades, overdue, tests, recent)
        persistent_issues = _detect_persistent_issues(feedback_context, feedback_history)

        # Retry logic for repetitive feedback
        max_retries = 2
        for attempt in range(max_retries + 1):
            print(f"  Generating student feedback{'...' if attempt == 0 else f' (attempt {attempt + 1})...'}")
            student_feedback = testprep.generate_student_feedback(
                grades, recent, tests, overdue, calendar_events,
                feedback_history=feedback_history,
                persistent_issues=persistent_issues,
            )

            if not student_feedback:
                break

            is_repetitive = _is_feedback_repetitive(
                student_feedback, feedback_context, feedback_history, persistent_issues
            )

            if not is_repetitive or attempt == max_retries:
                # Save to history
                components = _extract_feedback_components(student_feedback)
                feedback_entry = {
                    "date": datetime.now().strftime("%Y-%m-%d"),
                    "day_of_week": datetime.now().strftime("%A"),
                    "feedback_text": student_feedback,
                    "context": feedback_context,
                    "components": components
                }
                feedback_history["feedback_history"].append(feedback_entry)
                feedback_history["persistent_issues"] = persistent_issues
                _save_feedback_history(feedback_history)
                break
            else:
                print(f"  Feedback too similar to recent history, regenerating...")

    focus = _todays_focus(assignments, tests, low, overdue, recent)

    # --- Build subject line parts (shared) ---
    subject_parts = f"{len(assignments)} assignments"
    if tests:
        subject_parts += f", {len(tests)} upcoming test{'s' if len(tests) != 1 else ''}"
    if overdue:
        subject_parts += f", {len(overdue)} overdue"
    if low:
        subject_parts += f", {len(low)} low grade{'s' if len(low) != 1 else ''}"
    if new_assignments:
        subject_parts += f" ({len(new_assignments)} new)"

    # --- Student email (SchoolBot) ---
    student_html = _render_html(
        assignments, new_assignments, grades, low, tests, recent, overdue,
        test_prep=test_prep,
        student_feedback=student_feedback,
        focus_items=focus,
        variant="student",
    )
    student_subject = f"SchoolBot: {subject_parts}"
    if attachments:
        student_subject += " + study guides"

    _send_email(student_subject, student_html, config.STUDENT_EMAIL_TO,
                attachments=attachments if attachments else None)
    print(f"SchoolBot report sent to {', '.join(config.STUDENT_EMAIL_TO)}")

    # --- Parent email (ParentBot) ---
    parent_html = _render_html(
        assignments, new_assignments, grades, low, tests, recent, overdue,
        test_prep=test_prep,
        variant="parent",
    )
    parent_subject = f"ParentBot: {subject_parts}"

    _send_email(parent_subject, parent_html, config.PARENT_EMAIL_TO)
    print(f"ParentBot report sent to {', '.join(config.PARENT_EMAIL_TO)}")

    _save_run(data)

    # --- Summary ---
    if tests:
        print(f"  {len(tests)} upcoming test(s)/quiz(zes)")
    if attachments:
        print(f"  {len(attachments)} study guide(s) attached (student email)")
    if overdue:
        print(f"  {len(overdue)} overdue assignment(s)")
    if new_assignments:
        print(f"  {len(new_assignments)} new assignment(s)")
    if low:
        print(f"  {len(low)} grade(s) below {config.GRADE_WARN_THRESHOLD}%")
