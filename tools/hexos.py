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


RAW = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}"


def script_url(slug: str) -> str:
    return f"https://github.com/{REPO}/blob/{BRANCH}/{slug}.json"


def _get(url: str):
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "hexy-templates-sync"})
    if os.environ.get("GITHUB_TOKEN") and url.startswith("https://api.github.com/"):
        req.add_header("Authorization", f"Bearer {os.environ['GITHUB_TOKEN']}")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def metadata(slug: str) -> dict:
    """Facts about a curated app for a HexOS-only card.

    Only names, links and categories are taken. HexOS's catalogue has no
    licence, so its descriptions and scripts are never copied.
    """
    m = _get(f"{RAW}/{slug}.json").get("metadata") or {}
    return {
        "title": m.get("name") or slug,
        "icon": f"{RAW}/{m['icon']}" if m.get("icon") else "",
        "categories": m.get("categories") or [],
        "home": m.get("homepage") or "",
    }


def curated() -> set[str]:
    entries = _get(f"https://api.github.com/repos/{REPO}/contents?ref={BRANCH}")
    return {
        e["name"][: -len(".json")]
        for e in entries
        if e["type"] == "file" and e["name"].endswith(".json") and not e["name"].startswith(IGNORE_PREFIX)
    }
