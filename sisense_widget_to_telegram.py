import os
import re
import sys
from datetime import datetime, timezone

import requests
from playwright.sync_api import Page, TimeoutError, sync_playwright


BASE_URL = "https://projectanalytics.sisense.com"

DASHBOARD_ID = "6a4ec462193f10b9e24b4e05"

LOGIN_URL = (
    f"{BASE_URL}/app/account/login"
    f"?src={BASE_URL}/app/main"
)

DASHBOARD_URL = (
    f"{BASE_URL}/app/main/dashboards/{DASHBOARD_ID}"
)

SISENSE_USER = os.environ["SISENSE_USER"]
SISENSE_PASS = os.environ["SISENSE_PASS"]

BOT_TOKEN = os.environ["SBCALLSM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]


# ---------------------------
# Telegram helpers
# ---------------------------

def send_message(text: str) -> None:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    response = requests.post(
        url,
        data={
            "chat_id": CHAT_ID,
            "text": text,
        },
        timeout=180,
    )

    response.raise_for_status()
    print(f"Telegram message sent: {text}")


def send_photo(photo_path: str, caption: str) -> None:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"

    with open(photo_path, "rb") as photo:
        response = requests.post(
            url,
            data={
                "chat_id": CHAT_ID,
                "caption": caption,
            },
            files={
                "photo": (
                    os.path.basename(photo_path),
                    photo,
                    "image/png",
                )
            },
            timeout=180,
        )

    response.raise_for_status()
    print(f"Telegram photo sent: {photo_path}")


# ---------------------------
# Generic helpers
# ---------------------------

def safe_filename(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_-]+", "_", value.strip())
    value = re.sub(r"_+", "_", value).strip("_")
    return value or "unknown"


def wait_short(page: Page, ms: int = 2000) -> None:
    page.wait_for_timeout(ms)


# ---------------------------
# Sisense login / navigation
# ---------------------------

def login(page: Page) -> None:
    print("Opening Sisense login page.")

    page.goto(
        LOGIN_URL,
        wait_until="domcontentloaded",
        timeout=120_000,
    )

    wait_short(page, 3000)

    username_input = page.locator("input[placeholder='Username/Email']")
    password_input = page.locator("input[placeholder='Password']")

    username_input.wait_for(state="visible", timeout=30_000)

    username_input.fill(SISENSE_USER)
    password_input.fill(SISENSE_PASS)

    page.get_by_role("button", name="Login").click()

    try:
        page.wait_for_url("**/app/main/**", timeout=60_000)
    except Exception:
        wait_short(page, 8000)

    print(f"URL after login: {page.url}")

    if "login" in page.url.lower():
        page.screenshot(path="sb_calls_login_failed.png", full_page=True)
        raise RuntimeError("Sisense login did not complete.")


def open_dashboard(page: Page) -> None:
    print("Opening dashboard.")
    page.goto(
        DASHBOARD_URL,
        wait_until="domcontentloaded",
        timeout=120_000,
    )

    wait_short(page, 10_000)

    if "login" in page.url.lower():
        page.screenshot(path="sb_calls_redirected_to_login.png", full_page=True)
        raise RuntimeError("Sisense redirected back to login.")


# ---------------------------
# Chart detection / crop
# ---------------------------

def wait_for_chart(page: Page) -> None:
    print("Waiting for chart to render.")

    page.wait_for_function(
        """
        () => {
            const svgs = Array.from(document.querySelectorAll("svg"));

            return svgs.some(svg => {
                const rect = svg.getBoundingClientRect();
                const style = window.getComputedStyle(svg);
                const text = (svg.textContent || "").replace(/\\s+/g, " ").trim();

                return (
                    rect.width > 700 &&
                    rect.height > 400 &&
                    rect.right > 0 &&
                    rect.bottom > 0 &&
                    style.display !== "none" &&
                    style.visibility !== "hidden" &&
                    Number(style.opacity || 1) > 0 &&
                    text.includes("Total Call Duration") &&
                    text.includes("Unique Customers")
                );
            });
        }
        """,
        timeout=90_000,
    )

    wait_short(page, 3000)
    print("Chart found.")


def screenshot_chart_only(page: Page, output_path: str) -> None:
    wait_for_chart(page)

    chart_handle = page.evaluate_handle(
        """
        () => {
            const svgs = Array.from(document.querySelectorAll("svg"));

            const candidates = svgs
                .map(svg => {
                    const rect = svg.getBoundingClientRect();
                    const text = (svg.textContent || "").replace(/\\s+/g, " ").trim();
                    const style = window.getComputedStyle(svg);

                    let score = rect.width * rect.height;

                    if (text.includes("Total Call Duration")) score += 100000000;
                    if (text.includes("Unique Customers")) score += 100000000;

                    return { svg, rect, text, style, score };
                })
                .filter(item =>
                    item.rect.width > 700 &&
                    item.rect.height > 400 &&
                    item.rect.right > 0 &&
                    item.rect.bottom > 0 &&
                    item.style.display !== "none" &&
                    item.style.visibility !== "hidden" &&
                    Number(item.style.opacity || 1) > 0 &&
                    item.text.includes("Total Call Duration") &&
                    item.text.includes("Unique Customers")
                )
                .sort((a, b) => b.score - a.score);

            if (candidates.length === 0) {
                return null;
            }

            const chartSvg = candidates[0].svg;
            const svgRect = chartSvg.getBoundingClientRect();

            let selectedElement = chartSvg;
            let currentElement = chartSvg.parentElement;

            for (
                let level = 0;
                level < 8 && currentElement;
                level += 1, currentElement = currentElement.parentElement
            ) {
                const rect = currentElement.getBoundingClientRect();
                const text = (currentElement.textContent || "")
                    .replace(/\\s+/g, " ")
                    .trim();

                const widthDifference = rect.width - svgRect.width;
                const heightDifference = rect.height - svgRect.height;

                const sizeIsReasonable =
                    rect.width >= svgRect.width &&
                    rect.height >= svgRect.height &&
                    widthDifference <= 100 &&
                    heightDifference <= 120;

                if (sizeIsReasonable) {
                    selectedElement = currentElement;

                    if (text.includes("Agent Call Display")) {
                        break;
                    }
                }
            }

            return selectedElement;
        }
        """
    )

    chart_element = chart_handle.as_element()

    if chart_element is None:
        page.screenshot(path="sb_calls_chart_crop_debug.png", full_page=True)
        raise RuntimeError("Could not locate chart container.")

    box = chart_element.bounding_box()

    if box is None:
        raise RuntimeError("Chart container has no visible dimensions.")

    print(
        "Chart container:",
        {
            "x": round(box["x"], 2),
            "y": round(box["y"], 2),
            "width": round(box["width"], 2),
            "height": round(box["height"], 2),
        },
    )

    chart_element.screenshot(path=output_path)
    print(f"Chart screenshot created: {output_path}")


# ---------------------------
# Filter handling
# ---------------------------

def ensure_filters_panel(page: Page) -> None:
    # On dashboard page the filters panel is usually visible already.
    # If not, try opening it.
    try:
        if page.get_by_text("Filters", exact=True).count() > 0:
            print("Filters panel found.")
            return
    except Exception:
        pass

    # fallback - do nothing unless needed later
    print("Filters panel check complete.")


def click_owner_sd_filter(page: Page) -> None:
    print("Opening Owner SD filter.")

    candidates = [
        page.get_by_text("Owner SD", exact=True),
        page.locator("text=Owner SD"),
    ]

    for locator in candidates:
        try:
            locator.first.click(timeout=10_000)
            wait_short(page, 2000)
            return
        except Exception:
            pass

    page.screenshot(path="sb_calls_owner_sd_not_found.png", full_page=True)
    raise RuntimeError("Could not click the Owner SD filter.")


def discover_owner_sd_values(page: Page) -> list[str]:
    """
    Tries to open the Owner SD filter and extract all displayed values.
    This is heuristic because Sisense DOM varies a lot.
    """

    click_owner_sd_filter(page)
    wait_short(page, 2500)

    values = page.evaluate(
        """
        () => {
            function isVisible(el) {
                const rect = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                return (
                    rect.width > 0 &&
                    rect.height > 0 &&
                    style.display !== "none" &&
                    style.visibility !== "hidden" &&
                    Number(style.opacity || 1) > 0
                );
            }

            function clean(text) {
                return (text || "").replace(/\\s+/g, " ").trim();
            }

            const blacklist = new Set([
                "",
                "Include all",
                "Search",
                "Apply",
                "Cancel",
                "Filters",
                "Owner SD",
                "Description",
                "Table",
                "Column",
                "owner_sd",
                "Employees",
                "Exodus"
            ]);

            const containers = Array.from(document.querySelectorAll("body *"))
                .filter(el => isVisible(el))
                .map(el => {
                    const rect = el.getBoundingClientRect();
                    return {
                        el,
                        area: rect.width * rect.height,
                        text: clean(el.innerText || "")
                    };
                })
                .filter(item =>
                    item.area > 20000 &&
                    item.text.includes("Include all")
                )
                .sort((a, b) => b.area - a.area);

            if (containers.length === 0) {
                return [];
            }

            const container = containers[0].el;

            const rawTexts = Array.from(
                container.querySelectorAll("label, li, [role='option'], [role='menuitemcheckbox'], span, div")
            )
                .filter(el => isVisible(el))
                .map(el => clean(el.innerText || ""))
                .filter(text => text.length > 0 && text.length <= 80);

            const unique = [];
            for (const text of rawTexts) {
                if (blacklist.has(text)) continue;
                if (/^[-0-9]+$/.test(text)) continue;
                if (text.toLowerCase().includes("include all")) continue;
                if (unique.includes(text)) continue;
                unique.push(text);
            }

            return unique;
        }
        """
    )

    # close popup if possible by pressing Escape
    page.keyboard.press("Escape")
    wait_short(page, 1000)

    values = [v.strip() for v in values if v and v.strip()]
    values = sorted(set(values))

    print(f"Discovered Owner SD values: {values}")

    if not values:
        page.screenshot(path="sb_calls_owner_sd_discovery_failed.png", full_page=True)
        raise RuntimeError(
            "Could not discover Owner SD values from the filter popup."
        )

    return values


def apply_owner_sd_filter(page: Page, owner_value: str) -> None:
    """
    Reload the dashboard fresh, open the Owner SD filter,
    choose a value, and click Apply.
    """

    print(f"Applying Owner SD filter: {owner_value}")

    open_dashboard(page)
    ensure_filters_panel(page)

    click_owner_sd_filter(page)
    wait_short(page, 2500)

    # Try search input first if one exists
    search_locators = [
        page.locator("input[type='search']"),
        page.locator("input[placeholder*='Search']"),
        page.locator("input"),
    ]

    for search_locator in search_locators:
        try:
            if search_locator.count() > 0:
                search_locator.first.fill("")
                search_locator.first.fill(owner_value)
                wait_short(page, 1500)
                break
        except Exception:
            pass

    # Try exact visible text click inside popup
    clicked = False
    value_locators = [
        page.get_by_text(owner_value, exact=True),
        page.locator(f"text={owner_value}"),
    ]

    for locator in value_locators:
        try:
            locator.last.click(timeout=10_000)
            clicked = True
            wait_short(page, 1500)
            break
        except Exception:
            pass

    if not clicked:
        page.screenshot(
            path=f"sb_calls_owner_click_failed_{safe_filename(owner_value)}.png",
            full_page=True,
        )
        raise RuntimeError(f"Could not select Owner SD value: {owner_value}")

    # Try popup Apply first
    apply_clicked = False
    for locator in [
        page.get_by_role("button", name="Apply"),
        page.locator("button:has-text('Apply')"),
        page.locator("text=Apply"),
    ]:
        try:
            locator.first.click(timeout=5000)
            apply_clicked = True
            wait_short(page, 5000)
            break
        except Exception:
            pass

    if not apply_clicked:
        print("Apply button in popup/top bar not explicitly clicked. Continuing.")

    # Wait again for dashboard refresh
    wait_short(page, 8000)
    print(f"Owner SD applied: {owner_value}")


# ---------------------------
# Main
# ---------------------------

def main() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)

        context = browser.new_context(
            viewport={
                "width": 1800,
                "height": 1100,
            },
            device_scale_factor=1,
        )

        page = context.new_page()

        try:
            login(page)
            open_dashboard(page)
            ensure_filters_panel(page)

            owner_values = discover_owner_sd_values(page)

            send_message(
                "SB Calls Monitor started. "
                f"Found {len(owner_values)} Owner SD values: "
                + ", ".join(owner_values)
            )

            for owner_value in owner_values:
                try:
                    apply_owner_sd_filter(page, owner_value)

                    screenshot_path = (
                        f"sb_calls_{safe_filename(owner_value)}.png"
                    )

                    screenshot_chart_only(page, screenshot_path)

                    timestamp = datetime.now(timezone.utc).strftime(
                        "%Y-%m-%d %H:%M UTC"
                    )

                    send_photo(
                        screenshot_path,
                        f"Owner SD: {owner_value} | SB Calls | {timestamp}",
                    )

                except Exception as owner_error:
                    error_message = (
                        f'Failed for Owner SD "{owner_value}": {owner_error}'
                    )
                    print(error_message)
                    send_message(error_message)

        except Exception as error:
            try:
                page.screenshot(
                    path="sb_calls_error_debug.png",
                    full_page=True,
                )
            except Exception:
                pass

            raise RuntimeError(f"Main process failed: {error}")

        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
