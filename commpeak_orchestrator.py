import os
import time
import requests

# ============================================
# CONFIG
# ============================================

BASE_URL = "https://projectanalytics.sisense.com"

USERNAME = os.environ["SISENSE_USER"]
PASSWORD = os.environ["SISENSE_PASS"]

# Telegram config (optional – if not set, script just logs to console)
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Cube definitions
CUBE1 = {
    "id": "5ccf6f64-1d56-47dd-b00a-448617603dcf",
    "name": "Commpeak Calls",
    "buildType": "full",       # fetch new 500-row chunks from API
}

CUBE2 = {
    "id": "bf49122f-4abf-4b30-8a71-c52e8f613b00",
    "name": "Commpeak",
    "buildType": "by_table",   # 👈 incremental / accumulative build
}

CUBE3 = {
    "id": "4d35c342-d629-4047-be5c-259e73ede3c6",
    "name": "Commpeak Sites Employees",
    "buildType": "full",
}

CUBE4 = {
    "id": "3d2750f8-a0d5-4606-a0e2-1dd5de4fd6ec",
    "name": "CallsCombined",
    "buildType": "full",
}

POLL_INTERVAL_SECONDS = 30
BUILD_TIMEOUT_MINUTES = 60

# Configurable via env; default 5 for steady-state.
MAX_LOOPS_PER_RUN = int(os.getenv("MAX_LOOPS_PER_RUN", "5"))

SUCCESS_STATUSES = {"SUCCEEDED", "SUCCESS", "DONE", "COMPLETED"}


# ============================================
# TELEGRAM HELPER
# ============================================

