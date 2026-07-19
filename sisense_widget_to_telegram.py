
import os
import re
import sys
from datetime import datetime, timezone
from typing import Optional

import requests
from playwright.sync_api import ElementHandle, Page, sync_playwright


BASE_URL = "https://projectanalytics.sisense.com"
DASHBOARD_ID = "6a4ec462193f10b9e24b4e05"

LOGIN_URL = f"{BASE_URL}/app/account/login?src={BASE_URL}/app/main"
DASHBOARD_URL = f"{BASE_URL}/app/main/dashboards/{DASHBOARD_ID}"

SISENSE_USER = os.environ["SISENSE_USER"]
SISENSE_PASS = os.environ["SISENSE_PASS"]
BOT_TOKEN = os.environ["SBCALLSM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]


IGNORED_TEXTS = {
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
    "No results",
    "Loading",
}


def send_message(text: str) -> None:
    response = requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        data={"chat_id": CHAT_ID, "text": text},
        timeout=180,
    )
    response.raise_for_status()


def send_photo(photo_path: str, caption: str) -> None:
    with open(photo_path, "rb") as photo:
        response = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
            data={"chat_id": CHAT_ID, "caption": caption},
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


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def safe_filename(value: str) -> str:
    filename = re.sub(r"[^A-Za-z0-9_-]+", "_", value.strip())
    filename = re.sub(r"_+", "_", filename).strip("_")
    return filename or "unknown_owner_sd"


def clean_owner_values(values: list[str]) -> list[str]:
    result: list[str] = []

    for raw_value in values:
        value = clean_text(raw_value)

        if not value:
            continue
        if value in IGNORED_TEXTS:
            continue
        if value.lower().startswith("include all"):
            continue
        if value.lower().endswith("selected"):
            continue
        if len(value) > 100:
            continue
        if value not in result:
            result.append(value)

    return result


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

    page.get_by_role("button", name="Login").click()

    try:
        page.wait_for_url("**/app/main/**", timeout=60_000)
    except Exception:
        page.wait_for_timeout(8_000)

    print(f"URL after login: {page.url}")

    if "login" in page.url.lower():
        page.screenshot(
            path="sb_calls_login_failed.png",
            full_page=True,
        )
        raise RuntimeError("Sisense login did not complete.")


def open_dashboard(page: Page) -> None:
    print("Opening Calls Monitor dashboard.")

    page.goto(
        DASHBOARD_URL,
        wait_until="domcontentloaded",
        timeout=120_000,
    )

    if "login" in page.url.lower():
        raise RuntimeError(
            "Sisense redirected back to the login page."
        )

    page.wait_for_function(
        """
        () => {
            const clean = value =>
                (value || "").replace(/\\s+/g, " ").trim();

            const visible = element => {
                const rect = element.getBoundingClientRect();
                const style = window.getComputedStyle(element);

                return (
                    rect.width > 0 &&
                    rect.height > 0 &&
                    rect.right > 0 &&
                    rect.bottom > 0 &&
                    style.display !== "none" &&
                    style.visibility !== "hidden"
                );
            };

            return Array.from(
                document.querySelectorAll("body *")
            ).some(element => {
                if (!visible(element)) {
                    return false;
                }

                const rect = element.getBoundingClientRect();
                const text = clean(
                    element.innerText ||
                    element.textContent
                );

                return (
                    text === "Owner SD" &&
                    rect.left > window.innerWidth * 0.70
                );
            });
        }
        """,
        timeout=90_000,
    )

    page.wait_for_timeout(4_000)
    print(f"Dashboard URL: {page.url}")


