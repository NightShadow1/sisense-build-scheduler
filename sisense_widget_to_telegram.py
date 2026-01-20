import os
import sys
import requests
import pandas as pd
from io import StringIO
from datetime import datetime, timezone

BASE_URL = os.environ["SISENSE_BASE_URL"].rstrip("/")
USERNAME = os.environ["SISENSE_USER"]
PASSWORD = os.environ["SISENSE_PASS"]

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

DASHBOARD_ID = os.environ["DASHBOARD_ID"]
WIDGET_ID = os.environ["WIDGET_ID"]

def sisense_login() -> str:
    r = requests.post(
        f"{BASE_URL}/api/v1/authentication/login",
        json={"username": USERNAME, "password": PASSWORD},
        timeout=60,
    )
    r.raise_for_status()
    data = r.json()
    token = data.get("access_token") or data.get("token")
    if not token:
        raise RuntimeError(f"Login succeeded but token missing. Response: {data}")
    return token

def export_widget_csv(token: str) -> str:
    headers = {"Authorization": f"Bearer {token}"}

    # Try the most common export endpoints
    candidates = [
        f"{BASE_URL}/api/v1/dashboards/{DASHBOARD_ID}/widgets/{WIDGET_ID}/export/csv",
        f"{BASE_URL}/api/v1/widgets/{WIDGET_ID}/export/csv",
    ]

    last_err = None
    for url in candidates:
        try:
            r = requests.get(url, headers=headers, timeout=120)
            if r.status_code == 200 and len(r.text.strip()) > 0:
                return r.text
            last_err = f"{url} -> {r.status_code} {r.text[:200]}"
        except Exception as e:
            last_err = f"{url} -> {e}"

    raise RuntimeError(f"Could not export CSV. Last error: {last_err}")

def telegram_send_document(filename: str, content: str, caption: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
    files = {"document": (filename, content.encode("utf-8"), "text/csv")}
    data = {"chat_id": TELEGRAM_CHAT_ID, "caption": caption}
    r = requests.post(url, data=data, files=files, timeout=120)
    r.raise_for_status()

def telegram_send_message(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    r = requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": text}, timeout=60)
    r.raise_for_status()

def main():
    token = sisense_login()
    csv_text = export_widget_csv(token)

    # Send as CSV (most reliable)
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    caption = f"Last record table export ({now_utc})"
    telegram_send_document("sisense_last_records.csv", csv_text, caption)

    # Also send a short preview
    try:
        df = pd.read_csv(StringIO(csv_text))
        df_preview = df.head(25)
        preview = df_preview.to_string(index=False)
        if len(preview) > 3500:
            preview = preview[:3500] + "\n..."
        telegram_send_message(f"{caption}\n\n{preview}")
    except Exception:
        # If CSV format is unexpected, still succeed because document was sent
        telegram_send_message(f"{caption}\n\n(Preview unavailable, see CSV attachment.)")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
