import os
import time
import requests

# ============================================
# CONFIG
# ============================================

BASE_URL = "https://projectanalytics.sisense.com"

USERNAME = os.environ["SISENSE_USER"]
PASSWORD = os.environ["SISENSE_PASS"]

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

CHAIN_INTERVAL_SECONDS = 60 * 60

# Small cubes are triggered in pairs.
# Both cubes in a pair start first, then the scheduler waits for both
# before starting the next pair.
SMALL_CUBE_BATCH_SIZE = 2

FAST_CUBES = [
    {"id": "c0c863ec-e96d-4456-9a9b-c0f97a8583b9", "name": "SB BID[6,11,18,26,35]", "buildType": "full"},
    {"id": "e1110242-decf-4fe5-a3b2-fd934c53650d", "name": "SB AI Ret", "buildType": "full"},
    {"id": "64a0ca4c-a973-403f-ad1f-ee360319c3df", "name": "EQ BID[3,14]", "buildType": "full"},
    {"id": "641738cb-93ab-46f0-b2f6-351591467464", "name": "MC BID[13,23,38]", "buildType": "full"},
    {"id": "9ff7407c-0ba8-4399-96f0-4d4504919399", "name": "IR BID[12,21,28,30,37]", "buildType": "full"},
    {"id": "26158bd5-c4e3-4068-95d3-2916a0e81819", "name": "SW BID[10,19,36]", "buildType": "full"},
    {"id": "65aedf59-57bc-4e00-be57-e11738b38318", "name": "ZI BID[22]", "buildType": "full"},
    {"id": "0ec7e2c3-06b8-47db-9816-7bfb5766d4b8", "name": "NC BID[33]", "buildType": "full"},
    {"id": "31d234b0-fdd5-4d6a-b963-3e22ebe54ca7", "name": "SC BID[29]", "buildType": "full"},
    {"id": "0a920ab7-d9bb-41c1-9b5f-243f3bb6666c", "name": "MM BID[39]", "buildType": "full"},
    #{"id": "640484b2-f3c5-479f-b3c4-446f701499f6", "name": "AM BID[40]", "buildType": "full"},
    {"id": "c9e56405-b0ac-446e-97c0-64dd787f5517", "name": "WF BID[42,43,44]", "buildType": "full"},
]

# These cubes remain sequential and critical.
# If one fails, the remaining big cubes and post-big cubes are skipped,
# preserving the existing behaviour.
BIG_CUBES = [
    {"id": "271c0e9b-7ead-486e-9a05-7699273226c3", "name": "DWH&Crm_Sites", "buildType": "full"},
    {"id": "c36b8200-2db5-43aa-84aa-ea4843478a8e", "name": "Modernized DWH&Crm_Sites", "buildType": "full"},
    {"id": "5072195f-0b4b-4c8e-aba7-7f8ab1dc927c", "name": "Plan Overview", "buildType": "full"},
    {"id": "c8855636-6fc0-41e9-b4df-eba98c4d08d0", "name": "Plan Overview - Alex POC", "buildType": "full"},
]

# FTD Tracker runs after all big cubes.
# Its failure is non-blocking: Sites Compare must still be attempted.
FTD_TRACKER_CUBE = {
    "id": "7c821f78-1837-4944-aec5-42ae1ebca7aa",
    "name": "FTD Tracker List",
    "buildType": "full",
}

# Sites Compare runs after FTD Tracker, even if FTD Tracker fails.
FINAL_CUBE = {
    "id": "e808e919-8ea2-420d-8df6-5430566ac1af",
    "name": "Sites Compare",
    "buildType": "full",
}

POLL_INTERVAL_SECONDS = 30
BUILD_TIMEOUT_MINUTES = 60

SUCCESS_STATUSES = {"SUCCEEDED", "SUCCESS", "DONE", "COMPLETED"}


# ============================================
# TELEGRAM
# ============================================

