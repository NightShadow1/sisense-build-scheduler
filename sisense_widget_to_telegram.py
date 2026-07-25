import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from playwright.sync_api import (
    Page,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)


# ============================================================
# Configuration
# ============================================================

BASE_URL = "https://projectanalytics.sisense.com"

LOGIN_URL = (
    f"{BASE_URL}/app/account/login"
    f"?src={BASE_URL}/app/main"
)

SISENSE_USER = os.environ["SISENSE_USER"]
SISENSE_PASS = os.environ["SISENSE_PASS"]

BOT_TOKEN = os.environ["SBCALLSM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

LOCAL_TIMEZONE = ZoneInfo("Europe/Belgrade")

OUTPUT_DIRECTORY = Path("sb_calls_output")

WIDGETS = [
    (
        "A - Team",
        "https://projectanalytics.sisense.com/app/main/dashboards/"
        "6a5cb824193f10b9e24b514f/widgets/6a5cb824193f10b9e24b5151",
    ),
    (
        "Abundance",
        "https://projectanalytics.sisense.com/app/main/dashboards/"
        "6a5cb824193f10b9e24b514f/widgets/6a5cb88c193f10b9e24b5162",
    ),
    (
        "Anony",
        "https://projectanalytics.sisense.com/app/main/dashboards/"
        "6a5cb824193f10b9e24b514f/widgets/6a5cb89d193f10b9e24b5167",
    ),
    (
        "Asli",
        "https://projectanalytics.sisense.com/app/main/dashboards/"
        "6a5cb824193f10b9e24b514f/widgets/6a5cb8b9193f10b9e24b516c",
    ),
    (
        "Cats",
        "https://projectanalytics.sisense.com/app/main/dashboards/"
        "6a5cb824193f10b9e24b514f/widgets/6a5cb8d7193f10b9e24b5173",
    ),
    (
        "Dixie",
        "https://projectanalytics.sisense.com/app/main/dashboards/"
        "6a5cb824193f10b9e24b514f/widgets/6a5cb8ef193f10b9e24b5178",
    ),
    (
        "Efroh",
        "https://projectanalytics.sisense.com/app/main/dashboards/"
        "6a5cb824193f10b9e24b514f/widgets/6a5cb904193f10b9e24b517d",
    ),
    (
        "Eternals",
        "https://projectanalytics.sisense.com/app/main/dashboards/"
        "6a5cb824193f10b9e24b514f/widgets/6a5cb91f193f10b9e24b5182",
    ),
    (
        "Exodus",
        "https://projectanalytics.sisense.com/app/main/dashboards/"
        "6a5cb824193f10b9e24b514f/widgets/6a5cb931193f10b9e24b5187",
    ),
    (
        "Genesis",
        "https://projectanalytics.sisense.com/app/main/dashboards/"
        "6a5cb824193f10b9e24b514f/widgets/6a5cb943193f10b9e24b518c",
    ),
    (
        "Goldminers",
        "https://projectanalytics.sisense.com/app/main/dashboards/"
        "6a5cb824193f10b9e24b514f/widgets/6a5cb95c193f10b9e24b5191",
    ),
    (
        "INZG NM",
        "https://projectanalytics.sisense.com/app/main/dashboards/"
        "6a5cb824193f10b9e24b514f/widgets/6a5cb96e193f10b9e24b5196",
    ),
    (
        "Leaos",
        "https://projectanalytics.sisense.com/app/main/dashboards/"
        "6a5cb824193f10b9e24b514f/widgets/6a5cbc99193f10b9e24b519b",
    ),
    (
        "Leviticus",
        "https://projectanalytics.sisense.com/app/main/dashboards/"
        "6a5cb824193f10b9e24b514f/widgets/6a5f906f193f10b9e24b52f8",
    ),
    (
        "MJ",
        "https://projectanalytics.sisense.com/app/main/dashboards/"
        "6a5cb824193f10b9e24b514f/widgets/6a5f908a193f10b9e24b52fe",
    ),
    (
        "New Stars",
        "https://projectanalytics.sisense.com/app/main/dashboards/"
        "6a5cb824193f10b9e24b514f/widgets/6a5f90ab193f10b9e24b5305",
    ),
    (
        "Orca",
        "https://projectanalytics.sisense.com/app/main/dashboards/"
        "6a5cb824193f10b9e24b514f/widgets/6a5f90c5193f10b9e24b530a",
    ),
    (
        "Pear",
        "https://projectanalytics.sisense.com/app/main/dashboards/"
        "6a5cb824193f10b9e24b514f/widgets/6a5f90dd193f10b9e24b530f",
    ),
    (
        "Piazza",
        "https://projectanalytics.sisense.com/app/main/dashboards/"
        "6a5cb824193f10b9e24b514f/widgets/6a5f90f3193f10b9e24b5314",
    ),
    (
        "Rising Stars",
        "https://projectanalytics.sisense.com/app/main/dashboards/"
        "6a5cb824193f10b9e24b514f/widgets/6a5f911f193f10b9e24b531f",
    ),
    (
        "Sheva NM",
        "https://projectanalytics.sisense.com/app/main/dashboards/"
        "6a5cb824193f10b9e24b514f/widgets/6a5f913c193f10b9e24b5325",
    ),
    (
        "Shiny",
        "https://projectanalytics.sisense.com/app/main/dashboards/"
        "6a5cb824193f10b9e24b514f/widgets/6a5f90fd193f10b9e24b5316",
    ),
    (
        "The Legends",
        "https://projectanalytics.sisense.com/app/main/dashboards/"
        "6a5cb824193f10b9e24b514f/widgets/6a5f9171193f10b9e24b532d",
    ),
    (
        "TMinds",
        "https://projectanalytics.sisense.com/app/main/dashboards/"
        "6a5cb824193f10b9e24b514f/widgets/6a5f9188193f10b9e24b5332",
    ),
    (
        "Tuzan",
        "https://projectanalytics.sisense.com/app/main/dashboards/"
        "6a5cb824193f10b9e24b514f/widgets/6a5f9105193f10b9e24b5319",
    ),
    (
        "Twisted Minds",
        "https://projectanalytics.sisense.com/app/main/dashboards/"
        "6a5cb824193f10b9e24b514f/widgets/6a5f91b0193f10b9e24b533a",
    ),
    (
        "Warriors",
        "https://projectanalytics.sisense.com/app/main/dashboards/"
        "6a5cb824193f10b9e24b514f/widgets/6a5f91c3193f10b9e24b533f",
    ),
    (
        "Wolves",
        "https://projectanalytics.sisense.com/app/main/dashboards/"
        "6a5cb824193f10b9e24b514f/widgets/6a5f91d5193f10b9e24b5344",
    ),
    (
        "Yazza",
        "https://projectanalytics.sisense.com/app/main/dashboards/"
        "6a5cb824193f10b9e24b514f/widgets/6a5f91ef193f10b9e24b5349",
    ),
]


# ============================================================
# Telegram
# ============================================================

def send_photo(
    photo_path: Path,
    caption: str,
) -> None:
    with photo_path.open("rb") as photo:
        response = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
            data={
                "chat_id": CHAT_ID,
                "caption": caption,
            },
            files={
                "photo": (
                    photo_path.name,
                    photo,
                    "image/png",
                )
            },
            timeout=180,
        )

    response.raise_for_status()

    print(
        f"Telegram photo sent: "
        f"{photo_path.name}"
    )


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
# Sisense login
# ============================================================

