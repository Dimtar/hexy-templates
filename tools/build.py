"""Build the static site into dist/.

    python tools/build.py [--base /] [--out dist]

`--base` is the URL prefix the site is served from: "/" on the custom domain
(hexytemplates.com), or "/hexy-templates/" if it ever moves back to
dimtar.github.io/hexy-templates/.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import html
import json
import re
import shutil
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

import explain
import hexos
from truenas import ROOT

SITE = ROOT / "site"
APPS = ROOT / "apps"
UPDATES = ROOT / "updates"
HEXOS_ONLY = ROOT / "hexos-only"

# How each kind of change is described on the Updates page, in plain words.
UPDATE_SECTIONS = {
    "new": ("New apps", "These apps were added to the TrueNAS catalogue, so they now have install scripts here.",
            "{n} new app", "{n} new apps"),
    "regenerated": ("Refreshed scripts", "These apps changed their settings in TrueNAS, so their scripts were updated to match. "
                    "Apps you've already installed aren't affected — a script is only used when you install.",
                    "{n} refreshed script", "{n} refreshed scripts"),
    "curated": ("Now curated by HexOS", "HexOS now has its own official install script for these, so you can install them "
                "with the regular Install button.", "{n} now curated", "{n} now curated"),
    "uncurated": ("No longer curated by HexOS", "HexOS no longer has an official script for these. "
                  "The script here still works as a custom install.", "{n} no longer curated", "{n} no longer curated"),
    "hexos_only": ("Only available from HexOS", "HexOS offers these apps itself and they aren't in the TrueNAS catalogue, "
                   "so there's no script here. Install them straight from the Apps page in HexOS.",
                   "{n} HexOS-only app", "{n} HexOS-only apps"),
    "hexos_only_removed": ("No longer offered by HexOS", "HexOS has stopped offering these apps.",
                           "{n} no longer offered", "{n} no longer offered"),
    "removed": ("Removed from TrueNAS", "TrueNAS no longer lists these apps. Their scripts stay here for now, "
                "but they may stop working.", "{n} removed", "{n} removed"),
}

STATUS = {
    "tested": ("Tested", "Installed and checked on a real HexOS server."),
    "needs-retest": ("Needs re-test", "Was tested, but the TrueNAS app has changed since. Probably fine — not re-checked yet."),
    "draft": ("Not yet tested", "Generated automatically from the TrueNAS app settings and not yet installed on a real HexOS server."),
    "hexos-only": ("HexOS only", "Not in the TrueNAS catalogue. Only HexOS's own version exists, so there's no script here."),
}

TOKEN = re.compile(
    r'(?P<key>"(?:[^"\\]|\\.)*"(?=\s*:))|(?P<str>"(?:[^"\\]|\\.)*")|(?P<num>-?\d+(?:\.\d+)?)|(?P<lit>\btrue\b|\bfalse\b|\bnull\b)'
)
MACRO = re.compile(r"(\$[A-Z_]{3,})")


def highlight(text: str) -> Markup:
    out, pos = [], 0
    for m in TOKEN.finditer(text):
        out.append(html.escape(text[pos:m.start()]))
        kind, value = m.lastgroup, html.escape(m.group())
        if kind == "str":
            value = MACRO.sub(r'<span class="t-macro">\1</span>', value)
        out.append(f'<span class="t-{kind}">{value}</span>')
        pos = m.end()
    out.append(html.escape(text[pos:]))
    return Markup("".join(out))


def explained(script: dict, slug: str, title: str, notes: list | None = None) -> dict:
    """The highlighted, line-numbered script and its explanation boxes, for app pages."""
    lines, boxes = explain.explain(script, slug, title, notes)
    markers: dict[int, list[int]] = {}
    for b in boxes:
        markers.setdefault(b.start, []).append(b.number)
    return {
        "lines": [
            {"n": i, "html": highlight(line.text), "markers": markers.get(i, [])}
            for i, line in enumerate(lines, 1)
        ],
        "boxes": boxes,
    }


def load_apps() -> list[dict]:
    apps = []
    for folder in sorted(p for p in APPS.iterdir() if p.is_dir()):
        meta = yaml.safe_load((folder / "meta.yaml").read_text()) or {}
        script_text = (folder / "script.json").read_text()
        script = json.loads(script_text)
        title = meta.get("title", folder.name)
        status = meta.get("status", "draft")
        apps.append({
            "slug": folder.name,
            "meta": meta,
            "title": title,
            "status": status,
            "curated": bool(meta.get("curated")),
            "official_url": hexos.script_url(folder.name),
            "status_label": STATUS.get(status, STATUS["draft"])[0],
            "status_help": STATUS.get(status, STATUS["draft"])[1],
            "script_text": script_text,
            **explained(script, folder.name, title, meta.get("notes")),
            "search": " ".join([
                title, folder.name, meta.get("description", ""),
                *meta.get("categories", []), *meta.get("keywords", []),
            ]).lower(),
        })
    return apps


def load_hexos_only() -> list[dict]:
    """Cards for apps HexOS curates that TrueNAS doesn't have.

    Their pages explain HexOS's own script, fetched fresh at build time rather
    than kept in this repo. If GitHub can't be reached, the page goes without.
    """
    apps = []
    for f in sorted(HEXOS_ONLY.glob("*.yaml")) if HEXOS_ONLY.exists() else []:
        meta = yaml.safe_load(f.read_text()) or {}
        meta["description"] = meta.get("description") or "A curated app you can install straight from HexOS."
        title = meta.get("title", f.stem)
        try:
            script = hexos.official_script(f.stem)
        except (OSError, ValueError) as e:
            print(f"warning: no HexOS script for {f.stem}: {e}")
            script = None
        apps.append({
            "slug": f.stem,
            "meta": meta,
            "title": title,
            "status": "hexos-only",
            "hexos_only": True,
            "curated": True,
            "official_url": hexos.script_url(f.stem),
            "status_label": STATUS["hexos-only"][0],
            "status_help": STATUS["hexos-only"][1],
            "search": " ".join([title, f.stem, meta["description"], "hexos only", *meta.get("categories", [])]).lower(),
            **({"script_text": "\n".join(line.text for line in explain.render(script)) + "\n", **explained(script, f.stem, title)}
               if script else {}),
        })
    return apps


def load_updates(apps: list[dict]) -> list[dict]:
    by_slug = {a["slug"]: a for a in apps}
    updates = []
    for f in sorted(UPDATES.glob("*.yaml"), reverse=True) if UPDATES.exists() else []:
        raw = yaml.safe_load(f.read_text()) or {}
        day = datetime.date.fromisoformat(str(raw.get("date", f.stem)))
        sections, summary = [], []
        for key, (title, text, one, many) in UPDATE_SECTIONS.items():
            slugs = raw.get(key) or []
            if not slugs:
                continue
            listed = []
            for slug in slugs:
                app = by_slug.get(slug)
                listed.append({
                    "slug": slug,
                    "exists": app is not None,
                    "title": app["title"] if app else slug,
                    "icon": app["meta"].get("icon", "") if app else "",
                })
            listed.sort(key=lambda a: a["title"].lower())
            sections.append({"title": title, "text": text, "apps": listed})
            summary.append((one if len(slugs) == 1 else many).format(n=len(slugs)))
        if sections:
            updates.append({
                "date": day.isoformat(),
                "date_label": f"{day.day} {day:%B %Y}",
                "summary": " · ".join(summary),
                "sections": sections,
            })
    return updates


def build(base: str, out: Path) -> None:
    env = Environment(loader=FileSystemLoader(SITE / "templates"), autoescape=select_autoescape())
    # Appended to CSS/JS URLs so a deploy never pairs new HTML with stale cached assets.
    digest = hashlib.sha256()
    for f in sorted((SITE / "static").rglob("*")):
        if f.is_file():
            digest.update(f.read_bytes())
    env.globals.update(base=base, repo="https://github.com/Dimtar/hexy-templates", v=digest.hexdigest()[:10])
    env.filters["tojson_attr"] = lambda v: json.dumps(v)

    scripted = load_apps()
    apps = sorted(scripted + load_hexos_only(), key=lambda a: a["slug"])
    categories = sorted({c for a in apps for c in a["meta"].get("categories", [])})
    counts = {s: sum(a["status"] == s for a in apps) for s in STATUS}
    counts["curated"] = sum(a["curated"] for a in apps)

    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(SITE / "static", out / "static")
    if (SITE / "guide" / "img").exists():
        shutil.copytree(SITE / "guide" / "img", out / "guide" / "img")

    def write(rel: str, template: str, **ctx) -> None:
        path = out / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(env.get_template(template).render(**ctx))

    write("index.html", "index.html", apps=apps, scripted=len(scripted), categories=categories, counts=counts,
          page="library", latest=load_updates(apps)[:1])
    for app in apps:
        if app.get("hexos_only"):
            write(f"apps/{app['slug']}/index.html", "hexos_only.html", app=app, page="app")
            continue
        write(f"apps/{app['slug']}/index.html", "app.html", app=app, page="app")
        (out / "apps" / app["slug"] / f"{app['slug']}.json").write_text(app["script_text"])

    guide = yaml.safe_load((SITE / "guide" / "steps.yaml").read_text())
    for step in guide["steps"]:
        shot = step.get("screenshot")
        step["has_screenshot"] = bool(shot) and (SITE / "guide" / "img" / shot).exists()
    write("guide/index.html", "guide.html", guide=guide, page="guide")
    updates = load_updates(apps)
    write("updates/index.html", "updates.html", updates=updates, page="updates")
    write("faq/index.html", "faq.html", faq=yaml.safe_load((SITE / "faq.yaml").read_text()), page="faq")
    write("404.html", "404.html", page="404")
    (out / ".nojekyll").write_text("")
    print(f"Built {len(apps)} app pages ({len(apps) - len(scripted)} HexOS only) into {out}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="/")
    parser.add_argument("--out", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    base = args.base if args.base.endswith("/") else args.base + "/"
    build(base, args.out)


if __name__ == "__main__":
    main()
