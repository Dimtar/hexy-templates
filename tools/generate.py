"""Draft a HexOS install script from a TrueNAS app's questions.yaml.

TrueNAS describes every setting an app accepts in questions.yaml, and a HexOS
install script's `app_values` is a partial answer to those same questions. The
draft fills in only what HexOS needs to decide for the user — where data lives,
which port the web UI gets, resource limits, generated secrets — and leaves
everything else at the TrueNAS default, which is how the official HexOS scripts
are written too.

A draft is a starting point, not a tested script: every generated app is marked
`status: draft` until someone has installed it on a real HexOS box.
"""

from __future__ import annotations

import re

from truenas import UpstreamApp

SCRIPT_VERSION = 5

# Storage keys that are really one of the user's shared HexOS folders, so the
# app sees the same files as everything else instead of a private copy.
SHARED_LOCATIONS = {
    "media": "Media",
    "music": "Music",
    "movies": "Movies",
    "tv": "Shows",
    "shows": "Shows",
    "series": "Shows",
    "photos": "Photos",
    "pictures": "Photos",
    "videos": "Videos",
    "recordings": "Videos",
    "downloads": "Downloads",
    "documents": "Documents",
    "books": "Documents",
    "ebooks": "Documents",
    "audiobooks": "Media",
    "podcasts": "Media",
}

# Bulky, rebuildable data goes to the capacity pool and is not snapshotted.
CAPACITY_KEYS = re.compile(r"(^|_)(cache|logs?|transcodes?|tmp|temp|backups?)($|_)")

# Database engines in TrueNAS apps run as uid 999, which is `netdata` on HexOS.
DATABASE_KEYS = re.compile(r"(postgres|pg|mariadb|mysql|mongo|db|database)")

# Secrets an app only needs internally can be invented at install time; secrets
# that must match something outside the box (an API token, an OAuth client)
# have to be asked for.
GENERATED_SECRET = re.compile(
    r"(db_|database|postgres|mariadb|mysql|redis|root_password|jwt|session|encryption|secret|app_key|master_key|rpc_password|signing)"
)
EXTERNAL_SECRET = re.compile(r"(client_secret|api_key|token|passkey)")

# Settings that ask "what address will people use to reach this app?" On a home
# server that is the box's LAN address and the app's published web port.
SELF_URL_KEYS = {
    "app_url", "base_url", "frontend_url", "nextauth_url", "external_url", "root_url",
    "instance_url", "server_url", "site_url", "public_url",
}
SELF_HOST_KEYS = {"hostname", "server_ip", "host_ip", "lan_ip"}

NOT_APP_GROUPS = {"labels", "resources", "network", "storage", "TZ", "run_as", "image"}

GPU_CATEGORIES = {"media", "ai"}

# Media apps get the user's shared Media folder so they can see their library.
MEDIA_CATEGORY = "media"


def _attrs(schema: dict) -> list[dict]:
    return schema.get("attrs", []) if isinstance(schema, dict) else []


def _find(attrs: list[dict], name: str) -> dict | None:
    return next((a for a in attrs if a["variable"] == name), None)


def _owner_for(app: UpstreamApp, key: str) -> dict | None:
    if DATABASE_KEYS.search(key):
        return {"user": "netdata", "group": "docker"}
    contexts = app.meta.get("run_as_context") or []
    if contexts and contexts[0].get("uid") == 568:
        return {"user": "apps"}
    return None


def _question_for(key: str, schema: dict) -> dict:
    kind = schema.get("type", "string")
    q: dict = {
        "question": schema.get("label") or key.replace("_", " ").capitalize(),
        "type": "text",
        "key": key,
        "required": True,
    }
    if schema.get("description"):
        q["description"] = schema["description"]
    if schema.get("enum"):
        q["type"] = "select"
        q["options"] = [{"text": o.get("description", str(o["value"])), "value": o["value"]} for o in schema["enum"]]
    elif kind == "int":
        q["type"] = "number"
    elif kind == "boolean":
        q["type"] = "boolean"
    elif schema.get("private"):
        q["type"] = "password"
    return q


def _required_values(attrs: list[dict], questions: list[dict], taken: set[str], web_port: int | None) -> dict:
    """Answer every required setting that has no default."""
    out: dict = {}
    for attr in attrs:
        key, schema = attr["variable"], attr["schema"]
        if schema.get("show_if") or schema.get("hidden"):
            continue
        if schema.get("type") == "dict":
            nested = _required_values(_attrs(schema), questions, taken, web_port)
            if nested:
                out[key] = nested
            continue
        if not schema.get("required") or schema.get("default") not in (None, "") or schema.get("type") == "list":
            continue
        if schema.get("private") and GENERATED_SECRET.search(key) and not EXTERNAL_SECRET.search(key):
            out[key] = "$RANDOM_STRING(16)" if "password" in key else "$RANDOM_STRING(32)"
            continue
        if key in SELF_URL_KEYS and web_port:
            out[key] = f"http://$SERVER_LAN_IP:{web_port}"
            continue
        if key in SELF_HOST_KEYS:
            out[key] = "$SERVER_LAN_IP"
            continue
        qkey = key
        n = 2
        while qkey in taken:
            qkey, n = f"{key}_{n}", n + 1
        taken.add(qkey)
        questions.append(_question_for(qkey, schema))
        out[key] = f"$QUESTION({qkey})"
    return out


