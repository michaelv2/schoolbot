import json
import re
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright, BrowserContext, Page

from schoolbot import config

# How long to wait for AJAX-loaded content before giving up (ms)
AJAX_TIMEOUT = 10_000


def _save_cookies(context: BrowserContext) -> None:
    cookies = context.cookies()
    config.COOKIES_FILE.write_text(json.dumps(cookies, indent=2))


def _interactive_login(page: Page) -> None:
    """Pause for manual login when cookies are missing or expired."""
    print()
    print("=" * 60)
    print("Automated login failed or no cookies found.")
    print("A browser window should be open — log in manually.")
    print("Press Enter here once you are logged in.")
    print("=" * 60)
    input()


def _is_logged_in(page: Page) -> bool:
    """Heuristic: check if we landed on a login/SSO page."""
    url = page.url.lower()
    return "login" not in url and "signin" not in url and "sso" not in url


def _wait_for_ajax(page: Page, selector: str) -> None:
    """Wait for AJAX-loaded elements to appear, or timeout silently."""
    try:
        page.wait_for_selector(selector, timeout=AJAX_TIMEOUT)
    except Exception:
        pass  # Elements may legitimately not exist (e.g. no assignments)


def _extract_assignments(page: Page, selectors: dict) -> list[dict]:
    sel = selectors["assignments"]
    _wait_for_ajax(page, sel["item"])

    items = page.query_selector_all(sel["item"])
    assignments = []
    for item in items:
        title_el = item.query_selector(sel["title"])
        course_el = item.query_selector(sel["course"])
        due_el = item.query_selector(sel["due_date"])
        assignments.append({
            "title": title_el.text_content().strip() if title_el else "",
            "course": course_el.text_content().strip() if course_el else "",
            "due_date": due_el.text_content().strip() if due_el else "",
        })
    return assignments


def _extract_grades(page: Page, selectors: dict) -> list[dict]:
    sel = selectors["grades"]
    _wait_for_ajax(page, sel["course_item"])

    # Run extraction in-browser to avoid cross-document element handle errors
    return page.evaluate("""(sel) => {
        // Get visible text, excluding visually-hidden spans
        function visibleText(el) {
            if (!el) return "";
            const clone = el.cloneNode(true);
            clone.querySelectorAll(".visually-hidden").forEach(h => h.remove());
            return clone.textContent.trim();
        }

        const courses = document.querySelectorAll(sel.course_item);
        return Array.from(courses).map(course => {
            const nameEl = course.querySelector(sel.course_name);

            // Extract course ID from any assignment link: /course/{ID}/...
            let courseId = "";
            const anyLink = course.querySelector('a[href*="/course/"]');
            if (anyLink) {
                const courseMatch = anyLink.getAttribute("href").match(/\\/course\\/(\\d+)\\//);
                if (courseMatch) courseId = courseMatch[1];
            }
            const courseRow = course.querySelector(sel.course_row);

            let letter = "";
            let gradeDisplay = "";
            let gradeNum = null;
            if (courseRow) {
                const letterEl = courseRow.querySelector(sel.letter_grade);
                const pctEl = courseRow.querySelector(sel.grade_percent);
                letter = letterEl ? letterEl.textContent.trim() : "";
                if (pctEl) {
                    gradeDisplay = pctEl.textContent.trim();
                    const parsed = parseFloat(gradeDisplay.replace("%", ""));
                    if (!isNaN(parsed)) gradeNum = parsed;
                }
            }

            // Build period, category, and weight lookups from data-id / data-parent-id
            const periodMap = {};      // data-id -> period name
            const categoryToPeriod = {};  // category data-id -> period data-id
            const categoryInfo = {};   // category data-id -> {name, weight}

            course.querySelectorAll(sel.period_row).forEach(row => {
                const id = row.getAttribute("data-id");
                const titleEl = row.querySelector(".title");
                periodMap[id] = visibleText(titleEl);
            });
            course.querySelectorAll(sel.category_row).forEach(row => {
                const id = row.getAttribute("data-id");
                const parentId = row.getAttribute("data-parent-id");
                categoryToPeriod[id] = parentId;

                const titleEl = row.querySelector(".title");
                const weightEl = row.querySelector(".percentage-contrib");
                const name = visibleText(titleEl);
                let weight = null;
                if (weightEl) {
                    const m = weightEl.textContent.match(/(\\d+)%/);
                    if (m) weight = parseFloat(m[1]);
                }
                categoryInfo[id] = { name, weight };
            });

            const items = Array.from(course.querySelectorAll(sel.item_row)).map(item => {
                const titleEl = item.querySelector(sel.item_title);
                const awardedEl = item.querySelector(sel.item_awarded);
                const maxEl = item.querySelector(sel.item_max);
                const dueEl = item.querySelector(sel.item_due_date);

                // Trace item -> category -> period
                const parentId = item.getAttribute("data-parent-id") || "";
                const periodId = categoryToPeriod[parentId] || parentId;
                const period = periodMap[periodId] || "";
                const cat = categoryInfo[parentId] || {};

                return {
                    title: titleEl ? titleEl.textContent.trim() : "",
                    awarded: awardedEl ? (awardedEl.getAttribute("title") || awardedEl.textContent.trim()) : "",
                    max: maxEl ? maxEl.textContent.trim().replace(/^\\/\\s*/, "") : "",
                    due_date: visibleText(dueEl),
                    period: period,
                    category: cat.name || "",
                    category_weight: cat.weight,
                };
            });

            return {
                course: visibleText(nameEl),
                course_id: courseId,
                grade: gradeNum,
                grade_display: gradeDisplay,
                letter: letter,
                items: items,
            };
        });
    }""", sel)


