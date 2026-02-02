"""Dump materials page HTML for specific courses to inspect the DOM.

Uses existing cookies — no manual login needed.

Usage:
    python dump_materials.py <course_id:label> [course_id:label ...]

Example:
    python dump_materials.py 1234567890:science 9876543210:math
"""

import json
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

from schoolbot import config

OUTPUT_DIR = Path("spike_output")


def main():
    if len(sys.argv) < 2:
        print("Usage: python dump_materials.py <course_id:label> [course_id:label ...]")
        print("Example: python dump_materials.py 1234567890:science 9876543210:math")
        sys.exit(1)

    courses = {}
    for arg in sys.argv[1:]:
        if ":" in arg:
            cid, label = arg.split(":", 1)
            courses[cid] = label
        else:
            courses[arg] = arg

    OUTPUT_DIR.mkdir(exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()

        if config.COOKIES_FILE.exists():
            cookies = json.loads(config.COOKIES_FILE.read_text())
            context.add_cookies(cookies)
            print(f"Loaded {len(cookies)} cookies")

        page = context.new_page()

        for course_id, label in courses.items():
            child = config.SCHOOLOGY_CHILD_ID
            # Try multiple URL patterns to see which one works
            urls = [
                ("direct", f"{config.SCHOOLOGY_BASE_URL}/course/{course_id}/materials"),
                ("parent-preview", f"{config.SCHOOLOGY_BASE_URL}/course/{course_id}/preview/{child}/parent?url=materials"),
                ("parent-materials", f"{config.SCHOOLOGY_BASE_URL}/course/{course_id}/materials?preview_as_student={child}"),
            ]

            for url_label, url in urls:
                print(f"\n[{label}] Trying {url_label}: {url}")
                page.goto(url)
                page.wait_for_load_state("networkidle")

                final_url = page.url
                title = page.title()
                text_preview = page.evaluate("() => document.body ? document.body.innerText.substring(0, 300) : ''")
                is_error = "not found" in text_preview.lower() or "oops" in text_preview.lower()

                print(f"  Final URL: {final_url}")
                print(f"  Error page: {is_error}")

                if not is_error:
                    html = page.content()
                    out = OUTPUT_DIR / f"materials_{label}.html"
                    out.write_text(html)
                    print(f"  SUCCESS — saved {len(html)} chars to {out}")

                    summary = page.evaluate("""() => {
                        const body = document.body;
                        return {
                            links: document.querySelectorAll('a').length,
                            divs: document.querySelectorAll('div').length,
                            folders: document.querySelectorAll('[class*="folder"]').length,
                            materials: document.querySelectorAll('[class*="material"]').length,
                        };
                    }""")
                    print(f"  Links: {summary['links']}, Folders: {summary['folders']}, Materials: {summary['materials']}")
                    print(f"  Text: {text_preview[:200]}")
                    break
                else:
                    print(f"  FAILED — {text_preview[:100]}")

        browser.close()
    print("\nDone. Inspect the HTML files in spike_output/")


if __name__ == "__main__":
    main()
