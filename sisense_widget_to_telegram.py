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


def main() -> None:
    screenshot_path = "sb_calls_widget_test.png"

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
        )

        context = browser.new_context(
            viewport={
                "width": 1800,
                "height": 1000,
            },
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

        page.screenshot(
            path=screenshot_path,
            full_page=True,
        )

        browser.close()

    timestamp = datetime.now(timezone.utc).strftime(
        "%Y-%m-%d %H:%M UTC"
    )

    send_photo(
        screenshot_path,
        f"SB Calls widget login test — {timestamp}",
    )

    print("Widget screenshot sent successfully.")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
