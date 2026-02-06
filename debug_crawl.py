"""Debug: crawl one course's materials and print what the crawler sees.

Usage:
    python debug_crawl.py [course_id]
"""

import json
import sys
from playwright.sync_api import sync_playwright

from schoolbot import config, scraper
from schoolbot.downloader import _flatten_tree


def dump_tree(items, indent=0):
    for item in items:
        prefix = "  " * indent
        t = item.get("type", "?")
        name = item.get("name", "?")
        href = item.get("href", "")
        resolved = item.get("resolved_url", "")
        fid = item.get("folder_id", "")
        children = item.get("children", [])

        extra = ""
        if resolved:
            extra += f"  resolved={resolved[:80]}"
        if fid:
            extra += f"  fid={fid}"
        if href and t != "folder":
            extra += f"  href={href[:80]}"

        print(f"{prefix}[{t:12s}] {name[:70]}{extra}")

        if children:
            dump_tree(children, indent + 1)


def main():
    if len(sys.argv) > 1:
        course_id = sys.argv[1]
    else:
        try:
            data = json.load(open(config.LAST_RUN_FILE))
            for g in data.get("grades", []):
                if "science" in g.get("course", "").lower() and g.get("course_id"):
                    course_id = g["course_id"]
                    print(f"Using course: {g['course']} (ID: {course_id})")
                    break
            else:
                print("No Science course found")
                sys.exit(1)
        except FileNotFoundError:
            print("No last_run.json. Pass course_id as argument.")
            sys.exit(1)

    selectors = config.load_selectors()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()

        if config.COOKIES_FILE.exists():
            cookies = json.loads(config.COOKIES_FILE.read_text())
            context.add_cookies(cookies)

        page = context.new_page()
        page.goto(config.SCHOOLOGY_BASE_URL)
        page.wait_for_load_state("networkidle")

        if not scraper._is_logged_in(page):
            scraper._interactive_login(page)
            scraper._save_cookies(context)

        # Manually go 4 levels deep into one path to see actual items
        print("\n=== Manual deep dive: MP1 > Week 1 > Tuesday ===")
        # MP1
        page.goto(f"{config.SCHOOLOGY_BASE_URL}/course/{course_id}/materials?f=941218784")
        page.wait_for_load_state("networkidle")
        # Week 1
        page.goto(f"{config.SCHOOLOGY_BASE_URL}/course/{course_id}/materials?f=941221273")
        page.wait_for_load_state("networkidle")
        # Tuesday
        page.goto(f"{config.SCHOOLOGY_BASE_URL}/course/{course_id}/materials?f=941233939")
        page.wait_for_load_state("networkidle")

        items = scraper._extract_materials_from_page(page, selectors)
        print(f"Found {len(items)} items inside Tuesday:")
        for item in items:
            print(f"  [{item['type']:12s}] {item['name'][:60]}")
            print(f"    href={item.get('href', '')}")
            print(f"    fid={item.get('folder_id', '')}")

        # Also dump raw HTML of item rows to see what we're dealing with
        print("\n=== Raw DOM: first 5 content rows ===")
        raw = page.evaluate("""() => {
            const rows = document.querySelectorAll('tr.dr');
            return Array.from(rows).slice(0, 5).map(tr => ({
                classes: tr.className,
                id: tr.id,
                innerHTML: tr.innerHTML.substring(0, 300),
            }));
        }""")
        for r in raw:
            print(f"  class={r['classes']}  id={r['id']}")
            print(f"  html={r['innerHTML'][:200]}")
            print()

        # Now do full recursive crawl of just MP1 Week 1 (depth 4)
        print("\n=== Recursive crawl: MP1 > Week 1 only (max_depth=4) ===")
        tree = scraper._crawl_materials_recursive(
            page, course_id, "941221273", selectors, max_depth=4
        )
        dump_tree(tree)

        flat = _flatten_tree(tree)
        print(f"\nFlattened: {len(flat)} leaf items")
        type_counts = {}
        for item in flat:
            t = item["type"]
            type_counts[t] = type_counts.get(t, 0) + 1
            print(f"  [{t:12s}] {item['name'][:50]}  folder={item.get('_parent_folder','')[:40]}")
        print(f"\nType counts: {type_counts}")

        browser.close()


if __name__ == "__main__":
    main()