def login_to_sisense(page: Page) -> None:
    print("Opening Sisense login page.")

    page.goto(
        LOGIN_URL,
        wait_until="domcontentloaded",
        timeout=120_000,
    )

    page.wait_for_timeout(3_000)

    if "login" not in page.url.lower():
        print(
            f"Already authenticated: "
            f"{page.url}"
        )
        return

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
    except PlaywrightTimeoutError:
        page.wait_for_timeout(8_000)

    print(
        f"URL after login: "
        f"{page.url}"
    )

    if "login" in page.url.lower():
        raise RuntimeError(
            "Sisense login did not complete."
        )


# ============================================================
# Widget loading and inspection
# ============================================================

def inspect_widget(page: Page) -> dict:
    return page.evaluate(
        """
        () => {
            const clean = value =>
                (value || "")
                    .replace(/\\s+/g, " ")
                    .trim();

            const lower = value =>
                clean(value).toLowerCase();

            const visible = element => {
                const rect =
                    element.getBoundingClientRect();

                const style =
                    window.getComputedStyle(element);

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

            const noDataPhrases = [
                "no results",
                "no data",
                "nothing to display",
                "no items to display",
                "query returned no results"
            ];

            const noDataText = Array.from(
                document.querySelectorAll("body *")
            )
                .filter(visible)
                .map(element =>
                    lower(
                        element.innerText ||
                        element.textContent
                    )
                )
                .find(text =>
                    noDataPhrases.some(
                        phrase =>
                            text === phrase ||
                            text.includes(phrase)
                    )
                ) || null;

            const chartCandidates = Array.from(
                document.querySelectorAll("svg")
            )
                .filter(visible)
                .map(svg => {
                    const rect =
                        svg.getBoundingClientRect();

                    const text =
                        lower(svg.textContent || "");

                    let score =
                        rect.width * rect.height;

                    if (
                        text.includes(
                            "total call duration"
                        )
                    ) {
                        score += 100000000;
                    }

                    if (
                        text.includes(
                            "unique customers"
                        )
                    ) {
                        score += 100000000;
                    }

                    return {
                        svg,
                        rect,
                        score
                    };
                })
                .filter(item =>
                    item.rect.width > 600 &&
                    item.rect.height > 300
                )
                .sort(
                    (a, b) =>
                        b.score - a.score
                );

            if (!chartCandidates.length) {
                return {
                    ready: Boolean(noDataText),
                    chartFound: false,
                    hasData: false,
                    noDataText,
                    barCount: 0,
                    pointCount: 0,
                    categoryCount: 0
                };
            }

            const chart =
                chartCandidates[0].svg;

            const chartRect =
                chart.getBoundingClientRect();

            const excludedFills = new Set([
                "",
                "none",
                "transparent",
                "rgba(0, 0, 0, 0)",
                "rgb(255, 255, 255)",
                "white"
            ]);

            const barCount = Array.from(
                chart.querySelectorAll("rect")
            ).filter(rectangle => {
                if (!visible(rectangle)) {
                    return false;
                }

                const rect =
                    rectangle.getBoundingClientRect();

                const style =
                    window.getComputedStyle(rectangle);

                const fill = lower(
                    style.fill ||
                    rectangle.getAttribute("fill") ||
                    ""
                );

                const opacity = Number(
                    style.opacity || 1
                );

                const centreY =
                    rect.top +
                    rect.height / 2;

                const insidePlotArea =
                    centreY >
                    chartRect.top +
                    chartRect.height * 0.10;

                const isBackground =
                    rect.width >=
                        chartRect.width * 0.90 &&
                    rect.height >=
                        chartRect.height * 0.75;

                return (
                    rect.width >= 15 &&
                    rect.height >= 8 &&
                    rect.height <= 120 &&
                    opacity > 0.05 &&
                    insidePlotArea &&
                    !excludedFills.has(fill) &&
                    !isBackground
                );
            }).length;

            const pointCount = Array.from(
                chart.querySelectorAll("circle")
            ).filter(circle => {
                if (!visible(circle)) {
                    return false;
                }

                const rect =
                    circle.getBoundingClientRect();

                const style =
                    window.getComputedStyle(circle);

                const fill = lower(
                    style.fill ||
                    circle.getAttribute("fill") ||
                    ""
                );

                const centreY =
                    rect.top +
                    rect.height / 2;

                return (
                    rect.width >= 4 &&
                    rect.width <= 50 &&
                    rect.height >= 4 &&
                    rect.height <= 50 &&
                    centreY >
                        chartRect.top +
                        chartRect.height * 0.10 &&
                    !excludedFills.has(fill)
                );
            }).length;

            const ignoredLabels = new Set([
                "agent call display",
                "agent",
                "total call duration [hours]",
                "total call duration[hours]",
                "unique customers",
                "powered by sisense"
            ]);

            const categoryCount = Array.from(
                chart.querySelectorAll("text")
            )
                .filter(visible)
                .map(element => ({
                    text: lower(
                        element.textContent || ""
                    ),
                    rect:
                        element.getBoundingClientRect()
                }))
                .filter(item => {
                    if (!item.text) {
                        return false;
                    }

                    if (
                        ignoredLabels.has(item.text)
                    ) {
                        return false;
                    }

                    if (
                        /^[-+]?[0-9.,:%]+$/.test(
                            item.text
                        )
                    ) {
                        return false;
                    }

                    return (
                        item.rect.top >
                        chartRect.top +
                        chartRect.height * 0.10
                    );
                }).length;

            return {
                ready: true,
                chartFound: true,
                hasData:
                    !noDataText &&
                    (
                        barCount > 0 ||
                        pointCount > 0 ||
                        categoryCount > 0
                    ),
                noDataText,
                barCount,
                pointCount,
                categoryCount
            };
        }
        """
    )