def send_telegram_message(text: str):
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

    resp = requests.post(
        url,
        data={"username": USERNAME, "password": PASSWORD},
        timeout=30,
    )
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

    print(f"Triggering build: {cube_name} ({datamodel_id}, type={build_type})")

    try:
        resp = requests.post(
            url,
            json=body,
            headers=headers,
            timeout=30,
        )
        print("  -> HTTP status:", resp.status_code)

        if resp.status_code >= 300:
            msg = (
                f"❌ Sisense build trigger FAILED for cube '{cube_name}' "
                f"({datamodel_id}). HTTP {resp.status_code}: {resp.text}"
            )
            print(msg)
            send_telegram_message(msg)
            return None

        data = resp.json()

    except Exception as e:
        msg = (
            f"❌ Exception triggering build for cube '{cube_name}' "
            f"({datamodel_id}): {e}"
        )
        print(msg)
        send_telegram_message(msg)
        return None

    build_id = data.get("id") or data.get("oid") or data.get("_id")

    if not build_id:
        msg = (
            f"❌ Sisense did not return a build ID for cube '{cube_name}' "
            f"({datamodel_id}). Response: {data}"
        )
        print(msg)
        send_telegram_message(msg)
        return None

    print(f"  -> buildId: {build_id}")
    return str(build_id)


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
            resp = requests.get(
                url,
                headers=headers,
                timeout=30,
            )

            if (
                resp.status_code == 400
                and "Data source not found for build id" in resp.text
            ):
                print(
                    f"  Build {build_id}: "
                    "400 'Data source not found', retrying..."
                )

            elif resp.status_code == 404:
                print(f"  Build {build_id}: 404 Not Found yet, retrying...")

            elif resp.status_code >= 300:
                print(
                    f"  Error checking build {build_id}: "
                    f"{resp.status_code} {resp.text}"
                )
                return "ERROR_HTTP"

            else:
                data = resp.json()
                raw_status = data.get("status") or data.get("state") or "UNKNOWN"
                status = str(raw_status).upper()

                print(f"  Build {build_id} status: {status}")

                if status in final_statuses:
                    return status

        except Exception as e:
            print(f"  Exception checking build {build_id}: {e}")
            return "ERROR_EXCEPTION"

        if time.time() > deadline:
            print(
                f"  Build {build_id} timed out after "
                f"{BUILD_TIMEOUT_MINUTES} minutes."
            )
            return "TIMEOUT"

        time.sleep(POLL_INTERVAL_SECONDS)


# ============================================
# CHAIN HELPERS
# ============================================

def split_into_batches(items, batch_size):
    """Yield consecutive batches without dropping an odd final item."""
    for start_index in range(0, len(items), batch_size):
        yield items[start_index:start_index + batch_size]


def run_fast_cubes_in_pairs(token: str):
    """
    Trigger two small cubes, wait until both finish, then start the next two.
    A failure in one small cube does not prevent the remaining pairs from running.
    """
    print(
        f"=== Batch 1: small cubes, "
        f"{SMALL_CUBE_BATCH_SIZE} running at a time ==="
    )

    batches = list(split_into_batches(FAST_CUBES, SMALL_CUBE_BATCH_SIZE))

    for batch_number, cube_batch in enumerate(batches, start=1):
        cube_names = ", ".join(cube["name"] for cube in cube_batch)

        print(
            f"\n--- Small-cube pair {batch_number}/{len(batches)}: "
            f"{cube_names} ---"
        )

        triggered_builds = []

        # Trigger every cube in this pair before waiting.
        for cube in cube_batch:
            build_id = trigger_build(
                token,
                cube["id"],
                cube["buildType"],
                cube["name"],
            )
            triggered_builds.append((cube, build_id))

        # Wait for every successfully triggered cube in this pair.
        for cube, build_id in triggered_builds:
            cube_id = cube["id"]
            cube_name = cube["name"]

            if not build_id:
                print(
                    f"Skipping wait for {cube_name} ({cube_id}) "
                    "because its trigger failed."
                )
                continue

            print(f"\nWaiting for small cube {cube_name} ({cube_id})...")
            status = wait_for_build(token, build_id)

            print(f"Small cube {cube_name} finished with status: {status}")

            if status not in SUCCESS_STATUSES:
                send_telegram_message(
                    f"❌ Sisense small cube '{cube_name}' "
                    f"finished with status: {status}"
                )

        print(
            f"\nSmall-cube pair {batch_number}/{len(batches)} finished. "
            "Moving to the next pair."
        )


def run_critical_big_cubes(token: str) -> bool:
    """
    Run the main big cubes one by one.
    Returns False immediately if a big cube cannot be triggered or fails.
    """
    print("\n=== Batch 2: critical big cubes sequential ===")

    for cube in BIG_CUBES:
        cube_id = cube["id"]
        cube_name = cube["name"]
        build_type = cube["buildType"]

        print(f"\nStarting big cube {cube_name} ({cube_id})...")

        build_id = trigger_build(
            token,
            cube_id,
            build_type,
            cube_name,
        )

        if not build_id:
            send_telegram_message(
                f"❌ Could not trigger big cube '{cube_name}' ({cube_id}). "
                "Stopping the critical big-cube batch and skipping "
                "FTD Tracker and Sites Compare."
            )
            return False

        status = wait_for_build(token, build_id)

        print(f"Big cube {cube_name} finished with status: {status}")

        if status not in SUCCESS_STATUSES:
            send_telegram_message(
                f"❌ Big cube '{cube_name}' finished with status: {status}. "
                "Stopping the critical big-cube batch and skipping "
                "FTD Tracker and Sites Compare."
            )
            return False

    return True


