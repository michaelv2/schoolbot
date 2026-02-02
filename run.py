"""
SchoolBot entry point.

Usage:
    python run.py              # Headless scrape + email report
    python run.py --headed     # Visible browser (for debugging)
    python run.py --scrape-only  # Scrape and print data, no email
"""

import argparse
import json

from schoolbot import scraper, report


def main():
    parser = argparse.ArgumentParser(description="SchoolBot: Schoology scraper + email reporter")
    parser.add_argument("--headed", action="store_true", help="Launch visible browser")
    parser.add_argument("--scrape-only", action="store_true", help="Scrape and print, don't send email")
    args = parser.parse_args()

    print("Scraping Schoology...")
    data = scraper.scrape(headed=args.headed)
    print(f"  Found {len(data['assignments'])} assignments, {len(data['grades'])} grades")

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
