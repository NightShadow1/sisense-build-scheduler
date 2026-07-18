import os
import re
import sys
from datetime import datetime, timezone

import requests
from playwright.sync_api import ElementHandle, Page, sync_playwright


BASE_URL = "https://projectanalytics.sisense.com"

DASHBOARD_ID = "6a4ec462193f10b9e24b4e05"
WIDGET_ID = "6a4ec71e193f10b9e24b4e20"

LOGIN_URL = (
    f"{BASE_URL}/app/account/login"
    f"?src={BASE_URL}/app/main"
)

WIDGET_URL = (
    f"{BASE_URL}/app/main/dashboards/"
    f"{DASHBOARD_ID}/widgets/{WIDGET_ID}"
)

SISENSE_USER = os.environ["SISENSE_USER"]
SISENSE_PASS = os.environ["SISENSE_PASS"]

BOT_TOKEN = os.environ["SBCALLSM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]


# ============================================================
# Telegram
# ============================================================

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


# ============================================================
# General helpers
# ============================================================

def safe_filename(value: str) -> str:
    filename = re.sub(
        r"[^A-Za-z0-9_-]+",
        "_",
        value.strip(),
    )

    filename = re.sub(
        r"_+",
        "_",
        filename,
    ).strip("_")

    return filename or "unknown_owner_sd"


def clean_owner_values(values: list[str]) -> list[str]:
    ignored_values = {
        "",
        "Owner SD",
        "Owner_SD",
        "Include all",
        "Include All",
        "Select all",
        "Select All",
        "Clear",
        "Apply",
        "Cancel",
        "Search",
        "Filter",
        "Filters",
        "No results",
        "Loading",
    }

    result = []

    for value in values:
        value = re.sub(r"\s+", " ", value).strip()

        if not value:
            continue

        if value in ignored_values:
            continue

        if value.lower().startswith("include all"):
            continue

        if value.lower().startswith("select all"):
            continue

        if value.lower().startswith("search"):
            continue

        if len(value) > 100:
            continue

        if value not in result:
            result.append(value)

    return result


# ============================================================
# Sisense login and navigation
# ============================================================

def login_to_sisense(page: Page) -> None:
    print("Opening Sisense login page.")

    page.goto(
        LOGIN_URL,
        wait_until="domcontentloaded",
        timeout=120_000,
    )

    page.wait_for_timeout(3_000)

    username_input = page.locator(
        "input[placeholder='Username/Email']"
    )

    password_input = page.locator(
        "input[placeholder='Password']"
    )

    username_input.wait_for(
        state="visible",
        timeout=30_000,
    )

    username_input.fill(SISENSE_USER)
    password_input.fill(SISENSE_PASS)

    login_button = page.get_by_role(
        "button",
        name="Login",
    )

    login_button.click()

    try:
        page.wait_for_url(
            "**/app/main/**",
            timeout=60_000,
        )
    except Exception:
        page.wait_for_timeout(8_000)

    print(f"URL after login: {page.url}")

    if "login" in page.url.lower():
        page.screenshot(
            path="sb_calls_login_failed.png",
            full_page=True,
        )

        raise RuntimeError(
            "Sisense login did not complete."
        )


def open_widget(page: Page) -> None:
    print("Opening Agent Call Display widget.")

    page.goto(
        WIDGET_URL,
        wait_until="domcontentloaded",
        timeout=120_000,
    )

    page.wait_for_timeout(10_000)

    print(f"Widget URL: {page.url}")

    if "login" in page.url.lower():
        page.screenshot(
            path="sb_calls_redirected_to_login.png",
            full_page=True,
        )

        raise RuntimeError(
            "Sisense redirected back to login."
        )


# ============================================================
# Owner SD filter
# ============================================================

def find_owner_sd_label(page: Page):
    """
    Find the Owner SD filter label located furthest to the right.

    This avoids accidentally finding text from the chart or another
    unrelated part of the page.
    """

    possible_labels = [
        page.get_by_text("Owner SD", exact=True),
        page.get_by_text("Owner_SD", exact=True),
    ]

    best_locator = None
    best_x = -1

    for locator_group in possible_labels:
        count = locator_group.count()

        for index in range(count):
            locator = locator_group.nth(index)

            try:
                if not locator.is_visible():
                    continue

                box = locator.bounding_box()

                if box is None:
                    continue

                if box["x"] > best_x:
                    best_x = box["x"]
                    best_locator = locator

            except Exception:
                continue

    if best_locator is None:
        page.screenshot(
            path="sb_calls_owner_sd_label_not_found.png",
            full_page=True,
        )

        raise RuntimeError(
            "Could not find the Owner SD filter."
        )

    return best_locator


def open_owner_sd_filter(page: Page) -> None:
    print("Opening Owner SD filter.")

    owner_sd_label = find_owner_sd_label(page)

    try:
        owner_sd_label.click(timeout=10_000)
    except Exception:
        # The text itself might not be clickable, so click its parent.
        owner_sd_label.locator("xpath=..").click(
            timeout=10_000
        )

    page.wait_for_timeout(2_500)


def find_owner_sd_popup(page: Page) -> ElementHandle:
    """
    Find the visible popup created after opening Owner SD.

    The popup must contain filter-option controls or text such as
    'Include all'. The smallest matching popup is preferred so the
    whole dashboard/filter panel is not selected.
    """

    popup_handle = page.evaluate_handle(
        """
        () => {
            function isVisible(element) {
                const rect = element.getBoundingClientRect();
                const style = window.getComputedStyle(element);

                return (
                    rect.width > 0 &&
                    rect.height > 0 &&
                    rect.right > 0 &&
                    rect.bottom > 0 &&
                    style.display !== "none" &&
                    style.visibility !== "hidden" &&
                    Number(style.opacity || 1) > 0
                );
            }

            const elements = Array.from(
                document.querySelectorAll("body *")
            );

            const candidates = elements
                .filter(isVisible)
                .map(element => {
                    const rect = element.getBoundingClientRect();

                    const text = (
                        element.innerText ||
                        element.textContent ||
                        ""
                    )
                        .replace(/\\s+/g, " ")
                        .trim();

                    const checkboxCount =
                        element.querySelectorAll(
                            "input[type='checkbox'], " +
                            "[role='checkbox'], " +
                            "[role='option'], " +
                            "[role='menuitemcheckbox']"
                        ).length;

                    const area = rect.width * rect.height;

                    return {
                        element,
                        rect,
                        text,
                        checkboxCount,
                        area
                    };
                })
                .filter(item =>
                    item.rect.width >= 180 &&
                    item.rect.width <= 900 &&
                    item.rect.height >= 80 &&
                    item.rect.height <= 1000 &&
                    (
                        item.text.includes("Include all") ||
                        item.text.includes("Include All") ||
                        item.checkboxCount > 0
                    )
                )
                .sort((a, b) => {
                    /*
                     * Prefer popups with actual option controls.
                     * When control counts are equal, prefer the
                     * smallest matching container.
                     */
                    if (a.checkboxCount !== b.checkboxCount) {
                        return b.checkboxCount - a.checkboxCount;
                    }

                    return a.area - b.area;
                });

            if (candidates.length === 0) {
                return null;
            }

            return candidates[0].element;
        }
        """
    )

    popup = popup_handle.as_element()

    if popup is None:
        page.screenshot(
            path="sb_calls_owner_sd_popup_not_found.png",
            full_page=True,
        )

        raise RuntimeError(
            "Could not identify the Owner SD values popup."
        )

    box = popup.bounding_box()

    print(
        "Owner SD popup:",
        None if box is None else {
            "x": round(box["x"], 2),
            "y": round(box["y"], 2),
            "width": round(box["width"], 2),
            "height": round(box["height"], 2),
        },
    )

    return popup


def extract_visible_owner_values(
    popup: ElementHandle,
) -> list[str]:
    """
    Extract option text only from inside the Owner SD popup.
    """

    values = popup.evaluate(
        """
        root => {
            function isVisible(element) {
                const rect = element.getBoundingClientRect();
                const style = window.getComputedStyle(element);

                return (
                    rect.width > 0 &&
                    rect.height > 0 &&
                    style.display !== "none" &&
                    style.visibility !== "hidden" &&
                    Number(style.opacity || 1) > 0
                );
            }

            function clean(value) {
                return (value || "")
                    .replace(/\\s+/g, " ")
                    .trim();
            }

            const values = [];

            const selectors = [
                "[role='option']",
                "[role='menuitemcheckbox']",
                "[role='checkbox']",
                "input[type='checkbox']",
                "label",
                "li"
            ];

            const elements = Array.from(
                root.querySelectorAll(selectors.join(","))
            );

            for (const element of elements) {
                if (!isVisible(element)) {
                    continue;
                }

                let row = element;

                /*
                 * Walk up a few levels to find the option row containing
                 * both the checkbox and its text.
                 */
                for (let level = 0; level < 4; level += 1) {
                    const parent = row.parentElement;

                    if (!parent || parent === root) {
                        break;
                    }

                    const parentRect =
                        parent.getBoundingClientRect();

                    if (
                        parentRect.height >= 18 &&
                        parentRect.height <= 80
                    ) {
                        row = parent;
                    } else {
                        break;
                    }
                }

                const text = clean(
                    row.innerText ||
                    row.textContent ||
                    element.getAttribute("aria-label") ||
                    ""
                );

                if (text) {
                    for (const line of text.split(/\\n+/)) {
                        const cleanedLine = clean(line);

                        if (
                            cleanedLine &&
                            !values.includes(cleanedLine)
                        ) {
                            values.push(cleanedLine);
                        }
                    }
                }
            }

            /*
             * Fallback for Sisense versions that do not expose semantic
             * checkbox/option attributes.
             */
            if (values.length === 0) {
                const leafElements = Array.from(
                    root.querySelectorAll("*")
                ).filter(element =>
                    isVisible(element) &&
                    element.children.length === 0
                );

                for (const element of leafElements) {
                    const text = clean(
                        element.innerText ||
                        element.textContent ||
                        ""
                    );

                    if (
                        text &&
                        text.length <= 100 &&
                        !values.includes(text)
                    ) {
                        values.push(text);
                    }
                }
            }

            return values;
        }
        """
    )

    return clean_owner_values(values)


def scroll_owner_sd_popup(
    popup: ElementHandle,
) -> dict:
    """
    Scroll the option list inside the Owner SD popup.

    Returns whether scrolling is finished.
    """

    return popup.evaluate(
        """
        root => {
            const candidates = [
                root,
                ...Array.from(root.querySelectorAll("*"))
            ]
                .filter(element =>
                    element.scrollHeight >
                    element.clientHeight + 10
                )
                .map(element => ({
                    element,
                    difference:
                        element.scrollHeight -
                        element.clientHeight
                }))
                .sort(
                    (a, b) =>
                        b.difference - a.difference
                );

            if (candidates.length === 0) {
                return {
                    done: true,
                    scrollTop: 0,
                    scrollHeight: 0,
                    clientHeight: 0
                };
            }

            const scrollElement = candidates[0].element;

            const previousScrollTop =
                scrollElement.scrollTop;

            const newScrollTop = Math.min(
                previousScrollTop +
                    Math.max(
                        scrollElement.clientHeight * 0.8,
                        100
                    ),
                scrollElement.scrollHeight
            );

            scrollElement.scrollTop = newScrollTop;

            const done =
                newScrollTop +
                    scrollElement.clientHeight >=
                scrollElement.scrollHeight - 5 ||
                newScrollTop === previousScrollTop;

            return {
                done,
                scrollTop: newScrollTop,
                scrollHeight:
                    scrollElement.scrollHeight,
                clientHeight:
                    scrollElement.clientHeight
            };
        }
        """
    )


def discover_owner_sd_values(page: Page) -> list[str]:
    open_owner_sd_filter(page)

    popup = find_owner_sd_popup(page)

    all_values = []

    for _ in range(50):
        visible_values = extract_visible_owner_values(
            popup
        )

        for value in visible_values:
            if value not in all_values:
                all_values.append(value)

        scroll_state = scroll_owner_sd_popup(
            popup
        )

        page.wait_for_timeout(500)

        if scroll_state["done"]:
            # One final extraction after reaching the bottom.
            visible_values = extract_visible_owner_values(
                popup
            )

            for value in visible_values:
                if value not in all_values:
                    all_values.append(value)

            break

    page.keyboard.press("Escape")
    page.wait_for_timeout(1_000)

    all_values = clean_owner_values(all_values)

    print(
        f"Actual Owner SD values found: "
        f"{all_values}"
    )

    if not all_values:
        page.screenshot(
            path="sb_calls_owner_sd_values_not_found.png",
            full_page=True,
        )

        raise RuntimeError(
            "No Owner SD values were found in the popup."
        )

    return all_values


def find_option_in_popup(
    popup: ElementHandle,
    owner_value: str,
) -> ElementHandle | None:
    option_handle = popup.evaluate_handle(
        """
        (root, requiredValue) => {
            function isVisible(element) {
                const rect =
                    element.getBoundingClientRect();

                const style =
                    window.getComputedStyle(element);

                return (
                    rect.width > 0 &&
                    rect.height > 0 &&
                    style.display !== "none" &&
                    style.visibility !== "hidden" &&
                    Number(style.opacity || 1) > 0
                );
            }

            function clean(value) {
                return (value || "")
                    .replace(/\\s+/g, " ")
                    .trim();
            }

            const elements = Array.from(
                root.querySelectorAll("*")
            ).filter(isVisible);

            const exactMatches = elements.filter(
                element => {
                    const text = clean(
                        element.innerText ||
                        element.textContent ||
                        element.getAttribute(
                            "aria-label"
                        ) ||
                        ""
                    );

                    return text === requiredValue;
                }
            );

            if (exactMatches.length === 0) {
                return null;
            }

            /*
             * Prefer the smallest exact-match element, then move to
             * its clickable option row.
             */
            exactMatches.sort((a, b) => {
                const aRect =
                    a.getBoundingClientRect();

                const bRect =
                    b.getBoundingClientRect();

                return (
                    aRect.width * aRect.height -
                    bRect.width * bRect.height
                );
            });

            let selected =
                exactMatches[0];

            for (let level = 0; level < 4; level += 1) {
                const parent =
                    selected.parentElement;

                if (!parent || parent === root) {
                    break;
                }

                const rect =
                    parent.getBoundingClientRect();

                const hasControl =
                    parent.matches(
                        "[role='option'], " +
                        "[role='menuitemcheckbox'], " +
                        "[role='checkbox'], label, li"
                    ) ||
                    parent.querySelector(
                        "input[type='checkbox'], " +
                        "[role='checkbox']"
                    );

                if (
                    hasControl &&
                    rect.height >= 18 &&
                    rect.height <= 100
                ) {
                    selected = parent;
                    break;
                }
            }

            return selected;
        }
        """,
        owner_value,
    )

    return option_handle.as_element()


def select_owner_sd(
    page: Page,
    owner_value: str,
) -> None:
    print(
        f'Selecting Owner SD "{owner_value}".'
    )

    open_owner_sd_filter(page)
    popup = find_owner_sd_popup(page)

    # Use the popup search box when available.
    search_inputs = popup.query_selector_all(
        "input[type='search'], "
        "input[placeholder*='Search'], "
        "input[type='text']"
    )

    for search_input in search_inputs:
        try:
            if search_input.is_visible():
                search_input.fill(owner_value)
                page.wait_for_timeout(1_500)
                break
        except Exception:
            continue

    option = find_option_in_popup(
        popup,
        owner_value,
    )

    if option is None:
        # Search might not exist, so scroll until the value is found.
        for _ in range(50):
            option = find_option_in_popup(
                popup,
                owner_value,
            )

            if option is not None:
                break

            scroll_state = scroll_owner_sd_popup(
                popup
            )

            page.wait_for_timeout(400)

            if scroll_state["done"]:
                break

    if option is None:
        page.screenshot(
            path=(
                "sb_calls_owner_not_found_"
                f"{safe_filename(owner_value)}.png"
            ),
            full_page=True,
        )

        raise RuntimeError(
            f'Could not find Owner SD value '
            f'"{owner_value}" inside the filter.'
        )

    option.click()
    page.wait_for_timeout(1_000)

    # Close the filter popup.
    page.keyboard.press("Escape")

    # Dashboard has "Update on Every Change", so wait for refresh.
    page.wait_for_timeout(8_000)

    print(
        f'Owner SD "{owner_value}" applied.'
    )


# ============================================================
# Chart
# ============================================================

def wait_for_chart(page: Page) -> None:
    page.wait_for_function(
        """
        () => {
            const svgs = Array.from(
                document.querySelectorAll("svg")
            );

            return svgs.some(svg => {
                const rect =
                    svg.getBoundingClientRect();

                const style =
                    window.getComputedStyle(svg);

                const text = (
                    svg.textContent || ""
                )
                    .replace(/\\s+/g, " ")
                    .trim();

                return (
                    rect.width > 700 &&
                    rect.height > 400 &&
                    rect.right > 0 &&
                    rect.bottom > 0 &&
                    style.display !== "none" &&
                    style.visibility !== "hidden" &&
                    Number(style.opacity || 1) > 0 &&
                    text.includes(
                        "Total Call Duration"
                    ) &&
                    text.includes(
                        "Unique Customers"
                    )
                );
            });
        }
        """,
        timeout=90_000,
    )

    page.wait_for_timeout(3_000)


def screenshot_chart_only(
    page: Page,
    output_path: str,
) -> None:
    wait_for_chart(page)

    chart_handle = page.evaluate_handle(
        """
        () => {
            const svgs = Array.from(
                document.querySelectorAll("svg")
            );

            const candidates = svgs
                .map(svg => {
                    const rect =
                        svg.getBoundingClientRect();

                    const text = (
                        svg.textContent || ""
                    )
                        .replace(/\\s+/g, " ")
                        .trim();

                    const style =
                        window.getComputedStyle(svg);

                    let score =
                        rect.width * rect.height;

                    if (
                        text.includes(
                            "Total Call Duration"
                        )
                    ) {
                        score += 100000000;
                    }

                    if (
                        text.includes(
                            "Unique Customers"
                        )
                    ) {
                        score += 100000000;
                    }

                    return {
                        svg,
                        rect,
                        text,
                        style,
                        score
                    };
                })
                .filter(item =>
                    item.rect.width > 700 &&
                    item.rect.height > 400 &&
                    item.rect.right > 0 &&
                    item.rect.bottom > 0 &&
                    item.style.display !== "none" &&
                    item.style.visibility !== "hidden" &&
                    Number(
                        item.style.opacity || 1
                    ) > 0 &&
                    item.text.includes(
                        "Total Call Duration"
                    ) &&
                    item.text.includes(
                        "Unique Customers"
                    )
                )
                .sort(
                    (a, b) =>
                        b.score - a.score
                );

            if (candidates.length === 0) {
                return null;
            }

            const chartSvg =
                candidates[0].svg;

            const svgRect =
                chartSvg.getBoundingClientRect();

            let selectedElement = chartSvg;
            let currentElement =
                chartSvg.parentElement;

            for (
                let level = 0;
                level < 8 && currentElement;
                level += 1,
                currentElement =
                    currentElement.parentElement
            ) {
                const rect =
                    currentElement
                        .getBoundingClientRect();

                const text = (
                    currentElement.textContent ||
                    ""
                )
                    .replace(/\\s+/g, " ")
                    .trim();

                const widthDifference =
                    rect.width - svgRect.width;

                const heightDifference =
                    rect.height - svgRect.height;

                const sizeIsReasonable =
                    rect.width >= svgRect.width &&
                    rect.height >= svgRect.height &&
                    widthDifference <= 100 &&
                    heightDifference <= 120;

                if (sizeIsReasonable) {
                    selectedElement =
                        currentElement;

                    if (
                        text.includes(
                            "Agent Call Display"
                        )
                    ) {
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
        raise RuntimeError(
            "Could not locate the chart container."
        )

    chart_element.screenshot(
        path=output_path,
    )

    print(
        f"Chart screenshot created: "
        f"{output_path}"
    )


# ============================================================
# Main
# ============================================================

def main() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
        )

        context = browser.new_context(
            viewport={
                "width": 1800,
                "height": 1100,
            },
            device_scale_factor=1,
        )

        page = context.new_page()

        try:
            login_to_sisense(page)
            open_widget(page)

            owner_sd_values = (
                discover_owner_sd_values(page)
            )

            send_message(
                "SB Calls Monitor started. "
                f"Found {len(owner_sd_values)} "
                "Owner SD values: "
                + ", ".join(owner_sd_values)
            )

            for owner_value in owner_sd_values:
                try:
                    /*
                     * Reload the widget for each Owner SD so every
                     * iteration starts from a clean page state.
                     */
                    open_widget(page)

                    select_owner_sd(
                        page,
                        owner_value,
                    )

                    screenshot_path = (
                        "sb_calls_"
                        f"{safe_filename(owner_value)}"
                        ".png"
                    )

                    screenshot_chart_only(
                        page,
                        screenshot_path,
                    )

                    timestamp = (
                        datetime.now(timezone.utc)
                        .strftime(
                            "%Y-%m-%d %H:%M UTC"
                        )
                    )

                    send_photo(
                        screenshot_path,
                        (
                            f"Owner SD: {owner_value}"
                            f" | SB Calls | {timestamp}"
                        ),
                    )

                except Exception as owner_error:
                    error_text = (
                        f'Failed for Owner SD '
                        f'"{owner_value}": '
                        f"{owner_error}"
                    )

                    print(error_text)
                    send_message(error_text)

        except Exception as error:
            try:
                page.screenshot(
                    path="sb_calls_error_debug.png",
                    full_page=True,
                )
            except Exception:
                pass

            raise RuntimeError(
                f"SB Calls process failed: {error}"
            )

        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(
            f"ERROR: {error}",
            file=sys.stderr,
        )
        sys.exit(1)