def click_owner_sd_filter(page: Page) -> None:
    print("Opening Owner SD filter.")

    clicked = page.evaluate(
        """
        () => {
            const clean = value =>
                (value || "").replace(/\\s+/g, " ").trim();

            const visible = element => {
                const rect = element.getBoundingClientRect();
                const style = window.getComputedStyle(element);

                return (
                    rect.width > 0 &&
                    rect.height > 0 &&
                    rect.right > 0 &&
                    rect.bottom > 0 &&
                    style.display !== "none" &&
                    style.visibility !== "hidden"
                );
            };

            const matches = Array.from(
                document.querySelectorAll("body *")
            ).filter(element => {
                if (!visible(element)) {
                    return false;
                }

                const rect = element.getBoundingClientRect();
                const text = clean(
                    element.innerText ||
                    element.textContent
                );

                return (
                    text === "Owner SD" &&
                    rect.left > window.innerWidth * 0.70
                );
            });

            if (!matches.length) {
                return false;
            }

            matches.sort((a, b) => {
                const aRect = a.getBoundingClientRect();
                const bRect = b.getBoundingClientRect();

                return (
                    aRect.width * aRect.height -
                    bRect.width * bRect.height
                );
            });

            let target = matches[0];
            let current = target;

            for (let level = 0; level < 6; level += 1) {
                const parent = current.parentElement;

                if (!parent) {
                    break;
                }

                const rect = parent.getBoundingClientRect();
                const text = clean(
                    parent.innerText ||
                    parent.textContent
                );

                if (
                    rect.width >= 150 &&
                    rect.width <= 500 &&
                    rect.height >= 30 &&
                    rect.height <= 180 &&
                    text.includes("Owner SD")
                ) {
                    target = parent;
                    current = parent;
                } else {
                    break;
                }
            }

            target.click();
            return true;
        }
        """
    )

    if not clicked:
        page.screenshot(
            path="owner_sd_filter_not_found.png",
            full_page=True,
        )
        raise RuntimeError(
            "Could not find Owner SD in the dashboard Filters panel."
        )

    page.wait_for_function(
        """
        () => {
            const clean = value =>
                (value || "").replace(/\\s+/g, " ").trim();

            return Array.from(
                document.querySelectorAll("body *")
            ).some(element => {
                const rect = element.getBoundingClientRect();
                const style = window.getComputedStyle(element);
                const text = clean(
                    element.innerText ||
                    element.textContent
                );

                return (
                    rect.width > 0 &&
                    rect.height > 0 &&
                    style.display !== "none" &&
                    style.visibility !== "hidden" &&
                    text === "Include all (no filter applied)"
                );
            });
        }
        """,
        timeout=20_000,
    )

    page.wait_for_timeout(1_000)


