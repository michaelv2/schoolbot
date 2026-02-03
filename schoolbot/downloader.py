"""Download course materials from Schoology into organized local folders.

Handles:
- Schoology-hosted files (PDFs, etc.) via Playwright download
- Google Drive/Docs/Slides links collected in a Links.txt reference file
- Schoology pages/assignments saved as .txt
- External links and tools collected in Links.txt
"""

import re
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from playwright.sync_api import Page

from schoolbot import config, scraper


def _sanitize_name(name: str) -> str:
    """Clean a name for use as a filesystem path component."""
    # Replace path separators and other problematic chars
    name = re.sub(r'[<>:"/\\|?*]', '_', name)
    # Collapse whitespace and underscores
    name = re.sub(r'[\s_]+', '_', name).strip('_. ')
    # Truncate to reasonable length
    return name[:100] if name else "untitled"


def simplify_course_name(raw: str) -> str:
    """Simplify a Schoology course name to a readable folder name.

    Examples:
        "ENGLISH 8: Green 8 ENGLISH 8"              -> "English 8"
        "GR 8 MATH 8 - 2 412: 0458 3 GR 8 MATH 8"  -> "Math 8"
        "EXPLORING MUSIC 8: 0528 270 EXPLORING ..."  -> "Exploring Music 8"
        "SCIENCE 8: Cooper 8 Science YELLOW"          -> "Science 8"
        "GR 8 SPANISH 313: Cooper 8"                  -> "Spanish 313"
        "PHYS.ED.8: 0608 2711 PHYS.ED.8"             -> "Phys Ed 8"
        "KEYSTONE: 99023 43 KEYSTONE"                 -> "Keystone"
        "TECHNOLOGY 8: Q3 Period 8 Cooper"            -> "Technology 8"
        "SOCIAL STUDIES 8: 0758 5 SOCIAL STUDIES 8"   -> "Social Studies 8"
    """
    # Take only the part before the colon (section info comes after)
    name = raw.split(":")[0].strip()

    # Strip "GR 8" prefix (common Schoology pattern for grade 8 courses)
    name = re.sub(r'^GR\s+\d+\s+', '', name, flags=re.IGNORECASE)

    # Strip trailing section numbers / codes (pure digits, or "- digits")
    name = re.sub(r'\s*-\s*[\d\s]+$', '', name)
    name = re.sub(r'\s+\d{4,}$', '', name)  # trailing 4+ digit codes (section numbers)

    # Clean up PHYS.ED.8 -> PHYS ED 8
    name = name.replace('.', ' ')

    # Collapse whitespace
    name = re.sub(r'\s+', ' ', name).strip()

    # Title case
    name = name.title()

    return name if name else _sanitize_name(raw)


def _google_drive_export_url(url: str) -> tuple[str, str]:
    """Convert a Google Drive/Docs/Slides URL to a direct download/export URL.

    Returns (download_url, suggested_extension).
    Returns ("", "") if the URL is not a recognized Google Drive URL.
    """
    parsed = urlparse(url)
    host = parsed.hostname or ""

    # Google Docs: docs.google.com/document/d/{ID}/...
    if "docs.google.com" in host and "/document/d/" in parsed.path:
        m = re.search(r'/document/d/([^/]+)', parsed.path)
        if m:
            doc_id = m.group(1)
            return f"https://docs.google.com/document/d/{doc_id}/export?format=pdf", ".pdf"

    # Google Slides: docs.google.com/presentation/d/{ID}/...
    if "docs.google.com" in host and "/presentation/d/" in parsed.path:
        m = re.search(r'/presentation/d/([^/]+)', parsed.path)
        if m:
            doc_id = m.group(1)
            return f"https://docs.google.com/presentation/d/{doc_id}/export/pdf", ".pdf"

    # Google Sheets: docs.google.com/spreadsheets/d/{ID}/...
    if "docs.google.com" in host and "/spreadsheets/d/" in parsed.path:
        m = re.search(r'/spreadsheets/d/([^/]+)', parsed.path)
        if m:
            doc_id = m.group(1)
            return f"https://docs.google.com/spreadsheets/d/{doc_id}/export?format=pdf", ".pdf"

    # Google Drive file: drive.google.com/file/d/{ID}/...
    if "drive.google.com" in host and "/file/d/" in parsed.path:
        m = re.search(r'/file/d/([^/]+)', parsed.path)
        if m:
            file_id = m.group(1)
            return f"https://drive.google.com/uc?export=download&id={file_id}", ""

    # Google Drive open URL: drive.google.com/open?id={ID}
    if "drive.google.com" in host and "/open" in parsed.path:
        params = parse_qs(parsed.query)
        if "id" in params:
            file_id = params["id"][0]
            return f"https://drive.google.com/uc?export=download&id={file_id}", ""

    return "", ""