def wait_for_widget(
    page: Page,
    owner_name: str,
    timeout_seconds: int = 90,
) -> dict:
    deadline = (
        time.monotonic() +
        timeout_seconds
    )

    last_state: dict = {
        "ready": False,
        "chartFound": False,
        "hasData": False,
        "noDataText": None,
        "barCount": 0,
        "pointCount": 0,
        "categoryCount": 0,
    }

    while time.monotonic() < deadline:
        last_state = inspect_widget(page)

        if last_state["ready"]:
            # Let Sisense finish labels and animation.
            page.wait_for_timeout(4_000)

            return inspect_widget(page)

        page.wait_for_timeout(1_000)

    raise RuntimeError(
        f'Widget for "{owner_name}" '
        "did not finish rendering. "
        f"Last state: {last_state}"
    )


def open_widget(
    page: Page,
    owner_name: str,
    widget_url: str,
) -> dict:
    print(
        f'Opening widget for '
        f'"{owner_name}".'
    )

    page.goto(
        widget_url,
        wait_until="domcontentloaded",
        timeout=120_000,
    )

    if "login" in page.url.lower():
        print(
            "Sisense session expired. "
            "Logging in again."
        )

        login_to_sisense(page)

        page.goto(
            widget_url,
            wait_until="domcontentloaded",
            timeout=120_000,
        )

    state = wait_for_widget(
        page,
        owner_name,
    )

    print(
        f'{owner_name}: '
        f'chart={state["chartFound"]}, '
        f'bars={state["barCount"]}, '
        f'points={state["pointCount"]}, '
        f'categories={state["categoryCount"]}, '
        f'noData={state["noDataText"]!r}, '
        f'hasData={state["hasData"]}'
    )

    return state


