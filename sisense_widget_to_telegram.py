import os
import sys
from datetime import datetime, timezone

import requests
from playwright.sync_api import Page, sync_playwright


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


def send_photo(photo_path: str, caption: str) -> None:
    """Send the chart image to Telegram."""

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

    print("Telegram photo sent successfully.")


def wait_for_chart(page: Page) -> None:
    """
    Wait for the Agent Call Display chart to render.

    The chart is identified by its two legend labels rather than simply
    selecting the first or largest SVG on the Sisense page.
    """

    print("Waiting for the Agent Call Display chart.")

    page.wait_for_function(
        """
        () => {
            const svgs = Array.from(document.querySelectorAll("svg"));

            return svgs.some(svg => {
                const rect = svg.getBoundingClientRect();
                const text = (svg.textContent || "")
                    .replace(/\\s+/g, " ")
                    .trim();

                const style = window.getComputedStyle(svg);

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

    # Allow final labels and animations to settle.
    page.wait_for_timeout(3_000)

    print("Agent Call Display chart found.")


def screenshot_chart_only(page: Page, output_path: str) -> None:
    """
    Screenshot only the actual chart container.

    This excludes:
    - Sisense navigation
    - left configuration panel
    - right design panel
    - Apply/Cancel buttons
    """

    wait_for_chart(page)

    chart_handle = page.evaluate_handle(
        """
        () => {
            const svgs = Array.from(document.querySelectorAll("svg"));

            const candidates = svgs
                .map(svg => {
                    const rect = svg.getBoundingClientRect();
                    const text = (svg.textContent || "")
                        .replace(/\\s+/g, " ")
                        .trim();

                    const style = window.getComputedStyle(svg);

                    let score = rect.width * rect.height;

                    if (text.includes("Total Call Duration")) {
                        score += 100000000;
                    }

                    if (text.includes("Unique Customers")) {
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

            /*
             * Start with the SVG itself. Then move upward through its
             * parents and choose the smallest parent that can include the
             * title without including the editor side panels.
             */
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

                    /*
                     * Stop once we find the small container that also
                     * contains the chart title.
                     */
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
        page.screenshot(
            path="sb_calls_chart_crop_debug.png",
            full_page=True,
        )

        raise RuntimeError(
            "Could not locate the Agent Call Display chart container."
        )

    box = chart_element.bounding_box()

    if box is None:
        raise RuntimeError(
            "The chart container was found but has no visible dimensions."
        )

    print(
        "Chart container:",
        {
            "x": round(box["x"], 2),
            "y": round(box["y"], 2),
            "width": round(box["width"], 2),
            "height": round(box["height"], 2),
        },
    )

    chart_element.screenshot(
        path=output_path,
    )

    print(f"Chart-only screenshot created: {output_path}")


def main() -> None:
    screenshot_path = "sb_calls_chart_only.png"

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
            print("Opening Sisense login page.")

            page.goto(
                LOGIN_URL,
                wait_until="domcontentloaded",
                timeout=120_000,
            )

            page.wait_for_timeout(3_000)

            print(f"Login page URL: {page.url}")

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

            print("Login button clicked.")

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
                    "Sisense login did not complete. "
                    "The browser is still on the login page."
                )

            print("Opening calls widget.")

            page.goto(
                WIDGET_URL,
                wait_until="domcontentloaded",
                timeout=120_000,
            )

            print(f"Widget URL after navigation: {page.url}")

            if "login" in page.url.lower():
                page.screenshot(
                    path="sb_calls_redirected_to_login.png",
                    full_page=True,
                )

                raise RuntimeError(
                    "Sisense redirected back to login after "
                    "opening the widget."
                )

            page.wait_for_timeout(10_000)

            screenshot_chart_only(
                page,
                screenshot_path,
            )

        except Exception:
            try:
                page.screenshot(
                    path="sb_calls_error_debug.png",
                    full_page=True,
                )

                print(
                    "Debug screenshot created: "
                    "sb_calls_error_debug.png"
                )
            except Exception:
                pass

            raise

        finally:
            context.close()
            browser.close()

    timestamp = datetime.now(timezone.utc).strftime(
        "%Y-%m-%d %H:%M UTC"
    )

    send_photo(
        screenshot_path,
        f"SB Calls chart-only test — {timestamp}",
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