def _is_google_url(url: str) -> bool:
    """Check if a URL points to Google Drive/Docs/Slides."""
    if not url:
        return False
    host = (urlparse(url).hostname or "").lower()
    return any(d in host for d in ("docs.google.com", "drive.google.com"))


def _parse_folder_context(folder_name: str) -> tuple[str, str]:
    """Extract week number and topic from a folder name.

    Examples:
        "Week 6 Phases of Matter (1/20-1/22)" -> ("06", "Phases_of_Matter")
        "Week 12 Energy" -> ("12", "Energy")
        "Unit 3 - Expressions" -> ("03", "Expressions")
        "Marking Period 1" -> ("", "Marking_Period_1")

    Returns (week_prefix, topic_name).
    """
    # Try "Week N" pattern
    m = re.match(r'Week\s+(\d+)\s*(.*)', folder_name, re.IGNORECASE)
    if m:
        week_num = m.group(1).zfill(2)
        rest = m.group(2)
        # Strip date ranges like (1/20-1/22)
        rest = re.sub(r'\s*\([^)]*\)\s*', '', rest).strip(' -:')
        topic = _sanitize_name(rest) if rest else ""
        return week_num, topic

    # Try "Unit N" pattern
    m = re.match(r'Unit\s+(\d+)\s*[-:]?\s*(.*)', folder_name, re.IGNORECASE)
    if m:
        unit_num = m.group(1).zfill(2)
        rest = m.group(2).strip()
        topic = _sanitize_name(rest) if rest else ""
        return unit_num, topic

    return "", _sanitize_name(folder_name)


def _build_filename(folder_name: str, item_name: str, extension: str) -> str:
    """Build a prefixed filename: [week]-[topic]-[name].[ext]

    Falls back to just the item name if no week/topic can be extracted.
    """
    week, topic = _parse_folder_context(folder_name)

    name = _sanitize_name(item_name)
    # Remove extension from name if present (we'll add our own)
    name = re.sub(r'\.(pdf|docx?|pptx?|xlsx?|txt)$', '', name, flags=re.IGNORECASE)

    parts = []
    if week:
        parts.append(week)
    if topic:
        parts.append(topic)
    parts.append(name)

    filename = "-".join(parts) + extension
    return filename


def _find_marking_period(folder_name: str, all_top_folders: list[str]) -> str:
    """Determine which marking period folder a given folder belongs to.

    Uses the top-level folder names to identify marking period groupings.
    If no marking period structure exists, returns empty string.
    """
    # Check if the folder itself is a marking period
    mp_pattern = re.compile(
        r'(MP\s*\d+|Marking\s+Period\s+\d+|Quarter\s+\d+|Q[1-4]|Semester\s+\d+)',
        re.IGNORECASE,
    )
    for top in all_top_folders:
        if mp_pattern.search(top):
            return top
    return ""


def _attempt_playwright_download(page: Page, url: str, dest: Path, timeout: int = 30000) -> bool:
    """Download a file by navigating to the URL and catching the browser download.

    Returns True if a file was saved, False otherwise.
    """
    try:
        with page.expect_download(timeout=timeout) as download_info:
            try:
                page.goto(url)
            except Exception:
                pass  # Expected: goto throws "Download is starting" for file URLs
        download = download_info.value
        suggested = download.suggested_filename
        # Use suggested extension if we don't have one
        if not dest.suffix and suggested:
            ext = Path(suggested).suffix
            if ext:
                dest = dest.with_suffix(ext)
        download.save_as(str(dest))
        return True
    except Exception:
        return False


def _attempt_direct_download(page: Page, url: str, dest: Path) -> bool:
    """Download by navigating and saving the response content.

    Used as fallback when expect_download doesn't trigger (e.g. Google Drive
    serves content inline).
    """
    try:
        resp = page.goto(url)
        if not resp:
            return False

        content_type = resp.headers.get("content-type", "")
        # If we got HTML back, this isn't a direct file download
        if "text/html" in content_type and not dest.suffix == ".html":
            return False

        body = resp.body()
        if body and len(body) > 100:  # sanity check
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(body)
            return True
    except Exception:
        pass
    return False


def _extract_attachment_url(page: Page) -> str:
    """Extract a direct /attachment/.../source/... download URL from a Schoology preview page.

    Schoology's /materials/gp/ pages show an HTML preview with the actual
    file available at /attachment/{ID}/source/{HASH}.{ext}.
    """
    return page.evaluate("""() => {
        const links = document.querySelectorAll('a[href]');
        for (const a of links) {
            const href = a.getAttribute('href') || '';
            if (href.includes('/attachment/') && href.includes('/source/')) {
                return href;
            }
        }
        return '';
    }""")


