import os
import sys
from datetime import datetime, timezone

import requests
from playwright.sync_api import sync_playwright


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
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"

    with open(photo_path, "rb") as photo:
        response = requests.post(
            url,
            data={
                "chat_id": CHAT_ID,
                "caption": caption,
            },
            files={"photo": photo},
            timeout=180,
        )

    response.raise_for_status()


def screenshot_chart_only(page, output_path: str) -> None:
    """
    Screenshots only the chart area, not the full Sisense editor/page.
    It finds the largest visible SVG chart and crops around it.
    """

    page.wait_for_selector("svg", timeout=60_000)

    chart_box = page.evaluate(
        """
        () => {
            const svgs = Array.from(document.querySelectorAll('svg'));

            const visibleSvgs = svgs
                .map(svg => {
                    const rect = svg.getBoundingClientRect();

                    return {
                        x: rect.x,
                        y: rect.y,
                        width: rect.width,
                        height: rect.height,
                        area: rect.width * rect.height
                    };
                })
                .filter(r =>
                    r.width > 400 &&
                    r.height > 300 &&
                    r.x >= 0 &&
                    r.y >= 0
                );

            if (visibleSvgs.length === 0) {
                return null;
            }

            visibleSvgs.sort((a, b) => b.area - a.area);

            return visibleSvgs[0];
        }
        """
    )

    if chart_box is None:
        page.screenshot(path="debug_no_chart_found.png", full_page=True)
        raise RuntimeError("Could not find the chart SVG to crop.")

    viewport = page.viewport_size

    if viewport is None:
        raise RuntimeError("Could not read browser viewport size.")

    # Padding around SVG so we include title, legend, labels, and axes.
    # Adjust these only if the crop is too tight / too wide.
    padding_left = 180
    padding_top = 125
    padding_right = 45
    padding_bottom = 70

    x = max(chart_box["x"] - padding_left, 0)
    y = max(chart_box["y"] - padding_top, 0)

    right = min(
        chart_box["x"] + chart_box["width"] + padding_right,
        viewport["width"],
    )

    bottom = min(
        chart_box["y"] + chart_box["height"] + padding_bottom,
        viewport["height"],
    )

    print(
        "Cropping chart:",
        {
            "x": x,
            "y": y,
            "width": right - x,
            "height": bottom - y,
        },
    )

    page.screenshot(
        path=output_path,
        clip={
            "x": x,
            "y": y,
            "width": right - x,
            "height": bottom - y,
        },
    )


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

        page.wait_for_timeout(15_000)

        print(f"Widget URL after navigation: {page.url}")

        if "login" in page.url.lower():
            page.screenshot(
                path="sb_calls_redirected_to_login.png",
                full_page=True,
            )

            raise RuntimeError(
                "Sisense redirected back to login "
                "after opening the widget."
            )

        screenshot_chart_only(
            page,
            screenshot_path,
        )

        browser.close()

    timestamp = datetime.now(timezone.utc).strftime(
        "%Y-%m-%d %H:%M UTC"
    )

    send_photo(
        screenshot_path,
        f"SB Calls chart only test — {timestamp}",
    )

    print("Chart screenshot sent successfully.")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
