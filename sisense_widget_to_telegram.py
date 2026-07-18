import os
import re
import sys
from datetime import datetime, timezone

import requests
from playwright.sync_api import Page, sync_playwright


BASE_URL = "https://projectanalytics.sisense.com"
DASHBOARD_ID = "6a4ec462193f10b9e24b4e05"
WIDGET_ID = "6a4ec71e193f10b9e24b4e20"

LOGIN_URL = f"{BASE_URL}/app/account/login?src={BASE_URL}/app/main"

WIDGET_URL = (
    f"{BASE_URL}/app/main/dashboards/"
    f"{DASHBOARD_ID}/widgets/{WIDGET_ID}"
)

SISENSE_USER = os.environ["SISENSE_USER"]
SISENSE_PASS = os.environ["SISENSE_PASS"]

BOT_TOKEN = os.environ["SBCALLSM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]


IGNORED_OWNER_TEXTS = {
    "",
    "Owner SD",
    "Include all (no filter applied)",
    "Allow multiselect for lists",
    "Find in the list",
    "Select All",
    "Clear All",
    "Is not",
    "Select from list",
    "Custom",
    "Apply",
    "Cancel",
    "1 selected",
}


# ============================================================
# Telegram
# ============================================================

def send_message(text: str) -> None:
    response = requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        data={
            "chat_id": CHAT_ID,
            "text": text,
        },
        timeout=180,
    )

    response.raise_for_status()


def send_photo(photo_path: str, caption: str) -> None:
    with open(photo_path, "rb") as photo:
        response = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
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


# ============================================================
# General helpers
# ============================================================

def safe_filename(value: str) -> str:
    value = re.sub(
        r"[^A-Za-z0-9_-]+",
        "_",
        value.strip(),
    )

    value = re.sub(
        r"_+",
        "_",
        value,
    ).strip("_")

    return value or "unknown_owner"


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

    username = page.locator(
        "input[placeholder='Username/Email']"
    )

    password = page.locator(
        "input[placeholder='Password']"
    )

    username.wait_for(
        state="visible",
        timeout=30_000,
    )

    username.fill(SISENSE_USER)
    password.fill(SISENSE_PASS)

    page.get_by_role(
        "button",
        name="Login",
    ).click()

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
        raise RuntimeError(
            "Sisense redirected back to the login page."
        )


# ============================================================
# Owner SD filter
# ============================================================

def find_owner_sd_filter_label(page: Page):
    candidates = page.get_by_text(
        "Owner SD",
        exact=True,
    )

    best = None
    best_x = -1.0

    for index in range(candidates.count()):
        candidate = candidates.nth(index)

        try:
            if not candidate.is_visible():
                continue

            box = candidate.bounding_box()

            if box is not None and box["x"] > best_x:
                best = candidate
                best_x = box["x"]

        except Exception:
            continue

    if best is None:
        page.screenshot(
            path="owner_sd_filter_not_found.png",
            full_page=True,
        )

        raise RuntimeError(
            "Could not find the Owner SD dashboard filter."
        )

    return best


def open_owner_sd_filter(page: Page) -> None:
    label = find_owner_sd_filter_label(page)

    try:
        label.click(
            timeout=10_000,
        )

    except Exception:
        label.locator(
            "xpath=.."
        ).click(
            timeout=10_000,
        )

    page.wait_for_timeout(2_000)


def find_owner_sd_dialog(page: Page):
    handle = page.evaluate_handle(
        """
        () => {
            const visible = element => {
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
            };

            const clean = value =>
                (value || "")
                    .replace(/\\s+/g, " ")
                    .trim();

            const titles = Array.from(
                document.querySelectorAll("body *")
            ).filter(element =>
                visible(element) &&
                clean(
                    element.innerText ||
                    element.textContent
                ) === "Owner SD"
            );

            for (const title of titles) {
                let current = title;

                for (
                    let level = 0;
                    level < 12 && current;
                    level += 1
                ) {
                    const text = clean(
                        current.innerText ||
                        current.textContent
                    );

                    const rect =
                        current.getBoundingClientRect();

                    const buttons = Array.from(
                        current.querySelectorAll(
                            "button, [role='button']"
                        )
                    ).map(element =>
                        clean(
                            element.innerText ||
                            element.textContent
                        )
                    );

                    if (
                        rect.width >= 500 &&
                        rect.height >= 400 &&
                        buttons.includes("Apply") &&
                        buttons.includes("Cancel") &&
                        text.includes("Include all")
                    ) {
                        return current;
                    }

                    current = current.parentElement;
                }
            }

            return null;
        }
        """
    )

    dialog = handle.as_element()

    if dialog is None:
        page.screenshot(
            path="owner_sd_dialog_not_found.png",
            full_page=True,
        )

        raise RuntimeError(
            "Could not identify the Owner SD filter dialog."
        )

    return dialog