def _download_file(page: Page, url: str, dest: Path) -> bool:
    """Download a file using Playwright, trying multiple strategies."""
    dest.parent.mkdir(parents=True, exist_ok=True)

    # For Schoology preview pages (/materials/gp/, etc.), navigate first
    # to find the real attachment URL, then download that directly.
    # This avoids wasting 30s on a timeout for the preview page.
    try:
        page.goto(url)
        page.wait_for_load_state("networkidle")
    except Exception:
        return False

    resp_content_type = ""
    try:
        resp_content_type = page.evaluate("() => document.contentType || ''") or ""
    except Exception:
        pass

    # If we landed on an HTML page, look for the attachment download link
    if "html" in resp_content_type or "html" in (page.url or ""):
        attachment_href = _extract_attachment_url(page)
        if attachment_href:
            if not attachment_href.startswith("http"):
                attachment_href = config.SCHOOLOGY_BASE_URL + attachment_href
            # Attachment URLs trigger browser downloads, so expect_download first
            if _attempt_playwright_download(page, attachment_href, dest, timeout=15000):
                return True
            if _attempt_direct_download(page, attachment_href, dest):
                return True
            return False

    # Not an HTML preview — try downloading the original URL directly
    if _attempt_direct_download(page, url, dest):
        return True
    if _attempt_playwright_download(page, url, dest, timeout=15000):
        return True

    return False


def _flatten_tree(items: list[dict], parent_folder: str = "") -> list[dict]:
    """Flatten a recursive material tree into a list of leaf items with folder context."""
    flat = []
    for item in items:
        if item["type"] == "folder":
            folder_name = item["name"]
            # Include parent folder path
            full_path = f"{parent_folder}/{folder_name}" if parent_folder else folder_name
            flat.extend(_flatten_tree(item.get("children", []), full_path))
        else:
            item["_parent_folder"] = parent_folder
            flat.append(item)
    return flat