def run_non_blocking_ftd_tracker(token: str):
    """
    Run FTD Tracker after the main big cubes.
    Any trigger failure, build failure, error, or timeout is reported,
    but Sites Compare will still run afterward.
    """
    cube = FTD_TRACKER_CUBE
    cube_id = cube["id"]
    cube_name = cube["name"]
    build_type = cube["buildType"]

    print("\n=== Batch 3: FTD Tracker, non-blocking ===")
    print(f"\nStarting {cube_name} ({cube_id})...")

    build_id = trigger_build(
        token,
        cube_id,
        build_type,
        cube_name,
    )

    if not build_id:
        print(
            f"{cube_name} could not be triggered. "
            "Continuing to Sites Compare."
        )
        send_telegram_message(
            f"❌ Could not trigger '{cube_name}' ({cube_id}). "
            "The scheduler will continue with Sites Compare."
        )
        return

    status = wait_for_build(token, build_id)

    print(f"{cube_name} finished with status: {status}")

    if status not in SUCCESS_STATUSES:
        send_telegram_message(
            f"❌ Sisense cube '{cube_name}' finished with status: {status}. "
            "The scheduler will continue with Sites Compare."
        )
    else:
        print(f"{cube_name} succeeded. Continuing to Sites Compare.")


def run_sites_compare(token: str):
    """Run Sites Compare after the FTD Tracker attempt."""
    cube_id = FINAL_CUBE["id"]
    cube_name = FINAL_CUBE["name"]
    build_type = FINAL_CUBE["buildType"]

    print("\n=== Batch 4: Sites Compare ===")
    print(f"\nStarting final cube {cube_name} ({cube_id})...")

    build_id = trigger_build(
        token,
        cube_id,
        build_type,
        cube_name,
    )

    if not build_id:
        send_telegram_message(
            f"❌ Could not trigger final cube '{cube_name}' ({cube_id})"
        )
        return

    status = wait_for_build(token, build_id)

    print(f"Final cube {cube_name} finished with status: {status}")

    if status not in SUCCESS_STATUSES:
        send_telegram_message(
            f"❌ Sisense final cube '{cube_name}' "
            f"finished with status: {status}"
        )


# ============================================
# CHAIN LOGIC
# ============================================

def run_chain():
    token = get_token()

    print("Got token.")
    print("==============================")

    # 1. Small cubes: exactly two active builds at a time.
    run_fast_cubes_in_pairs(token)

    # 2. Main big cubes: sequential and critical.
    all_big_ok = run_critical_big_cubes(token)

    if not all_big_ok:
        print(
            "\nSkipping FTD Tracker and Sites Compare because "
            "the critical big-cube batch did not fully succeed."
        )
        print("\nChain finished.")
        return

    # 3. FTD Tracker: sequential but non-blocking.
    run_non_blocking_ftd_tracker(token)

    # 4. Sites Compare: always attempted after FTD Tracker,
    # even when FTD Tracker failed.
    run_sites_compare(token)

    print("\nChain finished.")


# ============================================
# MAIN LOOP
# ============================================

if __name__ == "__main__":

    while True:
        chain_start_time = time.time()
        chain_start_readable = time.strftime("%Y-%m-%d %H:%M:%S")

        print("\n============================================")
        print(f"Starting Sisense build chain at {chain_start_readable}")
        print("============================================")

        try:
            run_chain()
        except Exception as e:
            msg = f"❌ Sisense build chain crashed with exception: {e}"
            print(msg)
            send_telegram_message(msg)

        elapsed = time.time() - chain_start_time
        remaining_wait = CHAIN_INTERVAL_SECONDS - elapsed

        if remaining_wait > 0:
            print(
                "\nChain finished before 1 hour. "
                f"Waiting {remaining_wait / 60:.1f} minutes "
                "before next chain start."
            )
            time.sleep(remaining_wait)
        else:
            print(
                "\nChain took longer than 1 hour. "
                "Starting next chain immediately."
            )
