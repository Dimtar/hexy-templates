# Hexy Templates

HexOS custom install scripts for every app in the [TrueNAS apps catalogue](https://github.com/truenas/apps), with each script explained in plain language.

The site has three parts:

- **App library** (`/`): search and filter all apps.
- **App pages** (`/apps/<app>/`): the install script on the left. On the right are numbered boxes that explain each part of the script. Hovering a box highlights the lines it covers.
- **Install guide** (`/guide/`): step-by-step instructions with screenshots.

## Layout

```
apps/<app>/script.json   the install script (exactly what users copy)
apps/<app>/meta.yaml     title, icon, status, upstream tracking, custom notes
site/templates/          Jinja page templates
site/static/             CSS, JS, icon
site/guide/steps.yaml    guide text; screenshots go in site/guide/img/
tools/generate.py        drafts a script from a TrueNAS app's questions.yaml
tools/explain.py         turns a script into the plain-language boxes
tools/sync.py            compares apps/ with upstream TrueNAS
tools/validate.py        checks scripts against HexOS's install-script rules
tools/build.py           builds the static site into dist/
```

## Working locally

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python tools/build.py --base /
python3 -m http.server 8411 --directory dist
```

## meta.yaml fields you'll edit

| Field | Meaning |
|---|---|
| `status` | `draft` (generated, untested), `tested` (installed on real HexOS), `needs-retest` (was tested, then regenerated) |
| `managed` | `generated`: sync may rewrite `script.json` when TrueNAS changes. Set it to `manual` once you hand-edit a script, so sync only flags the app instead of overwriting it. |
| `notes` | Extra or replacement explanation boxes. A note whose `path` matches an automatic box replaces that box. |
| `curated` | Set by sync when HexOS has its own official script for the app (read from the `prod` branch of eshtek/hexos-app-catalog). Don't edit by hand. |
| `needs_review` | Set by sync on `manual` apps. Delete it once you've updated the script. |

Example note:

```yaml
notes:
  - path: app_values.storage.data
    title: Your photo library
    text: Every photo and video you upload is stored here. Back this folder up.
    tone: storage   # info | storage | network | warning
```

## Catalogue updates

`.github/workflows/sync-catalog.yml` runs every day at 6pm Sydney time (adjusting for daylight saving), and you can also start it by hand from the Actions tab. It opens or updates a single pull request on the `catalog-sync` branch:

- **New TrueNAS apps** get a draft script.
- **Changed apps** (when their `questions.yaml` changed) are regenerated if `managed: generated`, or flagged if `managed: manual`.
- **Curated apps**: the `curated` tag follows HexOS's official catalogue, and any change shows up in the same pull request.
- **Removed apps** are flagged with `removed_upstream: true` and are never deleted automatically.

Version-only bumps (a new container image with the same settings) are ignored on purpose.

Nothing is merged automatically.

## Credits

App metadata and icons come from the TrueNAS apps catalogue. The script format follows [HexOS's install-script docs](https://docs.hexos.com/features/apps/install-scripts/reference/schema) and the official [hexos-app-catalog](https://github.com/eshtek/hexos-app-catalog). This is a community project and is not affiliated with HexOS, Eshtek or iXsystems.