def _ports(network: dict | None) -> tuple[dict, list[int]]:
    values, ports = {}, []
    for attr in _attrs((network or {}).get("schema", {})):
        sub = _attrs(attr["schema"])
        number, mode = _find(sub, "port_number"), _find(sub, "bind_mode")
        if not number or "default" not in number["schema"]:
            continue
        if mode and mode["schema"].get("default", "published") != "published":
            continue
        port = int(number["schema"]["default"])
        values[attr["variable"]] = {"bind_mode": "published", "port_number": port}
        ports.append(port)
    return values, ports


def _storage(app: UpstreamApp, storage: dict | None) -> tuple[dict, list[dict], list[str]]:
    values: dict = {}
    dirs: list[dict] = []
    locations: list[str] = []

    def use(location: str) -> None:
        if location not in locations:
            locations.append(location)

    for attr in _attrs((storage or {}).get("schema", {})):
        key, schema = attr["variable"], attr["schema"]
        if key == "additional_storage" or schema.get("type") != "dict":
            continue
        kind = _find(_attrs(schema), "type")
        if not kind:
            continue
        options = [o["value"] for o in kind["schema"].get("enum", [])]
        if "host_path" not in options or kind["schema"].get("default") in ("temporary", "tmpfs", "anonymous"):
            continue

        if key in SHARED_LOCATIONS:
            location = SHARED_LOCATIONS[key]
            use(location)
            values[key] = f"$HOST_PATH($LOCATION({location}))"
            continue

        location = "ApplicationsCapacity" if CAPACITY_KEYS.search(key) else "ApplicationsPerformance"
        use(location)
        path = f"$LOCATION({location})/{app.slug}/{key}"
        entry: dict = {"path": path}
        owner = _owner_for(app, key)
        if owner:
            entry["owner"] = owner
        if location == "ApplicationsPerformance":
            entry["snapshot"] = {"id": key}
        dirs.append(entry)
        values[key] = f"$HOST_PATH({path})"

    if MEDIA_CATEGORY in (app.meta.get("categories") or []) and "Media" not in locations:
        use("Media")
        values["additional_storage"] = ["$MOUNTED_HOST_PATH($LOCATION(Media), /media)"]

    # Parents first, so HexOS creates the tree top-down.
    parents: list[dict] = []
    for location in locations:
        if location.startswith("Applications"):
            parents.append({"path": f"$LOCATION({location})"})
            if any(d["path"].startswith(f"$LOCATION({location})/") for d in dirs):
                parents.append({"path": f"$LOCATION({location})/{app.slug}"})
        else:
            parents.append({"path": f"$LOCATION({location})", "network_share": True})
    return values, parents + dirs, locations


def _resources(app: UpstreamApp, resources: dict | None) -> tuple[dict, int]:
    limits = _find(_attrs((resources or {}).get("schema", {})), "limits")
    sub = _attrs(limits["schema"]) if limits else []
    cpus_attr, mem_attr = _find(sub, "cpus"), _find(sub, "memory")
    cpus = int(cpus_attr["schema"].get("default", 2)) if cpus_attr else 2
    memory = int(mem_attr["schema"].get("default", 4096)) if mem_attr else 4096
    out: dict = {"limits": {"cpus": cpus, "memory": f"$MEMORY(10%, {memory})"}}
    has_gpus = _find(_attrs((resources or {}).get("schema", {})), "gpus")
    if has_gpus and GPU_CATEGORIES & set(app.meta.get("categories") or []):
        out["gpus"] = "$GPU_CONFIG()"
    return out, cpus


def generate(app: UpstreamApp) -> dict:
    groups = {q["variable"]: q for q in app.questions}
    installation_questions: list[dict] = []
    app_values: dict = {}

    network_values, ports = _ports(groups.get("network"))

    taken: set[str] = set()
    for name, group in groups.items():
        if name in NOT_APP_GROUPS or group["schema"].get("type") != "dict":
            continue
        answers = _required_values(_attrs(group["schema"]), installation_questions, taken, ports[0] if ports else None)
        if answers:
            app_values[name] = answers

    storage_values, dirs, locations = _storage(app, groups.get("storage"))
    if storage_values:
        app_values["storage"] = storage_values

    if network_values:
        app_values["network"] = network_values

    resources, cpus = _resources(app, groups.get("resources"))
    app_values["resources"] = resources

    requirements: dict = {"locations": locations, "specifications": [f"{cpus}CORE"]}
    if locations:
        requirements["permissions"] = ["READ_WRITE_LOCATIONS"]
    if ports:
        requirements["ports"] = ports

    script: dict = {
        "version": SCRIPT_VERSION,
        "script": {
            "version": "0.1.0",
            "changeLog": f"Auto-generated draft from TrueNAS {app.name} {app.meta.get('version')}",
        },
    }
    if installation_questions:
        script["installation_questions"] = installation_questions
    script["requirements"] = requirements
    if dirs:
        script["ensure_directories_exists"] = dirs
    script["app_values"] = app_values
    return script
