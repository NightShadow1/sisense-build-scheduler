import os
import time
import requests

# ============================================
# CONFIG
# ============================================

BASE_URL = "https://projectanalytics.sisense.com"

# Credentials are taken from environment variables for safety.
# In GitHub Actions, set them as repository secrets and map to env.
USERNAME = os.environ["SISENSE_USER"]
PASSWORD = os.environ["SISENSE_PASS"]

# --- Batch 1: fast cubes built in parallel (10 total) ---
FAST_CUBES = [
    {"id": "c0c863ec-e96d-4456-9a9b-c0f97a8583b9", "buildType": "full"},
    {"id": "64a0ca4c-a973-403f-ad1f-ee360319c3df", "buildType": "full"},
    {"id": "641738cb-93ab-46f0-b2f6-351591467464", "buildType": "full"},
    {"id": "9ff7407c-0ba8-4399-96f0-4d4504919399", "buildType": "full"},
    {"id": "b9c2f5e9-094e-4aa6-8504-86e7af9fb408", "buildType": "full"},
    {"id": "26158bd5-c4e3-4068-95d3-2916a0e81819", "buildType": "full"},
    {"id": "65aedf59-57bc-4e00-be57-e11738b38318", "buildType": "full"},
    {"id": "0ec7e2c3-06b8-47db-9816-7bfb5766d4b8", "buildType": "full"},
    {"id": "31d234b0-fdd5-4d6a-b963-3e22ebe54ca7", "buildType": "full"},
    {"id": "0a920ab7-d9bb-41c1-9b5f-243f3bb6666c", "buildType": "full"},
]

# --- Batch 2: big cubes in parallel ---
BIG_CUBES = [
    {"id": "c36b8200-2db5-43aa-84aa-ea4843478a8e", "buildType": "full"},
    {"id": "271c0e9b-7ead-486e-9a05-7699273226c3", "buildType": "full"},
]

# --- Batch 3: final quick cube ---
FINAL_CUBE = {
    "id": "e808e919-8ea2-420d-8df6-5430566ac1af",
    "buildType": "full",
}

# Polling settings
POLL_INTERVAL_SECONDS = 30      # how often to check build status
BUILD_TIMEOUT_MINUTES = 60      # safety timeout per build


# ============================================
# HELPER FUNCTIONS
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


def trigger_build(token: str, datamodel_id: str, build_type: str):
    """
    Trigger a build for one datamodel and return buildId.
    If the POST fails (HTTP error, bad ID, etc.) we log and return None,
    but we do NOT raise, so that other cubes can continue.
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

    print(f"Triggering build: datamodel={datamodel_id}, type={build_type}")
    try:
        resp = requests.post(url, json=body, headers=headers)
        print("  -> HTTP status:", resp.status_code)
        if resp.status_code >= 300:
            print("  -> ERROR triggering build:", resp.text)
            return None
        data = resp.json()
    except Exception as e:
        print(f"  -> EXCEPTION triggering build for {datamodel_id}: {e}")
        return None

    build_id = data.get("id") or data.get("oid") or data.get("_id") or str(data)
    print(f"  -> buildId: {build_id}")
    return build_id


def wait_for_build(token: str, build_id: str) -> str:
    """
    Poll /api/v2/builds/{buildId} until build is finished or timeout.
    We NEVER raise here; instead, we return a status string.

    Logic:
    - Certain statuses are considered *final* (SUCCEEDED, FAILED, CANCELLED, DONE, etc.).
    - Anything else is treated as "still in progress" and we keep polling.
    - A 400 with "Data source not found for build id" is treated as "still starting",
      because Sisense sometimes returns this briefly right after triggering the build.
    """

    url = f"{BASE_URL}/api/v2/builds/{build_id}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }

    # Statuses that mean the build is finished one way or another
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

            # Special case: Sisense sometimes says 400 "Data source not found for build id"
            # even though the build is in progress. Treat that as "still in progress".
            if resp.status_code == 400 and "Data source not found for build id" in resp.text:
                print(f"  Build {build_id}: 400 'Data source not found' (probably starting up), retrying...")

            elif resp.status_code == 404:
                # Build record not visible yet, treat as in progress
                print(f"  Build {build_id}: 404 Not Found yet, retrying...")

            elif resp.status_code >= 300:
                print(f"  Error checking build {build_id}: {resp.status_code} {resp.text}")
                return "ERROR_HTTP"

            else:
                data = resp.json()
                raw_status = data.get("status") or data.get("state") or "UNKNOWN"
                status = str(raw_status).upper()
                print(f"  Build {build_id} status (raw='{raw_status}', normalized='{status}')")

                # If the status is one of the known final ones, we're done
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
    # 1) Login once
    token = get_token()
    print("Got token (first 30 chars):", token[:30], "...")
    print("==============================")

    # 2) Batch 1: fast cubes in parallel
    print("=== Batch 1: fast cubes (parallel) ===")
    fast_build_ids = []
    for cube in FAST_CUBES:
        cube_id = cube["id"]
        build_type = cube["buildType"]
        build_id = trigger_build(token, cube_id, build_type)
        fast_build_ids.append((cube_id, build_id))

    # Wait for all fast cubes (only those that got a buildId)
    for cube_id, build_id in fast_build_ids:
        if not build_id:
            print(f"\nSkipping wait for {cube_id} (build trigger failed).")
            continue
        print(f"\nWaiting for fast cube {cube_id} (build {build_id}) ...")
        status = wait_for_build(token, build_id)
        print(f"Fast cube {cube_id} finished with status: {status}")

    # 3) Batch 2: big cubes in parallel
    print("\n=== Batch 2: big cubes (parallel) ===")
    big_build_ids = []

    # Trigger all big cubes
    for cube in BIG_CUBES:
        cube_id = cube["id"]
        build_type = cube["buildType"]
        print(f"\nStarting big cube {cube_id} ...")
        build_id = trigger_build(token, cube_id, build_type)
        big_build_ids.append((cube_id, build_id))

    # Wait for all big cubes
    for cube_id, build_id in big_build_ids:
        if not build_id:
            print(f"  Could not trigger big cube {cube_id}, skipping wait.")
            continue
        print(f"  Waiting for big cube {cube_id} (build {build_id}) ...")
        status = wait_for_build(token, build_id)
        print(f"Big cube {cube_id} finished with status: {status}")

    # 4) Batch 3: final quick cube
    print("\n=== Batch 3: final quick cube ===")
    cube_id = FINAL_CUBE["id"]
    build_type = FINAL_CUBE["buildType"]
    print(f"\nStarting final cube {cube_id} ...")
    build_id = trigger_build(token, cube_id, build_type)
    if build_id:
        status = wait_for_build(token, build_id)
        print(f"Final cube {cube_id} finished with status: {status}")
    else:
        print(f"Could not trigger final cube {cube_id}.")

    print("\nAll batches done.")
