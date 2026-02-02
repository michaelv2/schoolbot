"""
Phase 0: Discovery spike.

Opens a visible browser to Schoology, pauses for manual login,
saves cookies, then dumps raw HTML from assignments and grades pages.

Usage:
    python spike.py <schoology_domain> [child_id]

Example:
    python spike.py app.schoology.com
    python spike.py mydistrict.schoology.com 123456789
"""

import json
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

OUTPUT_DIR = Path("spike_output")
COOKIES_FILE = Path("cookies.json")


def main():
    if len(sys.argv) < 2:
        print("Usage: python spike.py <schoology_domain> [child_id]")
        print("Example: python spike.py app.schoology.com 123456789")
        sys.exit(1)

    domain = sys.argv[1].strip("/")
    child_id = sys.argv[2] if len(sys.argv) > 2 else None
    base_url = f"https://{domain}"
    OUTPUT_DIR.mkdir(exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()

        # Load saved cookies if they exist
        if COOKIES_FILE.exists():
            cookies = json.loads(COOKIES_FILE.read_text())
            context.add_cookies(cookies)
            print(f"Loaded {len(cookies)} saved cookies.")

        page = context.new_page()
        page.goto(base_url)

        print()
        print("=" * 60)
        print("Browser is open. Log in manually if needed.")
        print("When you're on the logged-in home page, press Enter here.")
        print("=" * 60)
        input()

        # Save cookies for future runs
        cookies = context.cookies()
        COOKIES_FILE.write_text(json.dumps(cookies, indent=2))
        print(f"Saved {len(cookies)} cookies to {COOKIES_FILE}")

        # Dump assignments page
        print(f"\nNavigating to assignments: {base_url}/home/upcoming ...")
        page.goto(f"{base_url}/home/upcoming")
        page.wait_for_load_state("networkidle")
        html = page.content()
        out = OUTPUT_DIR / "assignments.html"
        out.write_text(html)
        print(f"Saved assignments HTML ({len(html)} chars) to {out}")

        # Dump grades page (parent accounts use /parent/grades_attendance/grades)
        if child_id:
            grades_url = f"{base_url}/parent/grades_attendance/grades"
        else:
            grades_url = f"{base_url}/grades/grades"
        print(f"\nNavigating to grades: {grades_url} ...")
        page.goto(grades_url)
        page.wait_for_load_state("networkidle")
        html = page.content()
        out = OUTPUT_DIR / "grades.html"
        out.write_text(html)
        print(f"Saved grades HTML ({len(html)} chars) to {out}")

        # Dump calendar page
        if child_id:
            calendar_url = f"{base_url}/parent/calendar"
        else:
            calendar_url = f"{base_url}/user-calendar"
        print(f"\nNavigating to calendar: {calendar_url} ...")
        page.goto(calendar_url)
        page.wait_for_load_state("networkidle")
        html = page.content()
        out = OUTPUT_DIR / "calendar.html"
        out.write_text(html)
        print(f"Saved calendar HTML ({len(html)} chars) to {out}")

        # Dump materials page for one course (parent preview URL)
        # Use first course ID found on the grades page
        import re
        course_ids = re.findall(r'href="/course/(\d+)/', html)  # from last page loaded
        # Also check grades HTML for course IDs
        grades_html = (OUTPUT_DIR / "grades.html").read_text() if (OUTPUT_DIR / "grades.html").exists() else ""
        course_ids += re.findall(r'href="/course/(\d+)/', grades_html)
        course_ids = list(dict.fromkeys(course_ids))  # dedupe, preserve order

        if course_ids:
            sample_id = course_ids[0]
            if child_id:
                materials_url = f"{base_url}/course/{sample_id}/preview/{child_id}/parent?url=materials"
            else:
                materials_url = f"{base_url}/course/{sample_id}/materials"
            print(f"\nNavigating to materials: {materials_url} ...")
            page.goto(materials_url)
            page.wait_for_load_state("networkidle")
            html = page.content()
            out = OUTPUT_DIR / "materials.html"
            out.write_text(html)
            print(f"Saved materials HTML ({len(html)} chars) to {out}")
            print(f"  Course ID: {sample_id}")
            print(f"  Found {len(course_ids)} course IDs total: {course_ids}")
        else:
            print("\nNo course IDs found — skipping materials dump.")

        print()
        print("=" * 60)
        print("Done! Inspect the HTML files in spike_output/ to find")
        print("the real CSS selectors, then update selectors.yaml.")
        print()
        print("Tip: Keep the browser open and explore other pages.")
        print("Press Enter here to close the browser.")
        print("=" * 60)
        input()

        browser.close()


if __name__ == "__main__":
    main()