# ============================================================
# Chart-only screenshot
# ============================================================

def find_chart_element(page: Page):
    handle = page.evaluate_handle(
        """
        () => {
            const clean = value =>
                (value || "")
                    .replace(/\\s+/g, " ")
                    .trim()
                    .toLowerCase();

            const visible = element => {
                const rect =
                    element.getBoundingClientRect();

                const style =
                    window.getComputedStyle(element);

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

            const candidates = Array.from(
                document.querySelectorAll("svg")
            )
                .filter(visible)
                .map(svg => {
                    const rect =
                        svg.getBoundingClientRect();

                    const text =
                        clean(svg.textContent || "");

                    let score =
                        rect.width * rect.height;

                    if (
                        text.includes(
                            "total call duration"
                        )
                    ) {
                        score += 100000000;
                    }

                    if (
                        text.includes(
                            "unique customers"
                        )
                    ) {
                        score += 100000000;
                    }

                    return {
                        svg,
                        rect,
                        score
                    };
                })
                .filter(item =>
                    item.rect.width > 600 &&
                    item.rect.height > 300
                )
                .sort(
                    (a, b) =>
                        b.score - a.score
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
                level < 10 && current;
                level += 1,
                current =
                    current.parentElement
            ) {
                const rect =
                    current.getBoundingClientRect();

                const text =
                    clean(
                        current.textContent || ""
                    );

                const reasonable =
                    rect.width >=
                        svgRect.width &&
                    rect.height >=
                        svgRect.height &&
                    rect.width -
                        svgRect.width <= 120 &&
                    rect.height -
                        svgRect.height <= 180;

                if (reasonable) {
                    selected = current;

                    if (
                        text.includes(
                            "agent call display"
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

    return handle.as_element()


def screenshot_chart_only(
    page: Page,
    output_path: Path,
) -> None:
    chart = find_chart_element(page)

    if chart is None:
        raise RuntimeError(
            "Could not locate the chart container."
        )

    chart.screenshot(
        path=str(output_path),
    )

    print(
        f"Chart screenshot created: "
        f"{output_path.name}"
    )


# ============================================================
# Per-widget processing
# ============================================================

def process_widget(
    context,
    owner_name: str,
    widget_url: str,
) -> str:
    last_error: Exception | None = None

    for attempt in range(1, 3):
        page = context.new_page()

        try:
            print(
                f'Processing "{owner_name}" '
                f"(attempt {attempt}/2)."
            )

            state = open_widget(
                page,
                owner_name,
                widget_url,
            )

            if not state["hasData"]:
                print(
                    f'Skipping "{owner_name}": '
                    "the widget has no rendered data."
                )

                return "skipped"

            screenshot_path = (
                OUTPUT_DIRECTORY /
                (
                    "sb_calls_"
                    f"{safe_filename(owner_name)}"
                    ".png"
                )
            )

            screenshot_chart_only(
                page,
                screenshot_path,
            )

            run_time = datetime.now(
                LOCAL_TIMEZONE
            ).strftime(
                "%Y-%m-%d %H:%M"
            )

            send_photo(
                screenshot_path,
                (
                    f"Owner SD: {owner_name}"
                    f" | Yesterday"
                    f" | Sent: {run_time}"
                ),
            )

            return "sent"

        except Exception as error:
            last_error = error

            print(
                f'Attempt {attempt} failed '
                f'for "{owner_name}": '
                f"{error}",
                file=sys.stderr,
            )

            debug_path = (
                OUTPUT_DIRECTORY /
                (
                    "debug_"
                    f"{safe_filename(owner_name)}"
                    f"_attempt_{attempt}.png"
                )
            )

            try:
                page.screenshot(
                    path=str(debug_path),
                    full_page=True,
                )
            except Exception:
                pass

        finally:
            page.close()

    raise RuntimeError(
        f'Widget "{owner_name}" failed '
        f"after two attempts: {last_error}"
    )


# ============================================================
# Main
# ============================================================

def main() -> None:
    OUTPUT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    sent_count = 0
    skipped_count = 0
    failed_count = 0

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

        login_page = context.new_page()

        try:
            login_to_sisense(
                login_page
            )
        finally:
            login_page.close()

        try:
            for owner_name, widget_url in WIDGETS:
                try:
                    result = process_widget(
                        context,
                        owner_name,
                        widget_url,
                    )

                    if result == "sent":
                        sent_count += 1
                    else:
                        skipped_count += 1

                except Exception as error:
                    failed_count += 1

                    print(
                        f'ERROR for "{owner_name}": '
                        f"{error}",
                        file=sys.stderr,
                    )

        finally:
            context.close()
            browser.close()

    print(
        "Completed. "
        f"Sent: {sent_count}; "
        f"Empty/skipped: {skipped_count}; "
        f"Failed: {failed_count}."
    )

    if failed_count == len(WIDGETS):
        raise RuntimeError(
            "All widget checks failed."
        )


if __name__ == "__main__":
    try:
        main()

    except Exception as error:
        print(
            f"FATAL ERROR: {error}",
            file=sys.stderr,
        )

        sys.exit(1)
