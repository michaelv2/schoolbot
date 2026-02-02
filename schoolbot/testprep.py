"""Test prep generation using Claude API.

Produces two outputs per upcoming test:
1. Topic summary (~100-200 words) for the email body
2. Study guide (~500-1500 words) as an HTML email attachment
"""

from datetime import datetime, timedelta

import anthropic

from schoolbot import config

# Truncate materials text to stay within reasonable token limits
MAX_MATERIALS_CHARS = 30_000


def _get_client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)


def _truncate(text: str, max_chars: int = MAX_MATERIALS_CHARS) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n\n[...materials truncated...]"


def _today() -> str:
    return datetime.now().strftime("%B %d, %Y")


def generate_topic_summary(
    materials_text: str,
    course_name: str,
    test_title: str,
    test_date: str,
) -> str:
    """Generate a short topic summary for an upcoming test.

    Returns a plain-text bullet-point summary of key topics (~100-200 words).
    Returns empty string on failure.
    """
    if not materials_text.strip():
        return ""

    client = _get_client()
    prompt = (
        f"You are helping a student and their parent prepare for an upcoming test.\n\n"
        f"Today's date: {_today()}\n"
        f"Course: {course_name}\n"
        f"Test: {test_title}\n"
        f"Test date: {test_date} (this is an upcoming future date)\n\n"
        f"Below are the course materials from recent weeks. "
        f"Summarize the key topics and concepts that will likely be covered on this test. "
        f"Use bullet points. Be concise (100-200 words). "
        f"Focus on what to study, not general advice. "
        f"Do NOT use markdown formatting — output plain text only.\n\n"
        f"--- COURSE MATERIALS ---\n{_truncate(materials_text)}"
    )

    try:
        response = client.messages.create(
            model=config.ANTHROPIC_MODEL,
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()
    except Exception as e:
        print(f"  Warning: topic summary generation failed: {e}")
        return ""


def generate_study_guide(
    materials_text: str,
    course_name: str,
    test_title: str,
    test_date: str,
) -> str:
    """Generate a study guide for an upcoming test.

    Returns an HTML document with key concepts, terms, and practice questions.
    Returns empty string on failure.
    """
    if not materials_text.strip():
        return ""

    client = _get_client()
    prompt = (
        f"You are helping a student prepare for an upcoming test. "
        f"Generate a study guide based on the course materials below.\n\n"
        f"Today's date: {_today()}\n"
        f"Course: {course_name}\n"
        f"Test: {test_title}\n"
        f"Test date: {test_date} (this is an upcoming future date)\n\n"
        f"The study guide should include:\n"
        f"1. Key Concepts — brief explanations of the main topics\n"
        f"2. Important Terms & Definitions — vocabulary to know\n"
        f"3. Practice Questions — 5-10 questions with answers\n\n"
        f"Format the output as clean HTML (no <html>/<head>/<body> wrapper needed, "
        f"just the content with headings, lists, and paragraphs). "
        f"Use clear headings and organized structure.\n\n"
        f"--- COURSE MATERIALS ---\n{_truncate(materials_text)}"
    )

    try:
        response = client.messages.create(
            model=config.ANTHROPIC_MODEL,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        content = response.content[0].text.strip()
        return _wrap_study_guide_html(content, course_name, test_title, test_date)
    except Exception as e:
        print(f"  Warning: study guide generation failed: {e}")
        return ""


def generate_student_feedback(
    grades: list[dict],
    recent_items: list[dict],
    upcoming_tests: list[dict],
    overdue: list[dict],
    calendar_events: list[dict],
    feedback_history: dict | None = None,
    persistent_issues: dict | None = None,
) -> str:
    """Generate a short motivational message for the student.

    Returns HTML (1-3 sentences + a joke). Returns empty string on failure.
    """
    if feedback_history is None:
        feedback_history = {"feedback_history": [], "persistent_issues": {}}
    if persistent_issues is None:
        persistent_issues = {}
    client = _get_client()

    now = datetime.now()
    day_of_week = now.strftime("%A")
    is_friday = now.weekday() == 4

    # Build a concise snapshot of the student's situation
    grade_lines = []
    for g in grades:
        display = g.get("grade_display") or ""
        letter = g.get("letter") or ""
        course = g.get("course", "")
        if display:
            grade_lines.append(f"  {course}: {display} {letter}".strip())
    grade_summary = "\n".join(grade_lines) if grade_lines else "  (no overall grades available)"

    recent_lines = []
    for r in recent_items[:8]:
        recent_lines.append(f"  {r['course']}: {r['title']} — {r['score']} ({r['pct']})")
    recent_summary = "\n".join(recent_lines) if recent_lines else "  (none)"

    # Build test summary with day of week for clarity
    test_lines = []
    for t in upcoming_tests:
        due_date_str = t.get('due_date', '')
        course = t.get('course', '')

        # Try to parse the date and add day of week
        if due_date_str:
            try:
                # Handle format like "2/03/26" or "2/3/26"
                parts = due_date_str.split()[0].split('/')  # Get date part before any time
                if len(parts) == 3:
                    month, day, year = parts
                    year_full = f"20{year}" if len(year) == 2 else year
                    test_dt = datetime(int(year_full), int(month), int(day))
                    day_of_week = test_dt.strftime('%A')
                    due_date_str = f"{day_of_week} {due_date_str}"
            except (ValueError, IndexError):
                pass  # Keep original format if parsing fails

        test_lines.append(f"  {t['title']} ({course}) — {due_date_str}")
    test_summary = "\n".join(test_lines) if test_lines else "  (none)"

    overdue_count = len(overdue)

    event_lines = []
    for ev in calendar_events[:10]:
        event_lines.append(f"  {ev.get('title', '')}")
    events_summary = "\n".join(event_lines) if event_lines else "  (none)"

    # Build recent feedback history (last 7 days)
    # Show encouragement and joke separately so Claude can avoid reusing either
    seven_days_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    recent_feedback = [
        entry for entry in feedback_history.get("feedback_history", [])
        if entry.get("date", "") >= seven_days_ago
    ]
    history_lines = []
    for entry in recent_feedback[-7:]:  # Last 7 entries max
        date = entry.get("date", "")
        components = entry.get("components", {})
        encouragement = components.get("encouragement", "")
        joke = components.get("joke", "")
        if not date:
            continue
        if encouragement or joke:
            history_lines.append(f"  {date} encouragement: {encouragement}")
            if joke:
                history_lines.append(f"  {date} joke: {joke}")
    history_summary = "\n".join(history_lines) if history_lines else "  (no recent feedback)"

    # Build persistent issues list
    issue_lines = []
    for key, issue in persistent_issues.items():
        days = issue.get("consecutive_days", 0)
        if days >= 3:
            issue_name = key.replace("_", " ").replace("low grade ", "low grade in ")
            issue_lines.append(f"  {issue_name}: {days} consecutive days")
    issues_summary = "\n".join(issue_lines) if issue_lines else "  (none)"

    prompt = (
        f"You are SchoolBot, writing a brief motivational message to an 8th-grade student "
        f"at the top of their daily school report email. The parent also reads this.\n\n"
        f"Today: {day_of_week}, {_today()}\n\n"
        f"CURRENT GRADES:\n{grade_summary}\n\n"
        f"RECENTLY GRADED ITEMS (past 2 weeks):\n{recent_summary}\n\n"
        f"UPCOMING TESTS:\n{test_summary}\n\n"
        f"OVERDUE ASSIGNMENTS: {overdue_count}\n\n"
        f"UPCOMING CALENDAR EVENTS:\n{events_summary}\n\n"
        f"RECENT FEEDBACK HISTORY (avoid repetition):\n{history_summary}\n\n"
        f"PERSISTENT ISSUES (you may emphasize these even if mentioned before):\n{issues_summary}\n\n"
        f"INSTRUCTIONS:\n"
        f"Write 1-2 sentences of personalized encouragement based on the data above. "
        f"Target habits or behaviors that are common challenges for a student with ADHD. "
        f"Be specific — reference actual courses, scores, or events. "
        f"If there are overdue assignments, gently mention it. "
        f"If there's an upcoming test, mention preparing for it. "
        f"Keep the tone warm, upbeat, and parent-appropriate. "
        f"{'It is Friday — work in a TGIF vibe! ' if is_friday else ''}"
        f"Then add a short, clean, funny joke on its own line (appropriate for a 13-year-old). "
        f"\n\n"
        f"IMPORTANT: Review the recent feedback history above and vary your messaging and jokes "
        f"to avoid repetition. However, if there are persistent issues listed, you may repeat "
        f"concerns about those specific problems.\n\n"
        f"Do NOT use markdown. Output plain text only."
    )

    try:
        response = client.messages.create(
            model=config.ANTHROPIC_MODEL,
            max_tokens=250,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()
    except Exception as e:
        print(f"  Warning: student feedback generation failed: {e}")
        return ""


def _wrap_study_guide_html(
    body: str, course_name: str, test_title: str, test_date: str
) -> str:
    """Wrap generated content in a standalone HTML document."""
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Study Guide — {test_title}</title>
<style>
    body {{
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        max-width: 800px;
        margin: 40px auto;
        padding: 0 20px;
        line-height: 1.6;
        color: #333;
    }}
    h1 {{ color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 8px; }}
    h2 {{ color: #2980b9; margin-top: 24px; }}
    h3 {{ color: #34495e; }}
    .meta {{ color: #666; font-size: 14px; margin-bottom: 24px; }}
    ul, ol {{ margin: 8px 0; }}
    li {{ margin: 4px 0; }}
    .answer {{ color: #27ae60; font-style: italic; }}
    strong {{ color: #2c3e50; }}
</style>
</head>
<body>
<h1>Study Guide: {test_title}</h1>
<p class="meta">{course_name} &mdash; {test_date}<br>Generated by SchoolBot</p>
{body}
</body>
</html>"""
