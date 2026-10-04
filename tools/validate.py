"""Check every apps/*/script.json against the rules HexOS enforces at install.

Mirrors the checks in the official catalog's validator
(github.com/eshtek/hexos-app-catalog/_lib/contract.ts): a script that is valid
JSON can still abort an install with an unknown $LOCATION, a $QUESTION with no
question behind it, or a malformed requirement.
"""

from __future__ import annotations

import json
import re
import sys

import yaml

from truenas import ROOT

SUPPORTED_VERSIONS = {4, 5, 6}
LOCATIONS = {
    "ApplicationsPerformance", "ApplicationsCapacity", "Downloads", "Documents", "Media", "Photos",
    "Music", "Movies", "Shows", "Videos", "VirtualizationPerformance", "VirtualizationCapacity",
    "InstallMedia", "VirtualDisks",
}
CALL_MACROS = {"IF", "QUESTION", "MEMORY", "RANDOM_STRING", "HOST_PATH", "MOUNTED_HOST_PATH", "LOCATION",
               "APP_INSTALLED", "GPU_CONFIG"}
BARE_MACROS = {"SERVER_LAN_IP", "SERVER_HOST_ID"}
SPEC = re.compile(r"^(\d+)(MBRAM|GBRAM|MB|GB|CORE)$|^GPU$")
QUESTION_TYPES = {"text", "number", "select", "boolean", "password"}
PERMISSIONS = {"READ_WRITE_LOCATIONS"}
STATUSES = {"draft", "needs-retest", "tested"}


def check(slug: str) -> list[str]:
    errors: list[str] = []
    folder = ROOT / "apps" / slug
    try:
        script = json.loads((folder / "script.json").read_text())
    except (OSError, json.JSONDecodeError) as e:
        return [f"script.json: {e}"]
    try:
        meta = yaml.safe_load((folder / "meta.yaml").read_text()) or {}
    except (OSError, yaml.YAMLError) as e:
        return [f"meta.yaml: {e}"]

    if script.get("version") not in SUPPORTED_VERSIONS:
        errors.append(f"version must be one of {sorted(SUPPORTED_VERSIONS)}")
    if meta.get("status") not in STATUSES:
        errors.append(f"meta.yaml status must be one of {sorted(STATUSES)}")

    raw = json.dumps(script)
    for m in re.finditer(r"\$([A-Z_]{3,})", raw):
        name, called = m.group(1), raw[m.end():m.end() + 1] == "("
        if called and name not in CALL_MACROS:
            errors.append(f"unknown macro ${name}()")
        elif not called and name not in BARE_MACROS:
            errors.append(f"${name} needs an argument list" if name in CALL_MACROS else f"unknown macro ${name}")
    for m in re.finditer(r"\$LOCATION\(([^)]+)\)", raw):
        if m.group(1).strip() not in LOCATIONS:
            errors.append(f"$LOCATION({m.group(1)}) is not a known location")

    questions = script.get("installation_questions") or []
    keys = set()
    for q in questions:
        if q.get("type") not in QUESTION_TYPES:
            errors.append(f"question {q.get('key')}: type must be one of {sorted(QUESTION_TYPES)}")
        if q.get("type") == "select" and not q.get("options"):
            errors.append(f"question {q.get('key')}: select needs options")
        keys.add(q.get("key"))
    for hook in script.get("hooks") or []:
        for inp in hook.get("inputs") or []:
            if inp.get("type") == "question":
                keys.add((inp.get("question") or {}).get("key"))
    for m in re.finditer(r"\$QUESTION\(([^)]+)\)", raw):
        if m.group(1).strip() not in keys:
            errors.append(f"$QUESTION({m.group(1)}) has no matching installation question")

    req = script.get("requirements") or {}
    used = {m.group(1).strip() for m in re.finditer(r"\$LOCATION\(([^)]+)\)", raw)}
    missing = used - set(req.get("locations") or [])
    if missing:
        errors.append(f"requirements.locations is missing {sorted(missing)}")
    for spec in req.get("specifications") or []:
        if not SPEC.match(str(spec)):
            errors.append(f"specification {spec!r} must look like 2CORE, 1GB, 4GBRAM or GPU")
    for perm in req.get("permissions") or []:
        if perm not in PERMISSIONS:
            errors.append(f"unknown permission {perm}")
    for d in script.get("ensure_directories_exists") or []:
        if not isinstance(d, dict) or "path" not in d:
            errors.append("ensure_directories_exists entries must be objects with a path")
    return errors


def main() -> int:
    slugs = sorted(p.name for p in (ROOT / "apps").iterdir() if p.is_dir())
    failed = 0
    for slug in slugs:
        for e in check(slug):
            print(f"apps/{slug}: {e}")
            failed += 1
    print(f"{len(slugs)} scripts checked, {failed} problem(s)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
