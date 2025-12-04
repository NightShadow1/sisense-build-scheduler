import os
import time
import requests

# ============================================
# CONFIG
# ============================================

BASE_URL = "https://projectanalytics.sisense.com"

USERNAME = os.environ["SISENSE_USER"]
PASSWORD = os.environ["SISENSE_PASS"]

# Cube IDs + friendly names
CUBE1 = {
    "id": "5ccf6f64-1d56-47dd-b00a-448617603dcf",
    "name": "Commpeak Calls",
    "buildType": "full",
}

CUBE2 = {
    "id": "bf49122f-4abf-4b30-8a71-c52e8f613b00",
    "name": "Commpeak",
    "buildType": "full",
}

CUBE3 = {
    "id": "4d35c342-d629-4047-be5c-259e73ede3c6",
    "name": "Commpeak Sites Employees",
    "buildType": "full",
}

POLL_INTERVAL_SECONDS = 30
BUILD_TIMEOUT_MINUTES = 60

# 👇 configurable via env, default 5 for steady mode
MAX_LOOPS_PER_RUN = int(os.getenv("MAX_LOOPS_PER_RUN", "5"))

SUCCESS_STATUSES = {"SUCCEEDED", "SUCCESS", "DONE", "COMPLETED"}


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
            print(f"  -> ERROR triggering {cube_name}: {resp.text}")
            return None
        data = resp.json()
    except Exception as e:
        print(f"  -> EXCEPTION triggering {cube_name}: {e}")
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

            # Transient “just started” cases
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

    print("=== Commpeak loop: CUBE1 (Calls) -> CUBE2 (Commpeak) ===")

    while loops < MAX_LOOPS_PER_RUN:
        loops += 1
        print(f"\n--- Iteration {loops}/{MAX_LOOPS_PER_RUN} ---")

        # Step 1: build Commpeak Calls (Cube1)
        build1_id = trigger_build(token, CUBE1["id"], CUBE1["buildType"], CUBE1["name"])
        if not build1_id:
            print("Could not trigger Commpeak Calls. Stopping loop for this run.")
            break

        status1 = wait_for_build(token, build1_id)
        print(f"{CUBE1['name']} finished with status: {status1}")

        # 🚩 This is your “no more new data” condition:
        if status1 not in SUCCESS_STATUSES:
            print(
                f"{CUBE1['name']} did not succeed (status={status1}). "
                "Assuming no more new data for now. Stopping loop for this run."
            )
            break

        # Step 2: build Commpeak (Cube2) to cumulate
        build2_id = trigger_build(token, CUBE2["id"], CUBE2["buildType"], CUBE2["name"])
        if not build2_id:
            print(f"Could not trigger {CUBE2['name']}. Stopping loop for this run.")
            break

        status2 = wait_for_build(token, build2_id)
        print(f"{CUBE2['name']} finished with status: {status2}")

        if status2 not in SUCCESS_STATUSES:
            print(f"{CUBE2['name']} did not succeed (status={status2}). Stopping loop for this run.")
            break

        successful_c2_runs += 1
        print(f"Iteration {loops} completed successfully (Calls + Commpeak). Continuing loop...")

    # After finishing the loop, ALWAYS build Cube3 once
    print("\n=== Final step: build Commpeak Sites Employees (Cube 3) ===")
    build3_id = trigger_build(token, CUBE3["id"], CUBE3["buildType"], CUBE3["name"])
    if build3_id:
        status3 = wait_for_build(token, build3_id)
        print(f"{CUBE3['name']} finished with status: {status3}")
    else:
        print(f"Could not trigger {CUBE3['name']}.")

    print(f"\nCommpeak loop done. Successful Commpeak (Cube2) runs in this workflow: {successful_c2_runs}")
