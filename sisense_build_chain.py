import os
import time
import requests

# ============================================
# CONFIG
# ============================================

BASE_URL = "https://projectanalytics.sisense.com"

# Credentials are taken from environment variables for safety.
USERNAME = os.environ["SISENSE_USER"]
PASSWORD = os.environ["SISENSE_PASS"]

# Telegram config (optional – if not set, script just logs to console)
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# --- Batch 1: fast cubes built in parallel ---
FAST_CUBES = [
    {"id": "c0c863ec-e96d-4456-9a9b-c0f97a8583b9", "name": "SB BID[6,11,18,26,35]", "buildType": "full"},
    {"id": "e1110242-decf-4fe5-a3b2-fd934c53650d", "name": "SB AI Ret",             "buildType": "full"},
    {"id": "64a0ca4c-a973-403f-ad1f-ee360319c3df", "name": "EQ BID[3,14]",          "buildType": "full"},
    {"id": "641738cb-93ab-46f0-b2f6-351591467464", "name": "MC BID[13,23,38]",      "buildType": "full"},
    {"id": "9ff7407c-0ba8-4399-96f0-4d4504919399", "name": "IR BID[12,21,28,30,37]","buildType": "full"},
    {"id": "b9c2f5e9-094e-4aa6-8504-86e7af9fb408", "name": "ICC BID[8,16,24,34]",   "buildType": "full"},
    {"id": "26158bd5-c4e3-4068-95d3-2916a0e81819", "name": "SW BID[10,19,36]",      "buildType": "full"},
    {"id": "65aedf59-57bc-4e00-be57-e11738b38318", "name": "ZI BID[22]",            "buildType": "full"},
    {"id": "0ec7e2c3-06b8-47db-9816-7bfb5766d4b8", "name": "NC BID[33]",            "buildType": "full"},
    {"id": "31d234b0-fdd5-4d6a-b963-3e22ebe54ca7", "name": "SC BID[29]",            "buildType": "full"},
    {"id": "0a920ab7-d9bb-41c1-9b5f-243f3bb6666c", "name": "MM BID[39]",            "buildType": "full"},
]

# --- Batch 2: big cubes SEQUENTIAL ---
# Order is important: first DWH&Crm_Sites, then Modernized DWH&Crm_Sites
BIG_CUBES = [
    {"id": "271c0e9b-7ead-486e-9a05-7699273226c3", "name": "DWH&Crm_Sites",             "buildType": "full"},
    {"id": "c36b8200-2db5-43aa-84aa-ea4843478a8e", "name": "Modernized DWH&Crm_Sites",  "buildType": "full"},
]

# --- Batch 3: final quick cube ---
FINAL_CUBE = {
    "id": "e808e919-8ea2-420d-8df6-5430566ac1af",
    "name": "Sites Compare",
    "buildType": "full",
}

# Polling settings
POLL_INTERVAL_SECONDS = 30      # how often to check build status
BUILD_TIMEOUT_MINUTES = 60      # safety timeout per build

# Statuses that mean success
SUCCESS_STATUSES = {"SUCCEEDED", "SUCCESS", "DONE", "COMPLETED"}


# ============================================
# TELEGRAM HELPER
# ============================================

