import os
import re
import sys
from datetime import datetime, timezone
from typing import Optional

import requests
from playwright.sync_api import ElementHandle, Locator, Page, sync_playwright


BASE_URL = "https://projectanalytics.sisense.com"
DASHBOARD_ID = "6a4ec462193f10b9e24b4e05"

LOGIN_URL = f"{BASE_URL}/app/account/login?src={BASE_URL}/app/main"
DASHBOARD_URL = f"{BASE_URL}/app/main/dashboards/{DASHBOARD_ID}"

SISENSE_USER = os.environ["SISENSE_USER"]
SISENSE_PASS = os.environ["SISENSE_PASS"]
BOT_TOKEN = os.environ["SBCALLSM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

UI_TEXTS_TO_IGNORE = {
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


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def safe_filename(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_-]+", "_", value.strip())
    value = re.sub(r"_+", "_", value).strip("_")
    return value or "unknown_owner_sd"


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


def login_to_sisense(page: Page) -> None:
    print("Opening Sisense login page.")
    page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=120_000)
    page.wait_for_timeout(3_000)

    username = page.locator("input[placeholder='Username/Email']")
    password = page.locator("input[placeholder='Password']")

    username.wait_for(state="visible", timeout=30_000)
    username.fill(SISENSE_USER)
    password.fill(SISENSE_PASS)
    page.get_by_role("button", name="Login").click()

    try:
        page.wait_for_url("**/app/main/**", timeout=60_000)
    except Exception:
        page.wait_for_timeout(8_000)

    print(f"URL after login: {page.url}")
    if "login" in page.url.lower():
        raise RuntimeError("Sisense login did not complete.")


def visible_rightmost_exact_text(page: Page, text: str) -> Locator:
    candidates = page.get_by_text(text, exact=True)
    best: Optional[Locator] = None
    best_x = -1.0

    for index in range(candidates.count()):
        candidate = candidates.nth(index)
        try:
            if not candidate.is_visible():
                continue
            box = candidate.bounding_box()
            if box is None:
                continue
            if box["x"] > best_x:
                best = candidate
                best_x = box["x"]
        except Exception:
            continue

    if best is None:
        raise RuntimeError(f'Could not find visible text "{text}".')

    return best


def owner_dialog_is_open(page: Page) -> bool:
    search = page.locator("input[placeholder='Find in the list']")
    for index in range(search.count()):
        try:
            if search.nth(index).is_visible():
                return True
        except Exception:
            continue
    return False


def open_dashboard(page: Page) -> None:
    print("Opening Calls Monitor dashboard.")
    page.goto(DASHBOARD_URL, wait_until="domcontentloaded", timeout=120_000)

    if "login" in page.url.lower():
        raise RuntimeError("Sisense redirected back to the login page.")

    page.wait_for_function(
        """
        () => {
            const clean = value => (value || '').replace(/\\s+/g, ' ').trim();
            return Array.from(document.querySelectorAll('body *')).some(element => {
                const rect = element.getBoundingClientRect();
                const style = window.getComputedStyle(element);
                return (
                    rect.width > 0 &&
                    rect.height > 0 &&
                    rect.right > 0 &&
                    rect.bottom > 0 &&
                    style.display !== 'none' &&
                    style.visibility !== 'hidden' &&
                    clean(element.innerText || element.textContent) === 'Owner SD' &&
                    rect.left > window.innerWidth * 0.65
                );
            });
        }
        """,
        timeout=90_000,
    )
    page.wait_for_timeout(4_000)
    print(f"Dashboard URL: {page.url}")


def open_owner_sd_filter(page: Page) -> None:
    print("Opening Owner SD filter.")
    label = visible_rightmost_exact_text(page, "Owner SD")

    # Sisense normally renders the caption inside a clickable .f-header-host.
    # Try the label and its nearest ancestors one by one, and verify the popup
    # by the unique search input shown in the Owner SD dialog.
    attempts: list[Locator] = [label]
    current = label
    for _ in range(6):
        current = current.locator("xpath=..")
        attempts.append(current)

    for attempt_number, target in enumerate(attempts, start=1):
        try:
            tag_name = target.evaluate("el => el.tagName")
            class_name = target.evaluate("el => el.className || ''")
            print(
                f"Owner SD click attempt {attempt_number}: "
                f"tag={tag_name}, class={class_name}"
            )

            target.evaluate(
                """
                el => {
                    el.scrollIntoView({block: 'center', inline: 'center'});
                    el.dispatchEvent(new MouseEvent('mousedown', {
                        bubbles: true,
                        cancelable: true,
                        view: window
                    }));
                    el.dispatchEvent(new MouseEvent('mouseup', {
                        bubbles: true,
                        cancelable: true,
                        view: window
                    }));
                    el.click();
                }
                """
            )
            page.wait_for_timeout(1_500)
            if owner_dialog_is_open(page):
                print("Owner SD dialog opened.")
                return
        except Exception as error:
            print(f"Owner SD click attempt {attempt_number} failed: {error}")

    # Final fallback: click the centre of the visible Owner SD caption.
    box = label.bounding_box()
    if box is not None:
        page.mouse.click(
            box["x"] + box["width"] / 2,
            box["y"] + box["height"] / 2,
        )
        page.wait_for_timeout(2_000)
        if owner_dialog_is_open(page):
            print("Owner SD dialog opened by coordinate click.")
            return

    page.screenshot(path="owner_sd_open_failed.png", full_page=True)
    raise RuntimeError("Could not open the Owner SD filter dialog.")


def visible_owner_search_input(page: Page) -> Locator:
    inputs = page.locator("input[placeholder='Find in the list']")
    for index in range(inputs.count()):
        candidate = inputs.nth(index)
        try:
            if candidate.is_visible():
                return candidate
        except Exception:
            continue
    raise RuntimeError("Owner SD dialog search input was not found.")


def find_owner_sd_dialog(page: Page) -> ElementHandle:
    search_input = visible_owner_search_input(page)
    input_handle = search_input.element_handle()
    if input_handle is None:
        raise RuntimeError("Could not access the Owner SD search input.")

    handle = input_handle.evaluate_handle(
        """
        input => {
            const clean = value => (value || '').replace(/\\s+/g, ' ').trim();
            let current = input;
            const candidates = [];

            for (let level = 0; level < 16 && current; level += 1) {
                const rect = current.getBoundingClientRect();
                const text = clean(current.innerText || current.textContent);

                if (
                    rect.width > 350 &&
                    rect.height > 250 &&
                    text.includes('Owner SD') &&
                    text.includes('Apply') &&
                    text.includes('Cancel')
                ) {
                    candidates.push({
                        element: current,
                        area: rect.width * rect.height
                    });
                }
                current = current.parentElement;
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
        page.screenshot(path="owner_sd_dialog_not_found.png", full_page=True)
        raise RuntimeError("Could not identify the Owner SD filter dialog.")
    return dialog


def find_owner_list_scroller(dialog: ElementHandle) -> ElementHandle:
    handle = dialog.evaluate_handle(
        """
        root => {
            const candidates = Array.from(root.querySelectorAll('*'))
                .filter(element =>
                    element.scrollHeight > element.clientHeight + 10 &&
                    element.clientHeight >= 100 &&
                    element.clientWidth >= 180
                )
                .map(element => ({
                    element,
                    range: element.scrollHeight - element.clientHeight,
                    area: element.clientWidth * element.clientHeight
                }))
                .sort((a, b) => {
                    if (a.range !== b.range) return b.range - a.range;
                    return a.area - b.area;
                });

            return candidates.length ? candidates[0].element : null;
        }
        """
    )
    scroller = handle.as_element()
    if scroller is None:
        raise RuntimeError("Could not find the Owner SD values list.")
    return scroller


def clean_owner_values(values: list[str]) -> list[str]:
    result: list[str] = []
    for raw_value in values:
        value = clean_text(raw_value)
        if not value or value in UI_TEXTS_TO_IGNORE:
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


def collect_visible_owner_values(scroller: ElementHandle) -> list[str]:
    values = scroller.evaluate(
        """
        root => {
            const clean = value => (value || '').replace(/\\s+/g, ' ').trim();
            const rootRect = root.getBoundingClientRect();
            const visible = element => {
                const rect = element.getBoundingClientRect();
                const style = window.getComputedStyle(element);
                return (
                    rect.width > 0 &&
                    rect.height > 0 &&
                    rect.bottom >= rootRect.top &&
                    rect.top <= rootRect.bottom &&
                    style.display !== 'none' &&
                    style.visibility !== 'hidden'
                );
            };

            const result = [];
            const controls = Array.from(root.querySelectorAll(
                "input[type='checkbox'], [role='checkbox'], [role='option'], [role='menuitemcheckbox']"
            ));

            for (const control of controls) {
                if (!visible(control)) continue;
                let row = control;
                for (let level = 0; level < 5; level += 1) {
                    const parent = row.parentElement;
                    if (!parent || parent === root) break;
                    const rect = parent.getBoundingClientRect();
                    if (rect.height >= 18 && rect.height <= 70) {
                        row = parent;
                    } else {
                        break;
                    }
                }

                const text = clean(
                    row.innerText ||
                    row.textContent ||
                    control.getAttribute('aria-label')
                );
                if (text && text.length <= 100 && !result.includes(text)) {
                    result.push(text);
                }
            }

            if (!result.length) {
                const leaves = Array.from(root.querySelectorAll('span, label, div'))
                    .filter(element => visible(element) && element.children.length === 0);
                for (const element of leaves) {
                    const text = clean(element.innerText || element.textContent);
                    if (text && text.length <= 100 && !result.includes(text)) {
                        result.push(text);
                    }
                }
            }
            return result;
        }
        """
    )
    return clean_owner_values(values)


def click_exact_text_inside(root: ElementHandle, text: str) -> bool:
    return bool(
        root.evaluate(
            """
            (root, requiredText) => {
                const clean = value => (value || '').replace(/\\s+/g, ' ').trim();
                const visible = element => {
                    const rect = element.getBoundingClientRect();
                    const style = window.getComputedStyle(element);
                    return (
                        rect.width > 0 &&
                        rect.height > 0 &&
                        style.display !== 'none' &&
                        style.visibility !== 'hidden'
                    );
                };

                const matches = Array.from(root.querySelectorAll('*'))
                    .filter(element =>
                        visible(element) &&
                        clean(element.innerText || element.textContent) === requiredText
                    )
                    .sort((a, b) => {
                        const ar = a.getBoundingClientRect();
                        const br = b.getBoundingClientRect();
                        return ar.width * ar.height - br.width * br.height;
                    });

                if (!matches.length) return false;
                matches[0].click();
                return true;
            }
            """,
            text,
        )
    )


def discover_owner_sd_values(page: Page) -> list[str]:
    open_owner_sd_filter(page)
    dialog = find_owner_sd_dialog(page)
    scroller = find_owner_list_scroller(dialog)

    scroller.evaluate("element => { element.scrollTop = 0; }")
    page.wait_for_timeout(500)

    owners: list[str] = []
    previous_scroll_top = -1

    for _ in range(100):
        for value in collect_visible_owner_values(scroller):
            if value not in owners:
                owners.append(value)

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
            state["scrollTop"] + state["clientHeight"]
            >= state["scrollHeight"] - 5
        )
        if at_bottom or state["scrollTop"] == previous_scroll_top:
            break

        previous_scroll_top = state["scrollTop"]
        scroller.evaluate(
            """
            element => {
                element.scrollTop = Math.min(
                    element.scrollTop + Math.max(element.clientHeight * 0.8, 120),
                    element.scrollHeight
                );
            }
            """
        )
        page.wait_for_timeout(500)

    if not click_exact_text_inside(dialog, "Cancel"):
        page.keyboard.press("Escape")
    page.wait_for_timeout(1_000)

    owners = clean_owner_values(owners)
    if not owners:
        raise RuntimeError("No Owner SD values were discovered.")

    print(f"Owner SD values found ({len(owners)}): {owners}")
    return owners


def find_owner_option(dialog: ElementHandle, owner_value: str) -> Optional[ElementHandle]:
    handle = dialog.evaluate_handle(
        """
        (root, requiredValue) => {
            const clean = value => (value || '').replace(/\\s+/g, ' ').trim();
            const visible = element => {
                const rect = element.getBoundingClientRect();
                const style = window.getComputedStyle(element);
                return (
                    rect.width > 0 &&
                    rect.height > 0 &&
                    style.display !== 'none' &&
                    style.visibility !== 'hidden'
                );
            };

            const matches = Array.from(root.querySelectorAll('*'))
                .filter(element =>
                    visible(element) &&
                    clean(
                        element.innerText ||
                        element.textContent ||
                        element.getAttribute('aria-label')
                    ) === requiredValue
                )
                .sort((a, b) => {
                    const ar = a.getBoundingClientRect();
                    const br = b.getBoundingClientRect();
                    return ar.width * ar.height - br.width * br.height;
                });

            if (!matches.length) return null;
            let selected = matches[0];

            for (let level = 0; level < 6; level += 1) {
                const parent = selected.parentElement;
                if (!parent || parent === root) break;
                const rect = parent.getBoundingClientRect();
                const hasCheckbox = Boolean(parent.querySelector(
                    "input[type='checkbox'], [role='checkbox']"
                ));
                if (hasCheckbox && rect.height >= 18 && rect.height <= 90) {
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


def select_owner_sd(page: Page, owner_value: str) -> None:
    print(f'Selecting Owner SD "{owner_value}".')
    open_owner_sd_filter(page)
    dialog = find_owner_sd_dialog(page)

    click_exact_text_inside(dialog, "Clear All")
    page.wait_for_timeout(500)

    search = visible_owner_search_input(page)
    search.fill(owner_value)
    page.wait_for_timeout(1_200)

    option = find_owner_option(dialog, owner_value)
    if option is None:
        raise RuntimeError(f'Could not find Owner SD value "{owner_value}".')

    option.evaluate("el => el.click()")
    page.wait_for_timeout(700)

    if not click_exact_text_inside(dialog, "Apply"):
        raise RuntimeError("Could not find the Owner SD Apply control.")

    page.wait_for_timeout(10_000)
    print(f'Owner SD "{owner_value}" applied.')


def wait_for_chart(page: Page) -> None:
    page.wait_for_function(
        """
        () => Array.from(document.querySelectorAll('svg')).some(svg => {
            const rect = svg.getBoundingClientRect();
            const style = window.getComputedStyle(svg);
            const text = (svg.textContent || '').replace(/\\s+/g, ' ').trim();
            return (
                rect.width > 700 &&
                rect.height > 350 &&
                rect.right > 0 &&
                rect.bottom > 0 &&
                style.display !== 'none' &&
                style.visibility !== 'hidden' &&
                text.includes('Total Call Duration') &&
                text.includes('Unique Customers')
            );
        })
        """,
        timeout=90_000,
    )
    page.wait_for_timeout(3_000)


def screenshot_chart_only(page: Page, output_path: str) -> None:
    wait_for_chart(page)
    handle = page.evaluate_handle(
        """
        () => {
            const candidates = Array.from(document.querySelectorAll('svg'))
                .map(svg => {
                    const rect = svg.getBoundingClientRect();
                    const style = window.getComputedStyle(svg);
                    const text = (svg.textContent || '').replace(/\\s+/g, ' ').trim();
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
                    item.style.display !== 'none' &&
                    item.style.visibility !== 'hidden' &&
                    item.text.includes('Total Call Duration') &&
                    item.text.includes('Unique Customers')
                )
                .sort((a, b) => b.area - a.area);

            if (!candidates.length) return null;
            const chartSvg = candidates[0].svg;
            const svgRect = chartSvg.getBoundingClientRect();
            let selected = chartSvg;
            let current = chartSvg.parentElement;

            for (let level = 0; level < 10 && current; level += 1, current = current.parentElement) {
                const rect = current.getBoundingClientRect();
                const text = (current.textContent || '').replace(/\\s+/g, ' ').trim();
                const reasonable = (
                    rect.width >= svgRect.width &&
                    rect.height >= svgRect.height &&
                    rect.width - svgRect.width <= 120 &&
                    rect.height - svgRect.height <= 160
                );
                if (reasonable) {
                    selected = current;
                    if (text.includes('Agent Call Display')) break;
                }
            }
            return selected;
        }
        """
    )

    chart = handle.as_element()
    if chart is None:
        raise RuntimeError("Could not locate the Agent Call Display chart.")
    chart.screenshot(path=output_path)


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
            send_message(summary[:4000])

            for owner_value in owner_values:
                try:
                    open_dashboard(page)
                    select_owner_sd(page, owner_value)

                    screenshot_path = f"sb_calls_{safe_filename(owner_value)}.png"
                    screenshot_chart_only(page, screenshot_path)

                    timestamp = datetime.now(timezone.utc).strftime(
                        "%Y-%m-%d %H:%M UTC"
                    )
                    send_photo(
                        screenshot_path,
                        f"Owner SD: {owner_value} | SB Calls | {timestamp}",
                    )
                except Exception as owner_error:
                    error_text = (
                        f'Failed for Owner SD "{owner_value}": {owner_error}'
                    )
                    print(error_text)
                    send_message(error_text)

        except Exception as error:
            debug_path = "sb_calls_error_debug.png"
            try:
                page.screenshot(path=debug_path, full_page=True)
                send_photo(debug_path, f"SB Calls DEBUG: {error}")
            except Exception as debug_error:
                print(f"Could not send debug screenshot: {debug_error}")
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