def _extract_calendar_events(page: Page) -> list[dict]:
    """Extract events from FullCalendar's JS API on the calendar page."""
    _wait_for_ajax(page, ".fc")
    return page.evaluate("""() => {
        if (!window.jQuery) return [];
        const $cal = jQuery(".fc");
        if (!$cal.length) return [];
        try {
            const events = $cal.fullCalendar("clientEvents");
            return events.map(e => {
                // Strip HTML from title (assignment events have <a> tags)
                let title = e.title || "";
                const tmp = document.createElement("div");
                tmp.innerHTML = title;
                title = (tmp.textContent || tmp.innerText || title).trim();

                let start = null;
                if (e.start) {
                    if (e.start.toISOString) start = e.start.toISOString();
                    else if (e.start.format) start = e.start.format();
                    else start = String(e.start);
                }

                return {
                    title: title,
                    start: start,
                    all_day: e.allDay || false,
                    type: (e.className || []).includes("assignment-icon") ? "assignment" : "event",
                };
            });
        } catch(err) {
            return [];
        }
    }""")


def _materials_url(course_id: str) -> str:
    """Build the materials URL for a course.

    The direct /course/{ID}/materials URL works for both student and parent
    accounts. The parent preview URL (?url=materials) returns 404.
    """
    return f"{config.SCHOOLOGY_BASE_URL}/course/{course_id}/materials"


def _folder_url(course_id: str, folder_id: str) -> str:
    """Build the URL for a specific folder within a course's materials."""
    return f"{config.SCHOOLOGY_BASE_URL}/course/{course_id}/materials?f={folder_id}"


def _parse_folder_dates(folder_name: str) -> tuple[datetime | None, datetime | None]:
    """Try to extract a date range from folder names like 'Week 8 (1/20-1/22)'.

    Returns (start_date, end_date) or (None, None) if no dates found.
    """
    # Match patterns like (1/20-1/22), (1/20 - 1/22), (01/20-01/22)
    m = re.search(r'\((\d{1,2}/\d{1,2})\s*-\s*(\d{1,2}/\d{1,2})\)', folder_name)
    if not m:
        return None, None
    now = datetime.now()
    year = now.year
    try:
        start = datetime.strptime(f"{m.group(1)}/{year}", "%m/%d/%Y")
        end = datetime.strptime(f"{m.group(2)}/{year}", "%m/%d/%Y")
        # If end is before start, the range likely spans a year boundary
        if end < start:
            end = end.replace(year=year + 1)
        return start, end
    except ValueError:
        return None, None


def _is_folder_relevant(folder_name: str, test_date: datetime, weeks_before: int = 3) -> bool:
    """Check if a folder's date range falls within the study window for a test."""
    start, end = _parse_folder_dates(folder_name)
    if start is None:
        return False
    window_start = test_date - timedelta(weeks=weeks_before)
    # Folder overlaps the study window if it ends after window_start and starts before test_date
    return end >= window_start and start <= test_date