def find_owner_dialog(page: Page) -> ElementHandle:
    handle = page.evaluate_handle(
        """
        () => {
            const clean = value =>
                (value || "").replace(/\\s+/g, " ").trim();

            const visible = element => {
                const rect = element.getBoundingClientRect();
                const style = window.getComputedStyle(element);

                return (
                    rect.width > 0 &&
                    rect.height > 0 &&
                    rect.right > 0 &&
                    rect.bottom > 0 &&
                    style.display !== "none" &&
                    style.visibility !== "hidden"
                );
            };

            const anchors = Array.from(
                document.querySelectorAll("body *")
            ).filter(element =>
                visible(element) &&
                clean(
                    element.innerText ||
                    element.textContent
                ) === "Include all (no filter applied)"
            );

            const candidates = [];

            for (const anchor of anchors) {
                let current = anchor;

                for (
                    let level = 0;
                    level < 16 && current;
                    level += 1
                ) {
                    const rect =
                        current.getBoundingClientRect();

                    const text = clean(
                        current.innerText ||
                        current.textContent
                    );

                    if (
                        rect.width >= 500 &&
                        rect.height >= 400 &&
                        rect.width <= window.innerWidth &&
                        rect.height <= window.innerHeight &&
                        text.includes("Owner SD") &&
                        text.includes("Apply") &&
                        text.includes("Cancel")
                    ) {
                        candidates.push({
                            element: current,
                            area: rect.width * rect.height
                        });
                    }

                    current = current.parentElement;
                }
            }

            if (!candidates.length) {
                return null;
            }

            candidates.sort((a, b) => a.area - b.area);
            return candidates[0].element;
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


def find_owner_list_scroller(
    dialog: ElementHandle,
) -> ElementHandle:
    handle = dialog.evaluate_handle(
        """
        root => {
            const candidates = Array.from(
                root.querySelectorAll("*")
            )
                .filter(element =>
                    element.scrollHeight >
                        element.clientHeight + 20 &&
                    element.clientHeight >= 100 &&
                    element.clientWidth >= 180
                )
                .map(element => ({
                    element,
                    range:
                        element.scrollHeight -
                        element.clientHeight,
                    area:
                        element.clientWidth *
                        element.clientHeight
                }))
                .sort((a, b) => {
                    if (a.range !== b.range) {
                        return b.range - a.range;
                    }

                    return b.area - a.area;
                });

            return candidates.length
                ? candidates[0].element
                : null;
        }
        """
    )

    scroller = handle.as_element()

    if scroller is None:
        raise RuntimeError(
            "Could not find the Owner SD values list."
        )

    return scroller


def collect_visible_owner_values(
    scroller: ElementHandle,
) -> list[str]:
    values = scroller.evaluate(
        """
        root => {
            const rootRect = root.getBoundingClientRect();

            const clean = value =>
                (value || "").replace(/\\s+/g, " ").trim();

            const visible = element => {
                const rect = element.getBoundingClientRect();
                const style = window.getComputedStyle(element);

                return (
                    rect.width > 0 &&
                    rect.height > 0 &&
                    rect.bottom >= rootRect.top &&
                    rect.top <= rootRect.bottom &&
                    style.display !== "none" &&
                    style.visibility !== "hidden"
                );
            };

            const result = [];

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
                    const parent = row.parentElement;

                    if (!parent || parent === root) {
                        break;
                    }

                    const rect = parent.getBoundingClientRect();

                    if (
                        rect.height >= 18 &&
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
                    control.getAttribute("aria-label")
                );

                if (
                    text &&
                    text.length <= 100 &&
                    !result.includes(text)
                ) {
                    result.push(text);
                }
            }

            if (!result.length) {
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
                        !result.includes(text)
                    ) {
                        result.push(text);
                    }
                }
            }

            return result;
        }
        """
    )

    return clean_owner_values(values)


def click_text_inside(
    root: ElementHandle,
    required_text: str,
) -> None:
    clicked = root.evaluate(
        """
        (element, requiredText) => {
            const clean = value =>
                (value || "").replace(/\\s+/g, " ").trim();

            const matches = Array.from(
                element.querySelectorAll("*")
            ).filter(node =>
                clean(
                    node.innerText ||
                    node.textContent
                ) === requiredText
            );

            if (!matches.length) {
                return false;
            }

            matches.sort((a, b) => {
                const aRect = a.getBoundingClientRect();
                const bRect = b.getBoundingClientRect();

                return (
                    aRect.width * aRect.height -
                    bRect.width * bRect.height
                );
            });

            matches[0].click();
            return true;
        }
        """,
        required_text,
    )

    if not clicked:
        raise RuntimeError(
            f'Could not find "{required_text}" inside Owner SD dialog.'
        )


def discover_owner_sd_values(
    page: Page,
) -> list[str]:
    click_owner_sd_filter(page)

    dialog = find_owner_dialog(page)
    scroller = find_owner_list_scroller(dialog)

    scroller.evaluate(
        "element => { element.scrollTop = 0; }"
    )

    page.wait_for_timeout(700)

    owner_values: list[str] = []
    previous_scroll_top = -1

    for _ in range(100):
        for value in collect_visible_owner_values(scroller):
            if value not in owner_values:
                owner_values.append(value)

        state = scroller.evaluate(
            """
            element => ({
                scrollTop: element.scrollTop,
                clientHeight: element.clientHeight,
                scrollHeight: element.scrollHeight
            })
            """
        )

        at_bottom = (
            state["scrollTop"] +
            state["clientHeight"]
            >= state["scrollHeight"] - 5
        )

        if (
            at_bottom or
            state["scrollTop"] == previous_scroll_top
        ):
            break

        previous_scroll_top = state["scrollTop"]

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

        page.wait_for_timeout(600)

    click_text_inside(dialog, "Cancel")
    page.wait_for_timeout(1_000)

    owner_values = clean_owner_values(owner_values)

    if not owner_values:
        raise RuntimeError(
            "No Owner SD values were discovered."
        )

    print(
        f"Owner SD values found "
        f"({len(owner_values)}): {owner_values}"
    )

    return owner_values


def clear_owner_selection(dialog: ElementHandle) -> None:
    try:
        click_text_inside(dialog, "Clear All")
    except RuntimeError:
        dialog.evaluate(
            """
            root => {
                const controls = Array.from(
                    root.querySelectorAll(
                        "input[type='checkbox']"
                    )
                );

                for (const control of controls) {
                    if (control.checked) {
                        control.click();
                    }
                }
            }
            """
        )


def find_owner_option(
    dialog: ElementHandle,
    owner_value: str,
) -> Optional[ElementHandle]:
    handle = dialog.evaluate_handle(
        """
        (root, requiredValue) => {
            const clean = value =>
                (value || "").replace(/\\s+/g, " ").trim();

            const visible = element => {
                const rect = element.getBoundingClientRect();
                const style = window.getComputedStyle(element);

                return (
                    rect.width > 0 &&
                    rect.height > 0 &&
                    style.display !== "none" &&
                    style.visibility !== "hidden"
                );
            };

            const matches = Array.from(
                root.querySelectorAll("*")
            )
                .filter(element =>
                    visible(element) &&
                    clean(
                        element.innerText ||
                        element.textContent ||
                        element.getAttribute("aria-label")
                    ) === requiredValue
                )
                .sort((a, b) => {
                    const aRect =
                        a.getBoundingClientRect();

                    const bRect =
                        b.getBoundingClientRect();

                    return (
                        aRect.width * aRect.height -
                        bRect.width * bRect.height
                    );
                });

            if (!matches.length) {
                return null;
            }

            let selected = matches[0];

            for (
                let level = 0;
                level < 6;
                level += 1
            ) {
                const parent = selected.parentElement;

                if (!parent || parent === root) {
                    break;
                }

                const rect = parent.getBoundingClientRect();

                const hasCheckbox = Boolean(
                    parent.querySelector(
                        "input[type='checkbox'], " +
                        "[role='checkbox']"
                    )
                );

                if (
                    hasCheckbox &&
                    rect.height >= 18 &&
                    rect.height <= 90
                ) {
                    return parent;
                }

                selected = parent;
            }

            return matches[0];
        }
        """,
        owner_value,
    )

    return handle.as_element()


def select_owner_sd(
    page: Page,
    owner_value: str,
) -> None:
    print(f'Selecting Owner SD "{owner_value}".')

    click_owner_sd_filter(page)
    dialog = find_owner_dialog(page)

    clear_owner_selection(dialog)
    page.wait_for_timeout(500)

    search_input = dialog.query_selector(
        "input[placeholder*='Find'], "
        "input[placeholder*='Search'], "
        "input[type='search'], "
        "input[type='text']"
    )

    if search_input is not None and search_input.is_visible():
        search_input.fill(owner_value)
        page.wait_for_timeout(1_200)

    option = find_owner_option(dialog, owner_value)

    if option is None:
        page.screenshot(
            path=(
                "owner_sd_value_not_found_"
                f"{safe_filename(owner_value)}.png"
            ),
            full_page=True,
        )
        raise RuntimeError(
            f'Could not find Owner SD value "{owner_value}".'
        )

    option.evaluate("element => element.click()")
    page.wait_for_timeout(700)

    click_text_inside(dialog, "Apply")
    page.wait_for_timeout(10_000)

    print(f'Owner SD "{owner_value}" applied.')


def wait_for_chart(page: Page) -> None:
    page.wait_for_function(
        """
        () => Array.from(
            document.querySelectorAll("svg")
        ).some(svg => {
            const rect = svg.getBoundingClientRect();
            const style = window.getComputedStyle(svg);
            const text = (
                svg.textContent || ""
            ).replace(/\\s+/g, " ").trim();

            return (
                rect.width > 700 &&
                rect.height > 350 &&
                rect.right > 0 &&
                rect.bottom > 0 &&
                style.display !== "none" &&
                style.visibility !== "hidden" &&
                text.includes("Total Call Duration") &&
                text.includes("Unique Customers")
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
                    const rect = svg.getBoundingClientRect();
                    const style = window.getComputedStyle(svg);
                    const text = (
                        svg.textContent || ""
                    ).replace(/\\s+/g, " ").trim();

                    return {
                        svg,
                        rect,
                        style,
                        text,
                        area: rect.width * rect.height
                    };
                })
                .filter(item =>
                    item.rect.width > 700 &&
                    item.rect.height > 350 &&
                    item.rect.right > 0 &&
                    item.rect.bottom > 0 &&
                    item.style.display !== "none" &&
                    item.style.visibility !== "hidden" &&
                    item.text.includes("Total Call Duration") &&
                    item.text.includes("Unique Customers")
                )
                .sort((a, b) => b.area - a.area);

            if (!candidates.length) {
                return null;
            }

            const chartSvg = candidates[0].svg;
            const svgRect = chartSvg.getBoundingClientRect();

            let selected = chartSvg;
            let current = chartSvg.parentElement;

            for (
                let level = 0;
                level < 10 && current;
                level += 1,
                current = current.parentElement
            ) {
                const rect = current.getBoundingClientRect();
                const text = (
                    current.textContent || ""
                ).replace(/\\s+/g, " ").trim();

                const reasonable =
                    rect.width >= svgRect.width &&
                    rect.height >= svgRect.height &&
                    rect.width - svgRect.width <= 120 &&
                    rect.height - svgRect.height <= 160;

                if (reasonable) {
                    selected = current;

                    if (text.includes("Agent Call Display")) {
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
            "Could not locate the Agent Call Display chart."
        )

    chart.screenshot(path=output_path)
    print(f"Chart screenshot created: {output_path}")


def main() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)

        context = browser.new_context(
            viewport={"width": 1800, "height": 1100},
            device_scale_factor=1,
        )

        page = context.new_page()

        try:
            login_to_sisense(page)
            open_dashboard(page)

            owner_values = discover_owner_sd_values(page)

            summary = (
                "SB Calls Monitor started. "
                f"Found {len(owner_values)} Owner SD values: "
                + ", ".join(owner_values)
            )

            if len(summary) > 4000:
                summary = (
                    "SB Calls Monitor started. "
                    f"Found {len(owner_values)} Owner SD values."
                )

            send_message(summary)

            for owner_value in owner_values:
                try:
                    open_dashboard(page)
                    select_owner_sd(page, owner_value)

                    screenshot_path = (
                        f"sb_calls_"
                        f"{safe_filename(owner_value)}.png"
                    )

                    screenshot_chart_only(
                        page,
                        screenshot_path,
                    )

                    timestamp = datetime.now(
                        timezone.utc
                    ).strftime("%Y-%m-%d %H:%M UTC")

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
                        f'"{owner_value}": {owner_error}'
                    )
                    print(error_text)
                    send_message(error_text)

        except Exception:
            try:
                page.screenshot(
                    path="sb_calls_error_debug.png",
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
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