def download_course_materials(
    page: Page,
    course_id: str,
    course_name: str,
    selectors: dict,
    output_dir: Path | None = None,
    limit: int = 0,
) -> dict:
    """Download all materials for a course into organized local folders.

    If limit > 0, stop after processing that many downloadable items.
    Returns {"course", "downloaded", "skipped", "failed"}.
    """
    output_dir = output_dir or config.MATERIALS_DIR
    friendly_name = simplify_course_name(course_name)
    course_dir = output_dir / _sanitize_name(friendly_name)
    course_dir.mkdir(parents=True, exist_ok=True)

    stats = {"course": friendly_name, "downloaded": 0, "skipped": 0, "failed": []}

    print(f"\n  Crawling materials for {friendly_name} (course {course_id})...")

    # Get recursive material tree (limited if limit is set)
    tree = scraper._crawl_materials_recursive(
        page, course_id, "", selectors, max_leaves=limit,
    )

    # Identify top-level folder names (for marking period detection)
    top_folders = [i["name"] for i in tree if i["type"] == "folder"]

    # Determine if there's a marking period structure
    mp_pattern = re.compile(
        r'(MP\s*\d+|Marking\s+Period\s+\d+|Quarter\s+\d+|Q[1-4]|Semester\s+\d+)',
        re.IGNORECASE,
    )
    marking_period_folders = [f for f in top_folders if mp_pattern.search(f)]

    # Flatten the tree for downloading
    flat_items = _flatten_tree(tree)

    if not flat_items:
        print(f"  No downloadable items found for {course_name}")
        return stats

    print(f"  Found {len(flat_items)} items across {len(top_folders)} folders")

    # Collect links that can't be downloaded directly, grouped by output dir
    # {dir_path: [(name, url, folder_context), ...]}
    collected_links: dict[Path, list[tuple[str, str, str]]] = {}

    items_processed = 0
    for item in flat_items:
        if limit and items_processed >= limit:
            print(f"  Reached limit of {limit} items, stopping.")
            break
        items_processed += 1

        name = item["name"]
        item_type = item["type"]
        href = item.get("href", "")
        resolved_url = item.get("resolved_url", "")
        parent_folder = item.get("_parent_folder", "")

        # Determine the best URL to use
        url = resolved_url or href
        if url and not url.startswith("http"):
            url = config.SCHOOLOGY_BASE_URL + url

        # Determine subdirectory based on marking period structure
        if marking_period_folders:
            # Find which marking period this item's folder belongs to
            mp_folder = ""
            for mp in marking_period_folders:
                if parent_folder.startswith(mp):
                    mp_folder = _sanitize_name(mp)
                    # Remove the MP prefix from parent_folder for the item context
                    parent_folder = parent_folder[len(mp):].strip("/")
                    break
            if mp_folder:
                item_dir = course_dir / mp_folder
            else:
                item_dir = course_dir
        else:
            item_dir = course_dir

        item_dir.mkdir(parents=True, exist_ok=True)

        # Determine immediate parent folder name for filename prefix
        folder_for_prefix = parent_folder.split("/")[-1] if parent_folder else ""

        # Determine effective URL for this item
        effective_url = url  # already resolved and absolute

        # Handle based on type / URL
        if _is_google_url(effective_url) or _is_google_url(resolved_url):
            # Google Drive/Docs/Slides — collect as link (can't auth with Google)
            link_url = resolved_url or effective_url
            folder_ctx = parent_folder or ""
            collected_links.setdefault(item_dir, []).append((name, link_url, folder_ctx))

        elif item_type in ("file", "document"):
            # Schoology-hosted file or document (/file/ID, /materials/gp/ID, etc.)
            file_url = effective_url or (
                href if href.startswith("http") else config.SCHOOLOGY_BASE_URL + href
            )
            if not file_url:
                stats["skipped"] += 1
                continue
            # Skip external tool launches (LTI) — can't download these
            if "/external_tool/" in file_url:
                folder_ctx = parent_folder or ""
                collected_links.setdefault(item_dir, []).append((name, file_url, folder_ctx))
                continue
            # Try to determine extension from the URL or item name
            name_ext = Path(name).suffix.lower() if "." in name else ""
            url_ext = Path(urlparse(file_url).path).suffix.lower()
            ext = name_ext or url_ext or ".pdf"
            filename = _build_filename(folder_for_prefix, name, ext)
            dest = item_dir / filename

            if dest.exists():
                stats["skipped"] += 1
                continue

            print(f"    Downloading (Schoology file): {filename}")
            if _download_file(page, file_url, dest):
                stats["downloaded"] += 1
            else:
                print(f"    FAILED: {filename}")
                stats["failed"].append(name)

        elif item_type in ("page", "assignment"):
            # Schoology page/assignment — extract text and save as .txt
            page_url = effective_url or (
                href if href.startswith("http") else config.SCHOOLOGY_BASE_URL + href
            )
            if not page_url:
                stats["skipped"] += 1
                continue
            filename = _build_filename(folder_for_prefix, name, ".txt")
            dest = item_dir / filename

            if dest.exists():
                stats["skipped"] += 1
                continue

            text = scraper._extract_page_text(page, page_url, selectors)
            if text:
                print(f"    Saving text: {filename}")
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(text, encoding="utf-8")
                stats["downloaded"] += 1
            else:
                # Don't count empty pages as failures — they just have no content
                stats["skipped"] += 1

        elif item_type == "link":
            # External link or unresolved link — collect for Links.txt
            link_url = resolved_url or href
            if link_url and not link_url.startswith("http"):
                link_url = config.SCHOOLOGY_BASE_URL + link_url
            if link_url:
                folder_ctx = parent_folder or ""
                collected_links.setdefault(item_dir, []).append((name, link_url, folder_ctx))
            else:
                stats["skipped"] += 1

        else:
            # Unknown type or no URL — skip silently
            stats["skipped"] += 1

    # Write one links file per output directory (marking period or course root)
    for link_dir, links in collected_links.items():
        links_file = link_dir / "Links.html"
        # Append to existing file (idempotent across runs by checking content)
        existing = links_file.read_text(encoding="utf-8") if links_file.exists() else ""
        new_entries = []
        for link_name, link_url, folder_ctx in links:
            # Skip if this link is already in the file
            if link_url in existing:
                continue
            label = f"[{folder_ctx}] {link_name}" if folder_ctx else link_name
            new_entries.append(
                f'<li><a href="{link_url}">{label}</a></li>\n'
            )
        if new_entries:
            with open(links_file, "a", encoding="utf-8") as f:
                if not existing:
                    f.write(
                        f"<!DOCTYPE html>\n<html><head>"
                        f"<meta charset='utf-8'>"
                        f"<title>{friendly_name} — Links</title>"
                        f"<style>"
                        f"body{{font-family:sans-serif;max-width:900px;margin:40px auto;padding:0 20px}}"
                        f"li{{margin:8px 0}}"
                        f"a{{color:#2980b9}}"
                        f"</style></head><body>\n"
                        f"<h1>{friendly_name} — Links</h1>\n<ul>\n"
                    )
                f.write("".join(new_entries))
            print(f"    Collected {len(new_entries)} link(s) in {links_file.relative_to(output_dir)}")

    # Save cookies after downloading
    scraper._save_cookies(page.context)

    return stats
