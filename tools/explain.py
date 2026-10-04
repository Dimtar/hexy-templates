"""Turn an install script into numbered, plain-language explanation boxes.

The script is pretty-printed line by line so that each box can point at the
exact lines it describes. Boxes are derived from the script itself, so every
app gets a breakdown without anyone writing one by hand; an app's meta.yaml can
replace or add boxes through `notes`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

Path = tuple  # ("app_values", "storage", "data") or ("requirements", "ports", 0)

INLINE_WIDTH = 72


@dataclass
class Line:
    text: str
    path: Path
    inline: bool = False  # the whole value at `path` sits on this one line


@dataclass
class Box:
    path: Path
    title: str
    body: str
    start: int = 0  # 1-based line numbers, filled by attach()
    end: int = 0
    number: int = 0
    tone: str = "info"  # info | storage | network | warning

    @property
    def path_str(self) -> str:
        return path_to_str(self.path)


# --- pretty printer ---------------------------------------------------------


def _compact(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(", ", ": "))


def render(script: dict) -> list[Line]:
    lines: list[Line] = []

    def emit(value, path: Path, indent: int, prefix: str, comma: str) -> None:
        pad = "  " * indent
        compact = _compact(value)
        if not isinstance(value, (dict, list)) or not value or (
            path and len(pad) + len(prefix) + len(compact) <= INLINE_WIDTH
        ):
            lines.append(Line(f"{pad}{prefix}{compact}{comma}", path, inline=True))
            return
        opening, closing = ("{", "}") if isinstance(value, dict) else ("[", "]")
        lines.append(Line(f"{pad}{prefix}{opening}", path))
        items = list(value.items()) if isinstance(value, dict) else list(enumerate(value))
        for i, (k, v) in enumerate(items):
            child_prefix = f"{json.dumps(k, ensure_ascii=False)}: " if isinstance(value, dict) else ""
            emit(v, path + (k,), indent + 1, child_prefix, "," if i < len(items) - 1 else "")
        lines.append(Line(f"{pad}{closing}{comma}", path))

    emit(script, (), 0, "", "")
    return lines


def path_to_str(path: Path) -> str:
    out = ""
    for p in path:
        out += f"[{p}]" if isinstance(p, int) else (f".{p}" if out else p)
    return out


def str_to_path(s: str) -> Path:
    parts: list = []
    for name, index in re.findall(r"([^.\[\]]+)|\[(\d+)\]", s):
        parts.append(int(index) if index else name)
    return tuple(parts)


def attach(boxes: list[Box], lines: list[Line]) -> list[Box]:
    """Give each box the line range of its path, drop boxes that match nothing."""
    placed = []
    for box in boxes:
        n = len(box.path)
        hits = [
            i for i, line in enumerate(lines, 1)
            if line.path[:n] == box.path or (line.inline and box.path[: len(line.path)] == line.path)
        ]
        if not hits:
            continue
        box.start, box.end = hits[0], hits[-1]
        placed.append(box)
    placed.sort(key=lambda b: (b.start, -b.end))
    for i, box in enumerate(placed, 1):
        box.number = i
    return placed


# --- plain-language helpers -------------------------------------------------

LOCATIONS = {
    "ApplicationsPerformance": ("App storage (fast)", "HexOS's fast app location — usually your SSD"),
    "ApplicationsCapacity": ("App storage (large)", "HexOS's big app location — usually your hard drives"),
    "Downloads": ("Downloads", "your shared Downloads folder"),
    "Documents": ("Documents", "your shared Documents folder"),
    "Media": ("Media", "your shared Media folder"),
    "Photos": ("Photos", "your shared Photos folder"),
    "Music": ("Music", "your shared Music folder"),
    "Movies": ("Movies", "your shared Movies folder"),
    "Shows": ("Shows", "your shared Shows folder"),
    "Videos": ("Videos", "your shared Videos folder"),
    "VirtualizationPerformance": ("VM storage (fast)", "HexOS's fast virtual machine location"),
    "VirtualizationCapacity": ("VM storage (large)", "HexOS's big virtual machine location"),
    "InstallMedia": ("Install media", "where HexOS keeps installer images"),
    "VirtualDisks": ("Virtual disks", "where HexOS keeps virtual machine disks"),
}

STORAGE_MEANING = {
    "data": "the app's main data",
    "config": "the app's settings",
    "postgres_data": "the app's database",
    "mariadb_data": "the app's database",
    "db": "the app's database",
    "database": "the app's database",
    "logs": "the app's log files",
    "log": "the app's log files",
    "cache": "temporary cache files",
    "transcode": "temporary video conversion files",
    "transcodes": "temporary video conversion files",
    "uploads": "files you upload",
    "backups": "backups the app makes",
    "plugins": "add-ons and plugins",
    "library": "your library",
    "media": "your media",
}

SPEC = re.compile(r"^(\d+)(MBRAM|GBRAM|MB|GB|CORE)$")


def friendly_path(raw: str) -> str:
    """$LOCATION(ApplicationsPerformance)/plex/config -> App storage (fast) › plex › config"""
    def sub(m: re.Match) -> str:
        return LOCATIONS.get(m.group(1), (m.group(1),))[0]

    text = re.sub(r"\$LOCATION\(([^)]+)\)", sub, raw)
    return " › ".join(part for part in text.split("/") if part)


def host_path_inner(value: str) -> str | None:
    m = re.fullmatch(r"\$HOST_PATH\((.*)\)", value)
    return m.group(1) if m else None


def describe_spec(spec: str) -> str:
    if spec == "GPU":
        return "a graphics card (recommended)"
    m = SPEC.match(spec)
    if not m:
        return spec
    n, unit = m.groups()
    return {
        "CORE": f"{n} CPU core{'s' if n != '1' else ''}",
        "MB": f"about {n} MB of free space",
        "GB": f"about {n} GB of free space",
        "MBRAM": f"{n} MB of memory",
        "GBRAM": f"{n} GB of memory",
    }[unit]


def describe_memory(value) -> str:
    if isinstance(value, int):
        return f"{value} MB of memory"
    m = re.fullmatch(r"\$MEMORY\(\s*(\d+)%\s*,\s*(\d+)\s*\)", str(value))
    if m:
        pct, cap = m.groups()
        cap_txt = f"{int(cap) // 1024} GB" if int(cap) % 1024 == 0 else f"{cap} MB"
        return f"{pct}% of your server's memory, but never more than {cap_txt}"
    return str(value)


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


# --- box rules --------------------------------------------------------------


def boxes_for(script: dict, slug: str, title: str) -> list[Box]:
    boxes: list[Box] = []
    add = lambda *a, **k: boxes.append(Box(*a, **k))  # noqa: E731

    add(("version",), "Script format",
        f"Tells HexOS this is a version {script.get('version')} install script, so it knows how to read the rest.")

    meta = script.get("script") or {}
    if meta:
        add(("script",), "Script revision",
            f"This copy of the script is revision {meta.get('version', '?')}. "
            + (f"Latest change: “{meta['changeLog']}”." if meta.get("changeLog") else ""))

    questions = script.get("installation_questions") or []
    if questions:
        asked = [q.get("question", q.get("key")) for q in questions]
        add(("installation_questions",), "Questions you'll be asked",
            f"Before installing, HexOS will ask you for: {_join(asked)}. "
            "Your answers are slotted into the settings further down wherever you see $QUESTION(...).",
            tone="warning")

    req = script.get("requirements") or {}
    if req.get("locations"):
        names = [LOCATIONS.get(l, (l,))[0] for l in req["locations"]]
        add(("requirements", "locations"), "Storage locations it needs",
            f"The app uses these HexOS storage locations: {_join(names)}. "
            "If one isn't set up yet, HexOS will ask you to pick a place for it.", tone="storage")
    if req.get("specifications"):
        add(("requirements", "specifications"), "Minimum hardware",
            f"Recommended minimum: {_join([describe_spec(s) for s in req['specifications']])}.")
    if req.get("permissions"):
        add(("requirements", "permissions"), "Permission to use your folders",
            "Allows the app to read and write files inside the storage locations listed above — and nowhere else.")
    if req.get("ports"):
        ports = [str(p) for p in req["ports"]]
        add(("requirements", "ports"), "Network ports",
            f"The app needs port{'s' if len(ports) > 1 else ''} {_join(ports)} to be free on your server. "
            "A port is like an apartment number for your server's address.", tone="network")

    dirs = script.get("ensure_directories_exists") or []
    if dirs:
        made = [friendly_path(d["path"]) for d in dirs if isinstance(d, dict) and "/" in d.get("path", "")]
        snap = any(isinstance(d, dict) and d.get("snapshot") for d in dirs)
        owned = any(isinstance(d, dict) and d.get("owner") for d in dirs)
        body = "Creates the folders the app needs before it starts"
        body += f": {_join(made)}." if made else "."
        if owned:
            body += " Some folders are handed to a specific system user so the app is allowed to write to them."
        if snap:
            body += " Folders marked “snapshot” are included in HexOS snapshots, so you can roll them back."
        add(("ensure_directories_exists",), "Folders created on install", body, tone="storage")

    values = script.get("app_values") or {}
    for group, answers in values.items():
        if group in ("storage", "network", "resources", "run_as"):
            continue
        if isinstance(answers, dict):
            for key, value in answers.items():
                boxes.extend(_setting_boxes((group, key), key, value, title))

    storage = values.get("storage") or {}
    for key, value in storage.items():
        if key == "additional_storage" and isinstance(value, list):
            mounts = []
            for v in value:
                m = re.fullmatch(r"\$MOUNTED_HOST_PATH\((.*),\s*(\S+)\)", str(v))
                if m:
                    mounts.append(f"{friendly_path(m.group(1))} appears inside the app as {m.group(2)}")
            if mounts:
                add(("app_values", "storage", key), "Your shared folders",
                    f"Gives the app access to your existing files: {_join(mounts)}.", tone="storage")
            continue
        inner = host_path_inner(str(value))
        meaning = STORAGE_MEANING.get(key, f"the app's “{key.replace('_', ' ')}” files")
        if inner:
            body = f"Where {meaning} is saved on your server: {friendly_path(inner)}."
        else:
            body = f"Sets where {meaning} is kept."
        add(("app_values", "storage", key), f"Where {meaning} is saved", body, tone="storage")

    network = values.get("network") or {}
    for key, value in network.items():
        if isinstance(value, dict) and "port_number" in value:
            port = value["port_number"]
            label = key.replace("_port", "").replace("_", " ")
            body = f"Publishes the app's {label} port as {port}."
            if key in ("web_port", "webui_port", "http_port"):
                body = (f"This is how you'll open the app: go to http://your-server-ip:{port} in your browser "
                        "(HexOS also links to it from the app's card).")
            add(("app_values", "network", key), f"{label.capitalize()} port: {port}", body, tone="network")
        elif key == "certificate_id":
            add(("app_values", "network", key), "HTTPS certificate",
                "Uses HexOS's built-in certificate so the app can be opened over https.", tone="network")
        elif key == "host_network":
            add(("app_values", "network", key), "Shares the server's network",
                "The app uses your server's network directly instead of its own private one — "
                "needed for apps that discover devices on your home network.", tone="network")

    resources = values.get("resources") or {}
    limits = resources.get("limits") or {}
    if limits:
        parts = []
        if "cpus" in limits:
            parts.append(f"{limits['cpus']} CPU core{'s' if limits['cpus'] != 1 else ''}")
        if "memory" in limits:
            parts.append(describe_memory(limits["memory"]))
        add(("app_values", "resources", "limits"), "Resource limits",
            f"Caps how much of your server the app can use: {_join(parts)}. "
            "This keeps one busy app from slowing everything else down.")
    if resources.get("gpus"):
        add(("app_values", "resources", "gpus"), "Graphics card access",
            "If your server has a supported graphics card, HexOS shares it with the app "
            "(useful for video conversion or AI features).")

    hooks = script.get("hooks") or []
    if hooks:
        add(("hooks",), "Automatic setup steps",
            "After installing, HexOS runs extra setup steps for you: "
            + _join([h.get("description") or h.get("title") or h.get("id", "setup") for h in hooks]) + ".")

    return boxes


def _setting_boxes(path_tail: tuple, key: str, value, title: str) -> list[Box]:
    path = ("app_values",) + path_tail
    label = key.replace("_", " ")
    if isinstance(value, dict):
        out = []
        for k, v in value.items():
            out.extend(_setting_boxes(path_tail + (k,), k, v, title))
        return out
    text = str(value)
    if text.startswith("$RANDOM_STRING"):
        return [Box(path, f"Auto-generated {label}",
                    f"HexOS makes up a long random {label} during install. "
                    f"It's only used inside {title}, so you never need to know it.")]
    m = re.fullmatch(r"\$QUESTION\((.+)\)", text)
    if m:
        return [Box(path, f"Your answer: {label}",
                    f"Filled in with what you typed for “{m.group(1).replace('_', ' ')}” when you installed.",
                    tone="warning")]
    if "$SERVER_LAN_IP" in text:
        return [Box(path, f"Your server's address ({label})",
                    f"Automatically set to your server's address on your home network ({text.replace('$SERVER_LAN_IP', 'your-server-ip')}).",
                    tone="network")]
    return [Box(path, f"Setting: {label}", f"Sets {label} to {_compact(value)}.")]


def explain(script: dict, slug: str, title: str, notes: list[dict] | None = None) -> tuple[list[Line], list[Box]]:
    lines = render(script)
    boxes = boxes_for(script, slug, title)
    for note in notes or []:
        path = str_to_path(note["path"])
        boxes = [b for b in boxes if b.path != path]
        boxes.append(Box(path, note["title"], note["text"], tone=note.get("tone", "info")))
    return lines, attach(boxes, lines)
