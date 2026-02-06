"""Debug: try downloading one file to see what Schoology serves."""

import json
from playwright.sync_api import sync_playwright
from schoolbot import config, scraper

COURSE_ID = "8000539026"
# Safety Packet.pdf from the debug crawl — a /materials/gp/ URL
TEST_HREF = "/course/8000539026/materials/gp/8009891310"

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

    url = config.SCHOOLOGY_BASE_URL + TEST_HREF
    print(f"\n=== Navigating to: {url} ===")
    resp = page.goto(url)
    page.wait_for_load_state("networkidle")

    print(f"Final URL: {page.url}")
    print(f"Response status: {resp.status if resp else 'None'}")
    print(f"Content-Type: {resp.headers.get('content-type', '?') if resp else '?'}")

    # Check if it's a preview page with a download link
    info = page.evaluate("""() => {
        const body = document.body ? document.body.innerText.substring(0, 500) : '';
        // Look for download links
        const links = Array.from(document.querySelectorAll('a[href]'));
        const downloadLinks = links.filter(a => {
            const h = a.getAttribute('href') || '';
            const t = a.textContent || '';
            return h.includes('download') || h.includes('/attachment/') ||
                   t.toLowerCase().includes('download') || h.includes('.pdf');
        }).map(a => ({
            text: a.textContent.trim().substring(0, 50),
            href: a.getAttribute('href'),
        }));
        // Look for attachment/file links
        const attachLinks = links.filter(a => {
            const h = a.getAttribute('href') || '';
            return h.includes('/attachment/') || h.includes('/file/');
        }).map(a => ({
            text: a.textContent.trim().substring(0, 50),
            href: a.getAttribute('href'),
        }));
        return {
            body: body,
            downloadLinks: downloadLinks.slice(0, 5),
            attachLinks: attachLinks.slice(0, 5),
            allLinkCount: links.length,
            title: document.title,
        };
    }""")

    print(f"\nPage title: {info['title']}")
    print(f"Total links on page: {info['allLinkCount']}")
    print(f"\nDownload-related links:")
    for l in info['downloadLinks']:
        print(f"  [{l['text']}] -> {l['href']}")
    print(f"\nAttachment links:")
    for l in info['attachLinks']:
        print(f"  [{l['text']}] -> {l['href']}")
    print(f"\nPage text (first 300 chars):")
    print(info['body'][:300])

    # Also try: does the page have an iframe with the PDF?
    iframe_info = page.evaluate("""() => {
        const iframes = document.querySelectorAll('iframe');
        return Array.from(iframes).map(f => ({
            src: f.getAttribute('src') || '',
            id: f.id,
            className: f.className,
        }));
    }""")
    if iframe_info:
        print(f"\nIframes found:")
        for f in iframe_info:
            print(f"  src={f['src'][:100]}  id={f['id']}  class={f['className']}")

    input("\nPress Enter to close browser...")
    browser.close()