def send_telegram_message(text: str):
    """
    Send a message to Telegram, if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are set.
    Otherwise just print a note and continue.
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
    """
    Login to Sisense and return a fresh token.
    If login fails, we stop the whole script (fatal).
    """
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
    """
    Trigger a build for one datamodel and return buildId.
    If the POST fails we log and send Telegram, then return None.
    """
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
            msg = f"❌ Sisense build trigger FAILED for cube '{cube_name}' ({datamodel_id}). HTTP {resp.status_code}: {resp.text}"
            print("  -> " + msg)
            send_telegram_message(msg)
            return None
        data = resp.json()
    except Exception as e:
        msg = f"❌ Exception triggering build for cube '{cube_name}' ({datamodel_id}): {e}"
        print("  -> " + msg)
        send_telegram_message(msg)
        return None

    build_id = data.get("id") or data.get("oid") or data.get("_id") or str(data)
    print(f"  -> buildId: {build_id}")
    return build_id


def wait_for_build(token: str, build_id: str) -> str:
    """
    Poll /api/v2/builds/{buildId} until build is finished or timeout.
    Returns a status string.
    """

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

            # 400 "Data source not found for build id" – treat as transient
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
# MAIN BATCH LOGIC
# ============================================

if __name__ == "__main__":
    token = get_token()
    print("Got token (first 30 chars):", token[:30], "...")
    print("==============================")

    # 1) Batch 1: fast cubes in parallel
    print("=== Batch 1: fast cubes (parallel) ===")
    fast_build_ids = []
    for cube in FAST_CUBES:
        cube_id = cube["id"]
        cube_name = cube["name"]
        build_type = cube["buildType"]
        build_id = trigger_build(token, cube_id, build_type, cube_name)
        fast_build_ids.append((cube_id, cube_name, build_id))

    for cube_id, cube_name, build_id in fast_build_ids:
        if not build_id:
            print(f"\nSkipping wait for {cube_name} ({cube_id}) (build trigger failed).")
            continue
        print(f"\nWaiting for fast cube {cube_name} ({cube_id}) (build {build_id}) ...")
        status = wait_for_build(token, build_id)
        print(f"Fast cube {cube_name} ({cube_id}) finished with status: {status}")
        if status not in SUCCESS_STATUSES:
            send_telegram_message(f"❌ Sisense cube '{cube_name}' finished with status: {status}")

    # 2) Batch 2: big cubes SEQUENTIAL
    print("\n=== Batch 2: big cubes (sequential) ===")

    # First: DWH&Crm_Sites
    dwh_cube = BIG_CUBES[0]
    dwh_id = dwh_cube["id"]
    dwh_name = dwh_cube["name"]
    dwh_build_type = dwh_cube["buildType"]

    print(f"\nStarting big cube {dwh_name} ({dwh_id}) ...")
    dwh_build_id = trigger_build(token, dwh_id, dwh_build_type, dwh_name)

    if not dwh_build_id:
        print(f"Could not trigger {dwh_name}. Skipping Modernized DWH&Crm_Sites and Sites Compare.")
        send_telegram_message(f"❌ Could not trigger '{dwh_name}'. Skipping downstream cubes.")
    else:
        dwh_status = wait_for_build(token, dwh_build_id)
        print(f"{dwh_name} ({dwh_id}) finished with status: {dwh_status}")
        if dwh_status not in SUCCESS_STATUSES:
            send_telegram_message(
                f"❌ Big cube '{dwh_name}' finished with status: {dwh_status}. "
                f"Skipping Modernized DWH&Crm_Sites and Sites Compare."
            )
        else:
            # Second: Modernized DWH&Crm_Sites
            mod_cube = BIG_CUBES[1]
            mod_id = mod_cube["id"]
            mod_name = mod_cube["name"]
            mod_build_type = mod_cube["buildType"]

            print(f"\nStarting big cube {mod_name} ({mod_id}) ...")
            mod_build_id = trigger_build(token, mod_id, mod_build_type, mod_name)

            if not mod_build_id:
                print(f"Could not trigger {mod_name}. Skipping Sites Compare.")
                send_telegram_message(
                    f"❌ Could not trigger '{mod_name}'. Skipping Sites Compare."
                )
            else:
                mod_status = wait_for_build(token, mod_build_id)
                print(f"{mod_name} ({mod_id}) finished with status: {mod_status}")
                if mod_status not in SUCCESS_STATUSES:
                    send_telegram_message(
                        f"❌ Big cube '{mod_name}' finished with status: {mod_status}. "
                        f"Skipping Sites Compare."
                    )
                else:
                    # 3) Batch 3: final quick cube, only if both big cubes succeeded
                    print("\n=== Batch 3: final quick cube ===")
                    cube_id = FINAL_CUBE["id"]
                    cube_name = FINAL_CUBE["name"]
                    build_type = FINAL_CUBE["buildType"]
                    print(f"\nStarting final cube {cube_name} ({cube_id}) ...")
                    build_id = trigger_build(token, cube_id, build_type, cube_name)
                    if build_id:
                        status = wait_for_build(token, build_id)
                        print(f"Final cube {cube_name} ({cube_id}) finished with status: {status}")
                        if status not in SUCCESS_STATUSES:
                            send_telegram_message(
                                f"❌ Sisense final cube '{cube_name}' finished with status: {status}"
                            )
                    else:
                        print(f"Could not trigger final cube {cube_name} ({cube_id}).")
                        send_telegram_message(
                            f"❌ Could not trigger final cube '{cube_name}' ({cube_id})"
                        )

    print("\nAll batches done.")
