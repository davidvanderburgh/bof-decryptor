"""Deprecation redirector for BOF Asset Decryptor.

This standalone app has been retired in favour of the unified
**Pinball Asset Decryptor**.  On startup the GUI now polls the
unified app's release feed and surfaces a one-time prompt asking
the user to migrate.

Uses only the standard library (urllib, json).  All errors are
silently swallowed — a migration prompt is helpful but must never
interfere with the user finishing a job in this build.
"""

import json
import urllib.request

# The unified app — where every new feature, bug fix, and release
# lives from now on.  Includes BOF's full Labyrinth / Dune /
# Winchester Mystery House flow alongside JJP, Spooky, PB, CGC,
# and Williams.
UPSTREAM_REPO = "davidvanderburgh/pinball-asset-decryptor"
RELEASES_URL = (
    f"https://api.github.com/repos/{UPSTREAM_REPO}/releases/latest")
REQUEST_TIMEOUT = 5


def check_for_update(current_version):  # noqa: ARG001
    """Return ``(latest_version, download_url, release_notes)`` for the
    unified app, or None if the GitHub API is unreachable.

    ``current_version`` is accepted for backward compatibility but no
    longer compared — *this* repo is frozen, so the answer is
    unconditionally "yes, switch to the unified app."
    """
    try:
        req = urllib.request.Request(
            RELEASES_URL,
            headers={
                "Accept": "application/vnd.github.v3+json",
                "User-Agent":
                    "BOF-Asset-Decryptor-DeprecationCheck",
            })
        with urllib.request.urlopen(
                req, timeout=REQUEST_TIMEOUT) as resp:
            data = json.loads(resp.read().decode())
        tag = (data.get("tag_name") or "").lstrip("v")
        html_url = data.get("html_url") or ""
        body = data.get("body", "") or ""
        if tag and html_url:
            return (tag, html_url, body)
    except Exception:
        pass
    return None
