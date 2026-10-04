"""Which apps HexOS curates itself.

HexOS's official install scripts live in github.com/eshtek/hexos-app-catalog,
one <app>.json per curated app at the repo root, named after the TrueNAS app.
The `prod` branch is what HexOS users actually get; `staging` runs ahead of it.
"""

from __future__ import annotations

import json
import os
import urllib.request

REPO = "eshtek/hexos-app-catalog"
BRANCH = "prod"
# Fixtures HexOS uses to test its own installer, not real apps.
IGNORE_PREFIX = "hexos-test"


def script_url(slug: str) -> str:
    return f"https://github.com/{REPO}/blob/{BRANCH}/{slug}.json"


def curated() -> set[str]:
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/contents?ref={BRANCH}",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "hexy-templates-sync"},
    )
    if os.environ.get("GITHUB_TOKEN"):
        req.add_header("Authorization", f"Bearer {os.environ['GITHUB_TOKEN']}")
    with urllib.request.urlopen(req, timeout=30) as resp:
        entries = json.load(resp)
    return {
        e["name"][: -len(".json")]
        for e in entries
        if e["type"] == "file" and e["name"].endswith(".json") and not e["name"].startswith(IGNORE_PREFIX)
    }