def _extract_materials_from_page(page: Page, selectors: dict) -> list[dict]:
    """Extract folder listing and content items from a materials page.

    Returns list of dicts: {name, type, href, folder_id?}
    """
    sel = selectors.get("materials", {})
    _wait_for_ajax(page, sel.get("folder", "tr.material-row-folder"))

    return page.evaluate("""() => {
        const items = [];

        // Folders: <tr class="material-row-folder" id="f-{ID}">
        document.querySelectorAll("tr.material-row-folder").forEach(tr => {
            const titleEl = tr.querySelector(".folder-title a");
            const name = titleEl ? titleEl.textContent.trim() : "";
            // Folder ID from tr id="f-{ID}" or from link href ?f={ID}
            let folderId = "";
            const trId = tr.getAttribute("id") || "";
            if (trId.startsWith("f-")) {
                folderId = trId.substring(2);
            }
            if (name) {
                items.push({name, type: "folder", href: "", folder_id: folderId});
            }
        });

        // Content items: <tr class="dr type-assignment|type-document" id="n-{ID}">
        document.querySelectorAll("tr.dr:not(.material-row-folder)").forEach(tr => {
            const classes = tr.className || "";
            let type = "unknown";
            let titleEl = null;

            if (classes.includes("type-assignment")) {
                type = "assignment";
                titleEl = tr.querySelector(".item-title a");
            } else if (classes.includes("type-document")) {
                titleEl = tr.querySelector(".document-body-title a");
                const href = titleEl ? (titleEl.getAttribute("href") || "") : "";
                // Determine subtype from href pattern
                if (href.includes("/page/")) type = "page";
                else if (href.includes("/file/")) type = "file";
                else if (href.includes("/link/")) type = "link";
                else if (href.includes("/discussion/")) type = "discussion";
                else type = "document";
            }

            if (!titleEl) {
                // Fallback: try any link in the row
                titleEl = tr.querySelector("a[href]");
            }

            const name = titleEl ? titleEl.textContent.trim() : "";
            const href = titleEl ? (titleEl.getAttribute("href") || "") : "";
            if (name) {
                items.push({name, type, href, folder_id: ""});
            }
        });

        return items;
    }""")


def _extract_page_text(page: Page, url: str, selectors: dict) -> str:
    """Navigate to a Schoology Page or assignment and extract its text content."""
    sel = selectors.get("materials", {})
    try:
        page.goto(url)
        page.wait_for_load_state("networkidle")

        # Try multiple selectors for the content body
        for selector in [
            sel.get("page_body", ""),
            sel.get("assignment_body", ""),
            ".s-page-content",
            ".page-body",
            "#content-wrapper .content-body",
            ".info-body .content",
            ".assignment-description",
            ".s-content-body",
        ]:
            if not selector:
                continue
            el = page.query_selector(selector)
            if el:
                text = el.text_content().strip()
                if text:
                    return text
    except Exception:
        pass
    return ""


def extract_course_materials(
    page: Page,
    course_id: str,
    selectors: dict,
    test_date: datetime | None = None,
    max_folders: int = 3,
) -> dict:
    """Scrape text content from a course's materials page.

    If test_date is provided, tries to find folders covering the ~3 weeks
    before the test. Otherwise, returns the most recent folders.

    Returns {
        "course_id": str,
        "folders": [{name, items: [{name, type, text}]}],
        "text": str  # all extracted text concatenated
    }
    """
    page.goto(_materials_url(course_id))
    page.wait_for_load_state("networkidle")

    items = _extract_materials_from_page(page, selectors)

    # Separate folders from content
    folders = [i for i in items if i["type"] == "folder"]
    top_level_content = [i for i in items if i["type"] != "folder"]

    # Select relevant folders
    selected_folders = []
    if test_date and folders:
        # Try date-based matching
        for f in folders:
            if _is_folder_relevant(f["name"], test_date):
                selected_folders.append(f)
        # Fall back to last N folders if no date match
        if not selected_folders:
            selected_folders = folders[-max_folders:]
    elif folders:
        selected_folders = folders[-max_folders:]

    result_folders = []
    all_text_parts = []

    for folder in selected_folders:
        folder_items = []
        # Navigate into the folder if we have an ID
        if folder.get("folder_id"):
            page.goto(_folder_url(course_id, folder["folder_id"]))
            page.wait_for_load_state("networkidle")
            folder_content = _extract_materials_from_page(page, selectors)
        else:
            folder_content = []

        for item in folder_content:
            text = ""
            # Extract text from pages and assignments
            if item["type"] in ("page", "assignment") and item.get("href"):
                href = item["href"]
                if not href.startswith("http"):
                    href = config.SCHOOLOGY_BASE_URL + href
                text = _extract_page_text(page, href, selectors)

            folder_items.append({
                "name": item["name"],
                "type": item["type"],
                "text": text,
            })
            if text:
                all_text_parts.append(f"## {item['name']}\n{text}")

        result_folders.append({
            "name": folder["name"],
            "items": folder_items,
        })
        all_text_parts.insert(
            len(all_text_parts) - len(folder_items),
            f"# Folder: {folder['name']}"
        )

    # Also extract text from top-level content items (pages/assignments not in folders)
    for item in top_level_content:
        if item["type"] in ("page", "assignment") and item.get("href"):
            href = item["href"]
            if not href.startswith("http"):
                href = config.SCHOOLOGY_BASE_URL + href
            text = _extract_page_text(page, href, selectors)
            if text:
                all_text_parts.append(f"## {item['name']}\n{text}")

    return {
        "course_id": course_id,
        "folders": result_folders,
        "text": "\n\n".join(all_text_parts),
    }


