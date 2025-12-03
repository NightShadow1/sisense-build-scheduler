import os
import requests

# ===== CONFIG =====

BASE_URL = "https://projectanalytics.sisense.com"
DATAMODEL_ID = "641738cb-93ab-46f0-b2f6-351591467464"  # your cube ID

# Build type in Sisense: adjust if you use something different
BUILD_TYPE = "schema_changes"   # or "by_table", "full", etc.


def get_token() -> str:
    """
    Log in to Sisense via /api/v1/authentication/login and return a fresh token.
    Username and password come from environment variables.
    """
    username = os.environ["SISENSE_USER"]
    password = os.environ["SISENSE_PASS"]

    url = f"{BASE_URL}/api/v1/authentication/login"
    resp = requests.post(url, data={"username": username, "password": password})
    resp.raise_for_status()

    data = resp.json()
    token = data.get("token") or data.get("access_token") or data.get("jwt")
    if not token:
        raise RuntimeError(f"No token in login response: {data}")

    return token


def trigger_build(token: str) -> None:
    """
    Call POST /api/v2/builds to trigger a build for the datamodel.
    """
    url = f"{BASE_URL}/api/v2/builds"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    body = {
        "datamodelId": DATAMODEL_ID,
        "buildType": BUILD_TYPE,
        "rowLimit": 0,
        "schemaOrigin": "latest",
    }

    resp = requests.post(url, json=body, headers=headers)
    print("Build call status:", resp.status_code)
    print("Response:", resp.text)
    resp.raise_for_status()


if __name__ == "__main__":
    t = get_token()
    print("Got token (first 30 chars):", t[:30], "...")
    trigger_build(t)
    print("Done.")