def send_telegram_message(text: str):
    """
    Send a message to Telegram, if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are set.
    Otherwise just print what would have been sent.
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"[Telegram] Not configured, would send: {text}")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
    }

    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code >= 300:
            print(f"[Telegram] Error {resp.status_code}: {resp.text}")
        else:
            print("[Telegram] Notification sent.")
    except Exception as e:
        print(f"[Telegram] Exception while sending message: {e}")


# ============================================
# SISENSE HELPERS
# ============================================

def get_token() -> str:
    url = f"{BASE_URL}/api/v1/authentication/login"
    print(f"Logging in to {BASE_URL} ...")
    resp = requests.post(url, data={"username": USERNAME, "password": PASSWORD})
    resp.raise_for_status()
    data = resp.json()
    token = data.get("token") or data.get("access_token") or data.get("jwt")
    if not token:
        raise RuntimeError(f"No token found in login response: {data}")
    return token


def trigger_build(token: str, datamodel_id: str, build_type: str, cube_name: str):
    url = f"{BASE_URL}/api/v2/builds"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    body = {
        "datamodelId": datamodel_id,
        "buildType": build_type,
        "rowLimit": 0,
        "schemaOrigin": "latest",
    }

    print(f"Triggering build: {cube_name} (datamodel={datamodel_id}, type={build_type})")
    try:
        resp = requests.post(url, json=body, headers=headers)
        print("  -> HTTP status:", resp.status_code)
        if resp.status_code >= 300:
            msg = f"❌ ERROR triggering {cube_name}: HTTP {resp.status_code}: {resp.text}"
            print("  -> " + msg)
            send_telegram_message(msg)
            return None
        data = resp.json()
    except Exception as e:
        msg = f"❌ EXCEPTION triggering {cube_name}: {e}"
        print("  -> " + msg)
        send_telegram_message(msg)
        return None

    build_id = data.get("id") or data.get("oid") or data.get("_id") or str(data)
    print(f"  -> buildId: {build_id}")
    return build_id


def wait_for_build(token: str, build_id: str) -> str:
    url = f"{BASE_URL}/api/v2/builds/{build_id}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }

    final_statuses = {
        "SUCCEEDED",
        "SUCCESS",
        "FAILED",
        "FAILURE",
        "CANCELLED",
        "CANCELED",
        "DONE",
        "COMPLETED",
        "ERROR",
        "TIMEOUT",
    }

    deadline = time.time() + BUILD_TIMEOUT_MINUTES * 60

    while True:
        try:
            resp = requests.get(url, headers=headers)

            # Transient cases right after triggering
            if resp.status_code == 400 and "Data source not found for build id" in resp.text:
                print(f"  Build {build_id}: 400 'Data source not found' (probably starting up), retrying...")
            elif resp.status_code == 404:
                print(f"  Build {build_id}: 404 Not Found yet, retrying...")
            elif resp.status_code >= 300:
                print(f"  Error checking build {build_id}: {resp.status_code} {resp.text}")
                return "ERROR_HTTP"
            else:
                data = resp.json()
                raw_status = data.get("status") or data.get("state") or "UNKNOWN"
                status = str(raw_status).upper()
                print(f"  Build {build_id} status (raw='{raw_status}', normalized='{status}')")
                if status in final_statuses:
                    return status

        except Exception as e:
            print(f"  Exception checking build {build_id}: {e}")
            return "ERROR_EXCEPTION"

        if time.time() > deadline:
            print(f"  Build {build_id} timed out after {BUILD_TIMEOUT_MINUTES} minutes.")
            return "TIMEOUT"

        time.sleep(POLL_INTERVAL_SECONDS)


# ============================================
# MAIN COMMPEAK LOOP
# ============================================

if __name__ == "__main__":
    print(f"MAX_LOOPS_PER_RUN={MAX_LOOPS_PER_RUN}")
    token = get_token()
    print("Got token (first 30 chars):", token[:30], "...")
    print("==============================")

    loops = 0
    successful_c2_runs = 0
    last_cube1_status = None
    cube3_status = None
    cube4_status = None

    print("=== Commpeak loop: CUBE1 (Calls) -> CUBE2 (Commpeak) ===")

    while loops < MAX_LOOPS_PER_RUN:
        loops += 1
        print(f"\n--- Iteration {loops}/{MAX_LOOPS_PER_RUN} ---")

        # Step 1: build Commpeak Calls (Cube1)
        build1_id = trigger_build(token, CUBE1["id"], CUBE1["buildType"], CUBE1["name"])
        if not build1_id:
            # trigger_build already sent Telegram; stop the loop
            last_cube1_status = "TRIGGER_FAILED"
            break

        status1 = wait_for_build(token, build1_id)
        last_cube1_status = status1
        print(f"{CUBE1['name']} finished with status: {status1}")

        if status1 not in SUCCESS_STATUSES:
            # This is where you usually mean "no more new data from API"
            msg = (
                f"ℹ {CUBE1['name']} finished with non-success status: {status1}.\n"
                f"Assuming no more new API data for now. Loop stopped after {loops} cycle(s)."
            )
            print(msg)
            send_telegram_message(msg)
            break

        # Step 2: build Commpeak (Cube2) to cumulate (incremental)
        build2_id = trigger_build(token, CUBE2["id"], CUBE2["buildType"], CUBE2["name"])
        if not build2_id:
            # trigger_build already sent Telegram; stop the loop
            break

        status2 = wait_for_build(token, build2_id)
        print(f"{CUBE2['name']} finished with status: {status2}")

        if status2 not in SUCCESS_STATUSES:
            msg = f"❌ {CUBE2['name']} finished with status: {status2}. Loop stopped."
            print(msg)
            send_telegram_message(msg)
            break

        successful_c2_runs += 1
        print(f"Iteration {loops} completed successfully (Calls + Commpeak). Continuing loop...")

    # After finishing the loop, ALWAYS build Cube3 once
    print("\n=== Final step: build Commpeak Sites Employees (Cube 3) ===")
    build3_id = trigger_build(token, CUBE3["id"], CUBE3["buildType"], CUBE3["name"])
    if build3_id:
        cube3_status = wait_for_build(token, build3_id)
        print(f"{CUBE3['name']} finished with status: {cube3_status}")
        if cube3_status not in SUCCESS_STATUSES:
            send_telegram_message(f"❌ {CUBE3['name']} finished with status: {cube3_status}")
    else:
        cube3_status = "TRIGGER_FAILED"
        send_telegram_message(f"❌ Could not trigger {CUBE3['name']}.")

    # Then build Cube4 once
    print("\n=== Final step 2: build CallsCombined (Cube 4) ===")
    build4_id = trigger_build(token, CUBE4["id"], CUBE4["buildType"], CUBE4["name"])
    if build4_id:
        cube4_status = wait_for_build(token, build4_id)
        print(f"{CUBE4['name']} finished with status: {cube4_status}")
        if cube4_status not in SUCCESS_STATUSES:
            send_telegram_message(f"❌ {CUBE4['name']} finished with status: {cube4_status}")
    else:
        cube4_status = "TRIGGER_FAILED"
        send_telegram_message(f"❌ Could not trigger {CUBE4['name']}.")

    print(
        f"\nCommpeak loop done. Successful Commpeak (Cube2) runs in this workflow: {successful_c2_runs}. "
        f"Last {CUBE1['name']} status: {last_cube1_status}, "
        f"{CUBE3['name']} status: {cube3_status}, "
        f"{CUBE4['name']} status: {cube4_status}."
    )