def _calendar_url() -> str:
    if config.SCHOOLOGY_CHILD_ID:
        return f"{config.SCHOOLOGY_BASE_URL}/parent/calendar"
    return f"{config.SCHOOLOGY_BASE_URL}/user-calendar"


def _grades_url() -> str:
    """Build the grades URL, using the parent path if a child ID is set."""
    if config.SCHOOLOGY_CHILD_ID:
        return f"{config.SCHOOLOGY_BASE_URL}/parent/grades_attendance/grades"
    return f"{config.SCHOOLOGY_BASE_URL}/grades/grades"


def scrape(headed: bool = False) -> dict:
    """
    Scrape assignments and grades from Schoology.

    Returns {"assignments": [...], "grades": [...], "calendar_events": [...]}.
    When ENABLE_TEST_PREP is on, also returns "browser_page" (a live Playwright
    Page) so the caller can reuse the session for materials scraping. The caller
    must call close_browser() when done.

    If headed=True, launches a visible browser (useful for debugging).
    """
    selectors = config.load_selectors()

    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=not headed)
    context = browser.new_context()

    if config.COOKIES_FILE.exists():
        cookies = json.loads(config.COOKIES_FILE.read_text())
        context.add_cookies(cookies)

    page = context.new_page()
    page.goto(config.SCHOOLOGY_BASE_URL)
    page.wait_for_load_state("networkidle")

    if not _is_logged_in(page):
        # Re-launch headed so the user can see the login page
        browser.close()
        browser = pw.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(config.SCHOOLOGY_BASE_URL)
        page.wait_for_load_state("networkidle")
        _interactive_login(page)

    _save_cookies(context)

    # Assignments (loaded via AJAX on /home/upcoming)
    page.goto(f"{config.SCHOOLOGY_BASE_URL}/home/upcoming")
    page.wait_for_load_state("networkidle")
    assignments = _extract_assignments(page, selectors)

    # Grades
    page.goto(_grades_url())
    page.wait_for_load_state("networkidle")
    grades = _extract_grades(page, selectors)

    # Calendar events (via FullCalendar JS API)
    page.goto(_calendar_url())
    page.wait_for_load_state("networkidle")
    calendar_events = _extract_calendar_events(page)

    result = {
        "assignments": assignments,
        "grades": grades,
        "calendar_events": calendar_events,
    }

    if config.ENABLE_TEST_PREP:
        # Keep browser open; caller uses page for materials scraping
        # and must call close_browser() when done
        result["_browser_page"] = page
        result["_browser"] = browser
        result["_playwright"] = pw
    else:
        browser.close()
        pw.stop()

    return result


def close_browser(data: dict) -> None:
    """Close the browser and Playwright instance stored in scrape result."""
    browser = data.pop("_browser", None)
    pw = data.pop("_playwright", None)
    data.pop("_browser_page", None)
    if browser:
        try:
            browser.close()
        except Exception:
            pass
    if pw:
        try:
            pw.stop()
        except Exception:
            pass
