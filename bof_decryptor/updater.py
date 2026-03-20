"""Auto-update checker for BOF Asset Decryptor.

Checks the GitHub releases API for newer versions on startup.
Uses only the standard library. All errors are silently swallowed.
"""

import json
import urllib.request

GITHUB_REPO = "davidvanderburgh/bof-decryptor"
RELEASES_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
REQUEST_TIMEOUT = 5


def _parse_version(version_str):
    v = version_str.strip().lstrip("v")
    return tuple(int(x) for x in v.split("."))


def check_for_update(current_version):
    """Return (latest_version, download_url) if an update is available, else None."""
    try:
        req = urllib.request.Request(
            RELEASES_URL,
            headers={
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "BOF-Asset-Decryptor-UpdateCheck",
            },
        )
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            data = json.loads(resp.read().decode())

        tag = data.get("tag_name", "")
        html_url = data.get("html_url", "")

        if not tag or not html_url:
            return None

        if _parse_version(tag) > _parse_version(current_version):
            body = data.get("body", "") or ""
            return (tag.lstrip("v"), html_url, body)
    except Exception:
        pass

    return None
