import os
import sys
import json
import requests
import pandas as pd
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
        raise RuntimeError(f"Login ok but token missing: {data}")
    return token

def try_get_json(url: str, headers: dict):
    r = requests.get(url, headers=headers, timeout=120)
    if r.status_code == 200:
        ct = r.headers.get("Content-Type","")
        if "application/json" in ct or r.text.strip().startswith("{") or r.text.strip().startswith("["):
            return r.json()
    return None, (r.status_code, r.text[:300])

def fetch_widget_table_as_df(token: str) -> pd.DataFrame:
    headers = {"Authorization": f"Bearer {token}"}

    # 1) Get widget definition from dashboard (often contains "metadata"/"data" query)
    candidates = [
        f"{BASE_URL}/api/v1/dashboards/{DASHBOARD_ID}",
        f"{BASE_URL}/api/v1/dashboards/{DASHBOARD_ID}/widgets",
        f"{BASE_URL}/api/v1/dashboards/{DASHBOARD_ID}/widgets/{WIDGET_ID}",
        f"{BASE_URL}/api/v1/widgets/{WIDGET_ID}",
    ]

    last = None
    payload = None
    for url in candidates:
        try:
            r = requests.get(url, headers=headers, timeout=120)
            if r.status_code == 200:
                payload = r.json()
                last = (url, r.status_code, "OK")
                break
            last = (url, r.status_code, r.text[:200])
        except Exception as e:
            last = (url, "ERR", str(e))

    if payload is None:
        raise RuntimeError(f"Could not fetch widget/dashboard JSON. Last: {last}")

    # 2) Try to locate tabular data inside payload directly (some endpoints include it)
    # We try common shapes: payload["data"], payload["metadata"], payload["result"], etc.
    def find_rows_cols(obj):
        if isinstance(obj, dict):
            # common Sisense-like structures
            if "data" in obj and isinstance(obj["data"], (list, dict)):
                return obj["data"]
            if "result" in obj and isinstance(obj["result"], (list, dict)):
                return obj["result"]
        return None

    direct = find_rows_cols(payload)

    # If "direct" isn't usable, we’ll attempt common "query/data" endpoints
    # that the UI typically calls after loading widget metadata.
    data_endpoints = [
        # commonly used for widget data in some Sisense versions
        f"{BASE_URL}/api/v1/dashboards/{DASHBOARD_ID}/widgets/{WIDGET_ID}/data",
        f"{BASE_URL}/api/v1/widgets/{WIDGET_ID}/data",
        f"{BASE_URL}/api/v1/dashboards/{DASHBOARD_ID}/widgets/{WIDGET_ID}/pivot",
        f"{BASE_URL}/api/v1/widgets/{WIDGET_ID}/pivot",
    ]

    data_json = None
    last_data_err = None
    for url in data_endpoints:
        try:
            r = requests.get(url, headers=headers, timeout=120)
            if r.status_code == 200:
                data_json = r.json()
                break
            last_data_err = f"{url} -> {r.status_code} {r.text[:200]}"
        except Exception as e:
            last_data_err = f"{url} -> {e}"

    if data_json is None and direct is None:
        raise RuntimeError(
            "Could not fetch widget data. "
            f"Widget/dashboard JSON fetched from: {last}. "
            f"Data endpoints last error: {last_data_err}"
        )

    # 3) Convert whatever we got to a DataFrame
    # We support a few common shapes:
    source = data_json if data_json is not None else direct

    # If it already looks like list of dict rows:
    if isinstance(source, list) and len(source) > 0 and isinstance(source[0], dict):
        return pd.DataFrame(source)

    # If it’s a dict with headers/rows:
    if isinstance(source, dict):
        # ex: {"headers":[...], "rows":[[...],[...]]}
        headers_list = source.get("headers") or source.get("columns")
        rows_list = source.get("rows") or source.get("data")
        if isinstance(headers_list, list) and isinstance(rows_list, list) and len(rows_list) > 0:
            # headers might be list of dicts or strings
            if isinstance(headers_list[0], dict):
                cols = [h.get("title") or h.get("name") or h.get("field") for h in headers_list]
            else:
                cols = headers_list
            return pd.DataFrame(rows_list, columns=cols)

    # last resort: dump json to telegram as file
    raise RuntimeError("Fetched data but could not parse into a table shape.")

def telegram_send_message(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    r = requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": text}, timeout=60)
    r.raise_for_status()

def telegram_send_document(filename: str, content_bytes: bytes, caption: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
    files = {"document": (filename, content_bytes)}
    data = {"chat_id": TELEGRAM_CHAT_ID, "caption": caption}
    r = requests.post(url, data=data, files=files, timeout=120)
    r.raise_for_status()

def main():
    token = sisense_login()
    df = fetch_widget_table_as_df(token)

    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    caption = f"Sisense Last Record Table ({now_utc})"

    # Send CSV
    csv_bytes = df.to_csv(index=False).encode("utf-8")
    telegram_send_document("sisense_last_records.csv", csv_bytes, caption)

    # Send short preview
    preview_df = df.head(25)
    preview = preview_df.to_string(index=False)
    if len(preview) > 3500:
        preview = preview[:3500] + "\n..."
    telegram_send_message(f"{caption}\n\n{preview}")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
