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
    """Send an image to Telegram."""

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


def wait_for_visible_chart(page: Page) -> None:
    """
    Wait until Sisense renders at least one large, visible SVG chart.

    We deliberately do not use wait_for_selector("svg"), because Sisense
    contains invisible SVG definitions with width and height equal to zero.
    """

    print("Waiting for a large visible chart SVG.")

    page.wait_for_function(
        """
        () => {
            const svgs = Array.from(document.querySelectorAll("svg"));

            return svgs.some(svg => {
                const rect = svg.getBoundingClientRect();
                const style = window.getComputedStyle(svg);

                const graphicalElements = svg.querySelectorAll(
                    "rect, path, circle, line, polyline, polygon, text"
                ).length;

                return (
                    rect.width > 500 &&
                    rect.height > 300 &&
                    rect.right > 0 &&
                    rect.bottom > 0 &&
                    style.display !== "none" &&
                    style.visibility !== "hidden" &&
                    Number(style.opacity || 1) > 0 &&
                    graphicalElements > 10
                );
            });
        }
        """,
        timeout=90_000,
    )

    print("Visible chart SVG found.")


def screenshot_chart_only(page: Page, output_path: str) -> None:
    """
    Capture only the chart region.

    The largest visible SVG is assumed to be the main chart. Padding is
    added to include the chart title, legend, axis labels and agent names.
    """

    wait_for_visible_chart(page)

    chart_box = page.evaluate(
        """
        () => {
            const candidates = Array.from(document.querySelectorAll("svg"))
                .map(svg => {
                    const rect = svg.getBoundingClientRect();
                    const style = window.getComputedStyle(svg);

                    const graphicalElements = svg.querySelectorAll(
                        "rect, path, circle, line, polyline, polygon, text"
                    ).length;

                    return {
                        x: rect.left + window.scrollX,
                        y: rect.top + window.scrollY,
                        width: rect.width,
                        height: rect.height,
                        area: rect.width * rect.height,
                        graphicalElements: graphicalElements,
                        display: style.display,
                        visibility: style.visibility,
                        opacity: Number(style.opacity || 1)
                    };
                })
                .filter(item =>
                    item.width > 500 &&
                    item.height > 300 &&
                    item.display !== "none" &&
                    item.visibility !== "hidden" &&
                    item.opacity > 0 &&
                    item.graphicalElements > 10
                )
                .sort((a, b) => b.area - a.area);

            if (candidates.length === 0) {
                return null;
            }

            const documentWidth = Math.max(
                document.documentElement.scrollWidth,
                document.body ? document.body.scrollWidth : 0
            );

            const documentHeight = Math.max(
                document.documentElement.scrollHeight,
                document.body ? document.body.scrollHeight : 0
            );

            return {
                chart: candidates[0],
                documentWidth: documentWidth,
                documentHeight: documentHeight
            };
        }
        """
    )

    if chart_box is None:
        page.screenshot(
            path="debug_no_visible_chart.png",
            full_page=True,
        )

        raise RuntimeError(
            "A visible Sisense chart could not be identified. "
            "A debug screenshot was created."
        )

    chart = chart_box["chart"]

    print(
        "Largest chart SVG:",
        {
            "x": chart["x"],
            "y": chart["y"],
            "width": chart["width"],
            "height": chart["height"],
        },
    )

    # Extra space around the SVG:
    # left   -> agent names
    # top    -> title and legend
    # right  -> value labels
    # bottom -> lower axis labels
    padding_left = 190
    padding_top = 125
    padding_right = 55
    padding_bottom = 70

    crop_x = max(chart["x"] - padding_left, 0)
    crop_y = max(chart["y"] - padding_top, 0)

    crop_right = min(
        chart["x"] + chart["width"] + padding_right,
        chart_box["documentWidth"],
    )

    crop_bottom = min(
        chart["y"] + chart["height"] + padding_bottom,
        chart_box["documentHeight"],
    )

    crop_width = crop_right - crop_x
    crop_height = crop_bottom - crop_y

    if crop_width <= 0 or crop_height <= 0:
        raise RuntimeError(
            "Calculated chart screenshot dimensions are invalid."
        )

    clip = {
        "x": crop_x,
        "y": crop_y,
        "width": crop_width,
        "height": crop_height,
    }

    print("Chart screenshot crop:", clip)

    page.screenshot(
        path=output_path,
        clip=clip,
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
                "height": 1000,
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
                # Sisense may navigate to /app/main/home without immediately
                # matching during SPA navigation, so verify the current URL.
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

            # Allow the Sisense widget application and query to initialise.
            page.wait_for_timeout(10_000)

            screenshot_chart_only(
                page,
                screenshot_path,
            )

        except Exception:
            # Useful diagnostic image when the GitHub workflow fails.
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