def find_owner_list_scroller(dialog):
    handle = dialog.evaluate_handle(
        """
        root => {
            const candidates = Array.from(
                root.querySelectorAll("*")
            )
                .filter(element =>
                    element.scrollHeight >
                        element.clientHeight + 20 &&
                    element.clientHeight >= 120 &&
                    element.clientWidth >= 200
                )
                .map(element => ({
                    element: element,
                    range:
                        element.scrollHeight -
                        element.clientHeight,
                    area:
                        element.clientWidth *
                        element.clientHeight
                }))
                .sort((a, b) =>
                    b.range !== a.range
                        ? b.range - a.range
                        : b.area - a.area
                );

            return candidates.length
                ? candidates[0].element
                : null;
        }
        """
    )

    scroller = handle.as_element()

    if scroller is None:
        raise RuntimeError(
            "Could not find the Owner SD scrollable list."
        )

    return scroller


def collect_visible_owner_values(
    scroller,
) -> list[str]:

    values = scroller.evaluate(
        """
        root => {
            const rootRect =
                root.getBoundingClientRect();

            const visible = element => {
                const rect =
                    element.getBoundingClientRect();

                const style =
                    window.getComputedStyle(element);

                return (
                    rect.width > 0 &&
                    rect.height > 0 &&
                    rect.bottom >= rootRect.top &&
                    rect.top <= rootRect.bottom &&
                    style.display !== "none" &&
                    style.visibility !== "hidden"
                );
            };

            const clean = value =>
                (value || "")
                    .replace(/\\s+/g, " ")
                    .trim();

            const results = [];

            const controls = Array.from(
                root.querySelectorAll(
                    "input[type='checkbox'], " +
                    "[role='checkbox'], " +
                    "[role='option'], " +
                    "[role='menuitemcheckbox']"
                )
            );

            for (const control of controls) {
                if (!visible(control)) {
                    continue;
                }

                let row = control;

                for (
                    let level = 0;
                    level < 5;
                    level += 1
                ) {
                    const parent =
                        row.parentElement;

                    if (
                        !parent ||
                        parent === root
                    ) {
                        break;
                    }

                    const rect =
                        parent.getBoundingClientRect();

                    if (
                        rect.height >= 20 &&
                        rect.height <= 70
                    ) {
                        row = parent;
                    } else {
                        break;
                    }
                }

                const text = clean(
                    row.innerText ||
                    row.textContent ||
                    control.getAttribute(
                        "aria-label"
                    )
                );

                if (
                    text &&
                    text.length <= 100 &&
                    !results.includes(text)
                ) {
                    results.push(text);
                }
            }

            /*
             * Fallback for Sisense versions where
             * checkboxes have no semantic attributes.
             */
            if (!results.length) {
                const leaves = Array.from(
                    root.querySelectorAll(
                        "span, label, div"
                    )
                ).filter(element =>
                    visible(element) &&
                    element.children.length === 0
                );

                for (const element of leaves) {
                    const text = clean(
                        element.innerText ||
                        element.textContent
                    );

                    if (
                        text &&
                        text.length <= 100 &&
                        !results.includes(text)
                    ) {
                        results.push(text);
                    }
                }
            }

            return results;
        }
        """
    )

    cleaned = []

    for value in values:
        value = re.sub(
            r"\s+",
            " ",
            value,
        ).strip()

        if not value:
            continue

        if value in IGNORED_OWNER_TEXTS:
            continue

        if value.lower().startswith(
            "include all"
        ):
            continue

        if value.lower().endswith(
            "selected"
        ):
            continue

        if value not in cleaned:
            cleaned.append(value)

    return cleaned


