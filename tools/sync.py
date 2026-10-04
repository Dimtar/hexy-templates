"""Bring apps/ in line with the upstream TrueNAS catalogue.

    python tools/sync.py [--report PATH]

- A new upstream app gets a generated draft script.
- An app whose questions.yaml changed is regenerated if its script is still
  machine-managed (`managed: generated`), or flagged for a human otherwise.
- An app that disappeared upstream is flagged, never deleted.

Version-only bumps upstream (new container image, same settings) are ignored:
they don't change what an install script has to say, and recording them would
open a pull request almost every day.

Writes a Markdown summary for the pull request body and, under GitHub Actions,
sets the `changed` step output.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import yaml

import explain
import generate
import hexos
import truenas

ROOT = truenas.ROOT
APPS = ROOT / "apps"


def script_text(script: dict) -> str:
    return "\n".join(line.text for line in explain.render(script)) + "\n"


def read_meta(slug: str) -> dict | None:
    path = APPS / slug / "meta.yaml"
    return yaml.safe_load(path.read_text()) if path.exists() else None


def write_meta(slug: str, meta: dict) -> None:
    (APPS / slug / "meta.yaml").write_text(yaml.safe_dump(meta, sort_keys=False, allow_unicode=True, width=100))


def upstream_meta(app: truenas.UpstreamApp) -> dict:
    m = app.meta
    return {
        "title": m.get("title", app.name),
        "description": (m.get("description") or "").strip(),
        "icon": m.get("icon", ""),
        "categories": m.get("categories") or [],
        "keywords": m.get("keywords") or [],
        "home": m.get("home", ""),
        "screenshots": m.get("screenshots") or [],
        "train": app.train,
        "truenas_name": app.name,
    }


def bump(version: str) -> str:
    parts = (version.split(".") + ["0", "0", "0"])[:3]
    parts[2] = str(int(parts[2]) + 1) if parts[2].isdigit() else "1"
    return ".".join(parts)


def sync(apps: dict[str, truenas.UpstreamApp], commit: str) -> dict[str, list[str]]:
    report: dict[str, list[str]] = {"new": [], "regenerated": [], "review": [], "removed": []}
    APPS.mkdir(exist_ok=True)

    for slug, app in apps.items():
        meta = read_meta(slug)
        upstream = {
            "version": app.meta.get("version"),
            "app_version": app.meta.get("app_version"),
            "questions_sha": app.questions_sha,
            "commit": commit,
            "source": app.source_url,
        }

        if meta is None:
            (APPS / slug).mkdir(parents=True, exist_ok=True)
            (APPS / slug / "script.json").write_text(script_text(generate.generate(app)))
            write_meta(slug, {
                **upstream_meta(app),
                "status": "draft",
                "managed": "generated",
                "upstream": upstream,
                "notes": [],
            })
            report["new"].append(slug)
            continue

        if meta.get("removed_upstream"):
            meta.pop("removed_upstream")
            write_meta(slug, meta)

        old = meta.get("upstream") or {}
        if old.get("questions_sha") == app.questions_sha:
            continue

        line = f"{slug}: TrueNAS {old.get('version', '?')} → {upstream['version']}"
        meta.update(upstream_meta(app))
        meta["upstream"] = upstream

        if meta.get("managed", "generated") == "generated":
            script_path = APPS / slug / "script.json"
            current = json.loads(script_path.read_text())
            fresh = generate.generate(app)
            fresh["script"]["version"] = bump(current.get("script", {}).get("version", "0.1.0"))
            fresh["script"]["changeLog"] = f"Regenerated for TrueNAS {app.name} {upstream['version']}"
            compare = lambda s: {k: v for k, v in s.items() if k != "script"}  # noqa: E731
            if compare(fresh) != compare(current):
                script_path.write_text(script_text(fresh))
                if meta.get("status") != "draft":
                    meta["status"] = "needs-retest"
                report["regenerated"].append(line)
        else:
            meta["needs_review"] = f"questions.yaml changed upstream ({old.get('version', '?')} → {upstream['version']})"
            report["review"].append(line)
        write_meta(slug, meta)

    for app_dir in sorted(p for p in APPS.iterdir() if p.is_dir()):
        if app_dir.name not in apps:
            meta = read_meta(app_dir.name) or {}
            if not meta.get("removed_upstream"):
                meta["removed_upstream"] = True
                write_meta(app_dir.name, meta)
                report["removed"].append(app_dir.name)
    return report


def sync_curated(curated: set[str]) -> dict[str, list[str]]:
    """Mirror which apps HexOS curates into each app's meta.yaml."""
    report: dict[str, list[str]] = {"curated": [], "uncurated": []}
    for app_dir in sorted(p for p in APPS.iterdir() if p.is_dir()):
        meta = read_meta(app_dir.name) or {}
        now, was = app_dir.name in curated, bool(meta.get("curated"))
        if now == was:
            continue
        if now:
            meta["curated"] = True
            report["curated"].append(app_dir.name)
        else:
            meta.pop("curated", None)
            report["uncurated"].append(app_dir.name)
        write_meta(app_dir.name, meta)
    return report


def render_report(report: dict[str, list[str]], commit: str) -> str:
    out = [
        "Automated check against the [TrueNAS apps catalogue]"
        f"(https://github.com/truenas/apps/tree/{commit}).",
        "",
    ]
    sections = [
        ("new", "🆕 New apps — draft scripts generated", "Check each draft and install-test it before marking `status: tested`."),
        ("regenerated", "🔄 Settings changed — script regenerated", "The app's TrueNAS settings changed, so its generated script was rebuilt. Compare the diff."),
        ("review", "✋ Settings changed — hand-written script needs a look", "These scripts are `managed: manual`, so nothing was changed. Update them by hand, then delete `needs_review` from meta.yaml."),
        ("removed", "🗑️ Removed from the TrueNAS catalogue", "Flagged with `removed_upstream: true`. Delete the folder if it should go."),
        ("curated", "⭐ Now curated by HexOS", "HexOS added an official script for these apps, so they're now tagged Curated."),
        ("uncurated", "Curated tag removed", "These apps are no longer in HexOS's official catalogue."),
    ]
    for key, title, hint in sections:
        items = report[key]
        if not items:
            continue
        out += [f"### {title} ({len(items)})", "", hint, ""]
        shown = items[:200]
        out += [f"- `{i}`" for i in shown]
        if len(items) > len(shown):
            out.append(f"- …and {len(items) - len(shown)} more")
        out.append("")
    return "\n".join(out)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, default=ROOT / ".cache" / "sync-report.md")
    parser.add_argument("--no-fetch", action="store_true", help="use the existing .cache checkout")
    args = parser.parse_args()

    path = truenas.CACHE if args.no_fetch else truenas.fetch()
    commit = truenas.commit(path)
    report = sync(truenas.load(path), commit)
    report.update(sync_curated(hexos.curated()))
    changed = any(report.values())

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(render_report(report, commit))
    print({k: len(v) for k, v in report.items()})
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as fh:
            fh.write(f"changed={'true' if changed else 'false'}\n")
            fh.write(f"summary={', '.join(f'{len(v)} {k}' for k, v in report.items() if v)}\n")


if __name__ == "__main__":
    main()
