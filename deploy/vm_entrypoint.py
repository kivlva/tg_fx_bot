"""Load the bot token from Lockbox into process memory before starting polling."""
import json
import os
import urllib.error
import urllib.request


def load_token():
    request = urllib.request.Request(
        "http://169.254.169.254/computeMetadata/v1/instance/service-accounts/default/token",
        headers={"Metadata-Flavor": "Google"},
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=10) as response:
        iam_token = json.load(response)["access_token"]
    secret_id = os.environ["LOCKBOX_SECRET_ID"]
    request = urllib.request.Request(
        f"https://payload.lockbox.api.cloud.yandex.net/lockbox/v1/secrets/{secret_id}/payload",
        headers={"Authorization": f"Bearer {iam_token}"},
    )
    with opener.open(request, timeout=15) as response:
        payload = json.load(response)
    for entry in payload["entries"]:
        if entry["key"] == "BOT_TOKEN" and entry.get("textValue"):
            return entry["textValue"]
    raise ValueError("BOT_TOKEN entry is missing")


def main():
    if not os.environ.get("BOT_TOKEN"):
        try:
            os.environ["BOT_TOKEN"] = load_token()
        except urllib.error.HTTPError as error:
            raise SystemExit(f"Lockbox/metadata request failed: HTTP {error.code}") from None
        except Exception:
            raise SystemExit("Cannot load BOT_TOKEN from Lockbox; check service account and network") from None
    from cur_converter_bot.__main__ import main as run_bot
    run_bot()


if __name__ == "__main__":
    main()