def discover_owner_sd_values(
    page: Page,
) -> list[str]:

    open_owner_sd_filter(page)

    dialog = find_owner_sd_dialog(page)
    scroller = find_owner_list_scroller(dialog)

    scroller.evaluate(
        "element => { element.scrollTop = 0; }"
    )

    page.wait_for_timeout(500)

    owners: list[str] = []
    previous_scroll_top = -1

    for _ in range(100):
        visible_values = (
            collect_visible_owner_values(
                scroller
            )
        )

        for value in visible_values:
            if value not in owners:
                owners.append(value)

        state = scroller.evaluate(
            """
            element => ({
                scrollTop:
                    element.scrollTop,
                clientHeight:
                    element.clientHeight,
                scrollHeight:
                    element.scrollHeight
            })
            """
        )

        at_bottom = (
            state["scrollTop"] +
            state["clientHeight"]
            >=
            state["scrollHeight"] - 5
        )

        if (
            at_bottom or
            state["scrollTop"] ==
            previous_scroll_top
        ):
            break

        previous_scroll_top = (
            state["scrollTop"]
        )

        scroller.evaluate(
            """
            element => {
                element.scrollTop = Math.min(
                    element.scrollTop +
                    Math.max(
                        element.clientHeight * 0.8,
                        120
                    ),
                    element.scrollHeight
                );
            }
            """
        )

        page.wait_for_timeout(500)

    page.keyboard.press("Escape")
    page.wait_for_timeout(800)

    if not owners:
        raise RuntimeError(
            "No Owner SD values were found."
        )

    print(
        f"Owner SD values found "
        f"({len(owners)}): {owners}"
    )

    return owners


def find_owner_option(
    dialog,
    owner_value: str,
):

    handle = dialog.evaluate_handle(
        """
        (root, requiredValue) => {
            const visible = element => {
                const rect =
                    element.getBoundingClientRect();

                const style =
                    window.getComputedStyle(element);

                return (
                    rect.width > 0 &&
                    rect.height > 0 &&
                    style.display !== "none" &&
                    style.visibility !== "hidden"
                );
            };

            const clean = value =>
                (value || "")
                    .replace(/\\s+/g, " ")
                    .trim();

            const matches = Array.from(
                root.querySelectorAll("*")
            )
                .filter(element =>
                    visible(element) &&
                    clean(
                        element.innerText ||
                        element.textContent ||
                        element.getAttribute(
                            "aria-label"
                        )
                    ) === requiredValue
                )
                .sort((a, b) => {
                    const aRect =
                        a.getBoundingClientRect();

                    const bRect =
                        b.getBoundingClientRect();

                    return (
                        aRect.width *
                        aRect.height
                    ) - (
                        bRect.width *
                        bRect.height
                    );
                });

            if (!matches.length) {
                return null;
            }

            const match = matches[0];
            let current = match;

            for (
                let level = 0;
                level < 5;
                level += 1
            ) {
                const parent =
                    current.parentElement;

                if (
                    !parent ||
                    parent === root
                ) {
                    break;
                }

                const rect =
                    parent.getBoundingClientRect();

                const hasCheckbox = Boolean(
                    parent.querySelector(
                        "input[type='checkbox'], " +
                        "[role='checkbox']"
                    )
                );

                if (
                    hasCheckbox &&
                    rect.height >= 20 &&
                    rect.height <= 80
                ) {
                    return parent;
                }

                current = parent;
            }

            return match;
        }
        """,
        owner_value,
    )

    return handle.as_element()


def option_is_selected(option) -> bool:
    return bool(
        option.evaluate(
            """
            element => {
                let current = element;

                for (
                    let level = 0;
                    level < 5 && current;
                    level += 1
                ) {
                    const checkbox =
                        current.matches(
                            "input[type='checkbox']"
                        )
                            ? current
                            : current.querySelector(
                                "input[type='checkbox']"
                            );

                    if (
                        checkbox &&
                        checkbox.checked
                    ) {
                        return true;
                    }

                    if (
                        current.getAttribute(
                            "aria-checked"
                        ) === "true"
                    ) {
                        return true;
                    }

                    if (
                        current.getAttribute(
                            "aria-selected"
                        ) === "true"
                    ) {
                        return true;
                    }

                    current =
                        current.parentElement;
                }

                return false;
            }
            """
        )
    )


def select_owner_sd(
    page: Page,
    owner_value: str,
) -> None:

    print(
        f'Selecting Owner SD '
        f'"{owner_value}".'
    )

    open_owner_sd_filter(page)

    dialog = find_owner_sd_dialog(page)

    search = dialog.query_selector(
        "input[placeholder*='Find'], "
        "input[placeholder*='Search'], "
        "input[type='search'], "
        "input[type='text']"
    )

    if (
        search is not None and
        search.is_visible()
    ):
        search.fill(owner_value)
        page.wait_for_timeout(1_200)

    option = find_owner_option(
        dialog,
        owner_value,
    )

    if option is None:
        raise RuntimeError(
            f'Could not find Owner SD '
            f'value "{owner_value}" '
            f'in the filter.'
        )

    if not option_is_selected(option):
        option.click()
        page.wait_for_timeout(700)

    apply_button = dialog.get_by_role(
        "button",
        name="Apply",
    )

    if apply_button.count() == 0:
        raise RuntimeError(
            "Could not find the Owner SD "
            "Apply button."
        )

    apply_button.click()

    page.wait_for_timeout(8_000)

    print(
        f'Owner SD "{owner_value}" applied.'
    )


