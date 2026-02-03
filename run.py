"""
SchoolBot entry point.

Usage:
    python run.py                       # Headless scrape + email report
    python run.py --headed              # Visible browser (for debugging)
    python run.py --scrape-only         # Scrape and print data, no email
    python run.py --download-materials  # Download course materials to data/materials/
    python run.py --download-materials --course science  # Download one course only
    python run.py --download-materials --course science --limit 20  # First 20 items only
"""

import argparse
import json

from schoolbot import scraper, report, config


def _download_materials(data: dict, headed: bool, course_filter: str = "", limit: int = 0) -> None:
    """Download course materials for all courses found in grades."""
    from playwright.sync_api import sync_playwright
    from schoolbot import downloader

    grades = data.get("grades", [])
    courses = [(g["course_id"], g["course"]) for g in grades if g.get("course_id")]

    if course_filter:
        filt = course_filter.lower()
        courses = [(cid, name) for cid, name in courses if filt in name.lower()]
        if not courses:
            print(f"No courses matching '{course_filter}' found. Available courses:")
            for g in grades:
                if g.get("course_id"):
                    friendly = downloader.simplify_course_name(g["course"])
                    print(f"  - {friendly}  ({g['course']})")
            return

    if not courses:
        print("No courses found in grades data — nothing to download.")
        return

    friendly_list = [downloader.simplify_course_name(n) for _, n in courses]
    print(f"\nDownloading materials for {len(courses)} course(s): {', '.join(friendly_list)}")
    print(f"Output directory: {config.MATERIALS_DIR}")
    config.MATERIALS_DIR.mkdir(parents=True, exist_ok=True)

    selectors = config.load_selectors()

    # Re-use the existing browser session or start a new one
    page = data.get("_browser_page")
    browser = data.get("_browser")
    pw = data.get("_playwright")

    if page is None:
        # No browser session from scrape — start our own
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=not headed)
        context = browser.new_context()

        if config.COOKIES_FILE.exists():
            cookies = json.loads(config.COOKIES_FILE.read_text())
            context.add_cookies(cookies)

        page = context.new_page()
        page.goto(config.SCHOOLOGY_BASE_URL)
        page.wait_for_load_state("networkidle")

        if not scraper._is_logged_in(page):
            browser.close()
            browser = pw.chromium.launch(headless=False)
            context = browser.new_context()
            page = context.new_page()
            page.goto(config.SCHOOLOGY_BASE_URL)
            page.wait_for_load_state("networkidle")
            scraper._interactive_login(page)

        scraper._save_cookies(context)

    total_downloaded = 0
    total_skipped = 0
    all_failures = []

    for course_id, course_name in courses:
        stats = downloader.download_course_materials(
            page, course_id, course_name, selectors, limit=limit,
        )

        total_downloaded += stats["downloaded"]
        total_skipped += stats["skipped"]
        all_failures.extend(stats["failed"])

        print(f"  {stats['course']}: {stats['downloaded']} downloaded, "
              f"{stats['skipped']} skipped, {len(stats['failed'])} failed")

    print(f"\nDownload complete: {total_downloaded} files downloaded, "
          f"{total_skipped} skipped, {len(all_failures)} failed")
    if all_failures:
        print("Failed items:")
        for f in all_failures:
            print(f"  - {f}")


def main():
    parser = argparse.ArgumentParser(description="SchoolBot: Schoology scraper + email reporter")
    parser.add_argument("--headed", action="store_true", help="Launch visible browser")
    parser.add_argument("--scrape-only", action="store_true", help="Scrape and print, don't send email")
    parser.add_argument("--download-materials", action="store_true",
                        help="Download course materials to data/materials/")
    parser.add_argument("--course", type=str, default="",
                        help="Filter to a specific course (substring match, e.g. 'science')")
    parser.add_argument("--limit", type=int, default=0,
                        help="Max number of items to process per course (0 = unlimited)")
    args = parser.parse_args()

    print("Scraping Schoology...")
    # Force browser to stay open if we need it for downloads
    original_test_prep = config.ENABLE_TEST_PREP
    if args.download_materials:
        config.ENABLE_TEST_PREP = True

    data = scraper.scrape(headed=args.headed)
    print(f"  Found {len(data['assignments'])} assignments, {len(data['grades'])} grades")

    if args.download_materials:
        config.ENABLE_TEST_PREP = original_test_prep
        try:
            _download_materials(data, headed=args.headed, course_filter=args.course, limit=args.limit)
        finally:
            scraper.close_browser(data)
        return

    if args.scrape_only:
        # Remove internal browser references before printing
        printable = {k: v for k, v in data.items() if not k.startswith("_")}
        print(json.dumps(printable, indent=2))
        scraper.close_browser(data)
        return

    try:
        browser_page = data.get("_browser_page")
        report.generate_and_send(data, browser_page=browser_page)
    finally:
        scraper.close_browser(data)


if __name__ == "__main__":
    main()
