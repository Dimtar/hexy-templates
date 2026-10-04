"""Read the upstream TrueNAS apps catalogue (github.com/truenas/apps).

Only each app's app.yaml and questions.yaml are needed, so the clone is sparse
and shallow: a few MB instead of the full repo with every chart template.
"""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / ".cache" / "truenas-apps"
REPO_URL = "https://github.com/truenas/apps.git"

# enterprise/dev/test apps are not shown in the regular TrueNAS catalogue.
TRAINS = ("stable", "community")


@dataclass
class UpstreamApp:
    slug: str  # unique across trains; the name, or name-community on a clash
    name: str
    train: str
    meta: dict  # app.yaml
    questions: list  # questions.yaml -> questions
    questions_sha: str

    @property
    def source_url(self) -> str:
        return f"https://github.com/truenas/apps/tree/master/ix-dev/{self.train}/{self.name}"


def fetch(path: Path = CACHE) -> Path:
    """Clone or fast-forward the sparse checkout and return its path."""
    patterns = [f"/ix-dev/{t}/*/{f}" for t in TRAINS for f in ("app.yaml", "questions.yaml")]
    if not (path / ".git").exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "clone", "-q", "--depth", "1", "--filter=blob:none", "--no-checkout", REPO_URL, str(path)],
            check=True,
        )
        subprocess.run(["git", "-C", str(path), "sparse-checkout", "set", "--no-cone", *patterns], check=True)
        subprocess.run(["git", "-C", str(path), "checkout", "-q", "master"], check=True)
    else:
        subprocess.run(["git", "-C", str(path), "fetch", "-q", "--depth", "1", "origin", "master"], check=True)
        subprocess.run(["git", "-C", str(path), "reset", "-q", "--hard", "origin/master"], check=True)
    return path


def commit(path: Path = CACHE) -> str:
    return subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()


def load(path: Path = CACHE) -> dict[str, UpstreamApp]:
    apps: dict[str, UpstreamApp] = {}
    for train in TRAINS:
        for app_dir in sorted((path / "ix-dev" / train).iterdir()):
            app_yaml, questions_yaml = app_dir / "app.yaml", app_dir / "questions.yaml"
            if not (app_yaml.exists() and questions_yaml.exists()):
                continue
            raw = questions_yaml.read_bytes()
            slug = app_dir.name if app_dir.name not in apps else f"{app_dir.name}-{train}"
            apps[slug] = UpstreamApp(
                slug=slug,
                name=app_dir.name,
                train=train,
                meta=yaml.safe_load(app_yaml.read_text()),
                questions=yaml.safe_load(raw)["questions"],
                questions_sha=hashlib.sha256(raw).hexdigest(),
            )
    return apps