# ============================================================
# Chart detection and screenshot
# ============================================================

def wait_for_chart(page: Page) -> None:
    page.wait_for_function(
        """
        () => Array.from(
            document.querySelectorAll("svg")
        ).some(svg => {
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
                text.includes(
                    "Total Call Duration"
                ) &&
                text.includes(
                    "Unique Customers"
                )
            );
        })
        """,
        timeout=90_000,
    )

    page.wait_for_timeout(3_000)


def screenshot_chart_only(
    page: Page,
    output_path: str,
) -> None:

    wait_for_chart(page)

    handle = page.evaluate_handle(
        """
        () => {
            const candidates = Array.from(
                document.querySelectorAll("svg")
            )
                .map(svg => {
                    const rect =
                        svg.getBoundingClientRect();

                    const style =
                        window.getComputedStyle(svg);

                    const text = (
                        svg.textContent || ""
                    )
                        .replace(/\\s+/g, " ")
                        .trim();

                    return {
                        svg: svg,
                        rect: rect,
                        style: style,
                        text: text,
                        area:
                            rect.width *
                            rect.height
                    };
                })
                .filter(item =>
                    item.rect.width > 700 &&
                    item.rect.height > 400 &&
                    item.rect.right > 0 &&
                    item.rect.bottom > 0 &&
                    item.style.display !== "none" &&
                    item.style.visibility !== "hidden" &&
                    item.text.includes(
                        "Total Call Duration"
                    ) &&
                    item.text.includes(
                        "Unique Customers"
                    )
                )
                .sort(
                    (a, b) =>
                        b.area - a.area
                );

            if (!candidates.length) {
                return null;
            }

            const chartSvg =
                candidates[0].svg;

            const svgRect =
                chartSvg.getBoundingClientRect();

            let selected = chartSvg;
            let current =
                chartSvg.parentElement;

            for (
                let level = 0;
                level < 8 && current;
                level += 1,
                current = current.parentElement
            ) {
                const rect =
                    current.getBoundingClientRect();

                const text = (
                    current.textContent || ""
                )
                    .replace(/\\s+/g, " ")
                    .trim();

                const reasonable =
                    rect.width >= svgRect.width &&
                    rect.height >= svgRect.height &&
                    rect.width -
                        svgRect.width <= 100 &&
                    rect.height -
                        svgRect.height <= 120;

                if (reasonable) {
                    selected = current;

                    if (
                        text.includes(
                            "Agent Call Display"
                        )
                    ) {
                        break;
                    }
                }
            }

            return selected;
        }
        """
    )

    chart = handle.as_element()

    if chart is None:
        raise RuntimeError(
            "Could not locate the "
            "chart container."
        )

    chart.screenshot(
        path=output_path,
    )

    print(
        f"Screenshot created: "
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

            owner_values = (
                discover_owner_sd_values(
                    page
                )
            )

            send_message(
                "SB Calls Monitor started. "
                f"Found {len(owner_values)} "
                "Owner SD values: "
                + ", ".join(owner_values)
            )

            for owner_value in owner_values:
                try:
                    # Reload the widget so every Owner SD
                    # starts from a clean page state.
                    open_widget(page)

                    select_owner_sd(
                        page,
                        owner_value,
                    )

                    screenshot_path = (
                        f"sb_calls_"
                        f"{safe_filename(owner_value)}"
                        f".png"
                    )

                    screenshot_chart_only(
                        page,
                        screenshot_path,
                    )

                    timestamp = (
                        datetime.now(
                            timezone.utc
                        ).strftime(
                            "%Y-%m-%d %H:%M UTC"
                        )
                    )

                    send_photo(
                        screenshot_path,
                        (
                            f"Owner SD: "
                            f"{owner_value}"
                            f" | SB Calls"
                            f" | {timestamp}"
                        ),
                    )

                except Exception as owner_error:
                    error_text = (
                        f'Failed for Owner SD '
                        f'"{owner_value}": '
                        f"{owner_error}"
                    )

                    print(error_text)

                    send_message(
                        error_text
                    )

        except Exception:
            try:
                page.screenshot(
                    path=(
                        "sb_calls_error_debug.png"
                    ),
                    full_page=True,
                )
            except Exception:
                pass

            raise

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
