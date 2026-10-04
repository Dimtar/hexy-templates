"""Build the static site into dist/.

    python tools/build.py [--base /hexy-templates/] [--out dist]

`--base` is the URL prefix the site is served from: "/hexy-templates/" on
GitHub Pages (a project site), "/" for a custom domain or local preview.
"""

from __future__ import annotations

import argparse
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

STATUS = {
    "tested": ("Tested", "Installed and checked on a real HexOS server."),
    "needs-retest": ("Needs re-test", "Was tested, but the TrueNAS app has changed since. Probably fine — not re-checked yet."),
    "draft": ("Not yet tested", "Generated automatically from the TrueNAS app settings and not yet installed on a real HexOS server."),
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


def load_apps() -> list[dict]:
    apps = []
    for folder in sorted(p for p in APPS.iterdir() if p.is_dir()):
        meta = yaml.safe_load((folder / "meta.yaml").read_text()) or {}
        script_text = (folder / "script.json").read_text()
        script = json.loads(script_text)
        title = meta.get("title", folder.name)
        lines, boxes = explain.explain(script, folder.name, title, meta.get("notes"))
        markers: dict[int, list[int]] = {}
        for b in boxes:
            markers.setdefault(b.start, []).append(b.number)
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
            "lines": [
                {"n": i, "html": highlight(line.text), "markers": markers.get(i, [])}
                for i, line in enumerate(lines, 1)
            ],
            "boxes": boxes,
            "search": " ".join([
                title, folder.name, meta.get("description", ""),
                *meta.get("categories", []), *meta.get("keywords", []),
            ]).lower(),
        })
    return apps


def build(base: str, out: Path) -> None:
    env = Environment(loader=FileSystemLoader(SITE / "templates"), autoescape=select_autoescape())
    env.globals.update(base=base, repo="https://github.com/Dimtar/hexy-templates")
    env.filters["tojson_attr"] = lambda v: json.dumps(v)

    apps = load_apps()
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

    write("index.html", "index.html", apps=apps, categories=categories, counts=counts, page="library")
    for app in apps:
        write(f"apps/{app['slug']}/index.html", "app.html", app=app, page="app")
        (out / "apps" / app["slug"] / f"{app['slug']}.json").write_text(app["script_text"])

    guide = yaml.safe_load((SITE / "guide" / "steps.yaml").read_text())
    for step in guide["steps"]:
        shot = step.get("screenshot")
        step["has_screenshot"] = bool(shot) and (SITE / "guide" / "img" / shot).exists()
    write("guide/index.html", "guide.html", guide=guide, page="guide")
    write("404.html", "404.html", page="404")
    (out / ".nojekyll").write_text("")
    print(f"Built {len(apps)} app pages into {out}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="/hexy-templates/")
    parser.add_argument("--out", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    base = args.base if args.base.endswith("/") else args.base + "/"
    build(base, args.out)


if __name__ == "__main__":
    main()
