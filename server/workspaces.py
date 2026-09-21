"""Named workspaces: one install, several boards, switched — never merged.

A workspace owns everything that is one board's state: its tracker connection
(settings.json), its tickets (db.json), its categories/docs, its category-
management history and its terminal transcripts. Those all live under
`data/workspaces/<slug>/`; the shipped `*.example.json` files stay at the data
root, since they are the same for every workspace.

Why a ContextVar and not a module-level "current workspace": the server really
does handle several workspaces at once. A terminal WebSocket can be attached to
workspace A for an hour while the board polls workspace B every 60 seconds, and
a background sync for the default workspace runs underneath both. A global
would make those three trample each other. A `contextvars.ContextVar` is set
per request (see main.WorkspaceMiddleware), is inherited by tasks created
inside that request, and — the reason it beats a thread-local — is carried into
`asyncio.to_thread`, which is how every sync actually runs.

Call sites keep their old shape: `db.read()` still takes no arguments, it just
resolves its path through here.
"""
import contextlib
import contextvars
import datetime
import json
import re
import shutil
import threading
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
# Patched by tests to a temp directory. Everything below resolves through it,
# so a test never touches the real data/ tree.
DATA_ROOT = BASE_DIR / "data"

DEFAULT_SLUG = "default"
RESERVED_SLUGS = {"default"}
# Bounded: a slug becomes a directory name, and an over-long one fails mkdir
# with OSError rather than the ValueError callers handle.
MAX_SLUG_LENGTH = 40
SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def valid_slug(slug: str) -> bool:
    return bool(slug) and len(slug) <= MAX_SLUG_LENGTH and bool(SLUG_PATTERN.match(slug))

# What `migrate_if_needed` lifts out of data/ into data/workspaces/default/.
MIGRATED_ENTRIES = ("db.json", "settings.json", "categories.json", "docs.json",
                    "category-management.json", "sessions")

_lock = threading.RLock()
# None means "nothing asked for a particular workspace" — resolved to the
# registry's default, so code paths with no request behind them (imports, a
# direct unit-test call) keep working unchanged.
_active = contextvars.ContextVar("workspace_slug", default=None)


class UnknownWorkspace(ValueError):
    """Raised for a slug that is not in the registry — a 404, not a 500."""


def now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


# ---------- layout ----------

def data_root() -> Path:
    return DATA_ROOT


def workspaces_dir() -> Path:
    return DATA_ROOT / "workspaces"


def registry_path() -> Path:
    return DATA_ROOT / "workspaces.json"


def example_path(name: str) -> Path:
    """The shipped `*.example.json` files are install-wide, not per-workspace."""
    return DATA_ROOT / name


def root(slug: str | None = None) -> Path:
    """The directory holding one workspace's whole state."""
    return workspaces_dir() / (slug or current())


def path(name: str, slug: str | None = None) -> Path:
    return root(slug) / name


# ---------- registry ----------

def _default_entry() -> dict:
    return {"slug": DEFAULT_SLUG, "name": "Default", "createdAt": "", "lastSyncAt": ""}


def read_registry() -> dict:
    """`{"defaultWorkspace": slug, "workspaces": [{slug,name,createdAt,lastSyncAt}]}`.

    A missing or unreadable file is not an error: an install that has never
    seen this feature has exactly one workspace, and synthesizing it here
    (rather than writing a file on first read) keeps a fresh clone unchanged
    on disk until the operator actually makes a second workspace.
    """
    with _lock:
        data = {}
        if registry_path().exists():
            try:
                data = json.loads(registry_path().read_text()) or {}
            except (ValueError, OSError):
                data = {}
    entries = [w for w in (data.get("workspaces") or []) if isinstance(w, dict) and w.get("slug")]
    if not entries:
        entries = [_default_entry()]
    slugs = {w["slug"] for w in entries}
    default = data.get("defaultWorkspace") or ""
    if default not in slugs:
        default = entries[0]["slug"]
    return {"defaultWorkspace": default, "workspaces": entries}


def write_registry(registry: dict) -> dict:
    with _lock:
        registry_path().parent.mkdir(parents=True, exist_ok=True)
        tmp = registry_path().with_suffix(".json.tmp")
        tmp.write_text(json.dumps(registry, indent=2, sort_keys=True))
        tmp.replace(registry_path())  # atomic on POSIX
    return registry


def list_workspaces() -> list[dict]:
    return read_registry()["workspaces"]


def default_slug() -> str:
    return read_registry()["defaultWorkspace"]


def exists(slug: str) -> bool:
    return any(w["slug"] == slug for w in read_registry()["workspaces"])


def resolve(slug: str | None) -> str:
    """Map a slug off the wire to a real one. An empty slug and the literal
    `default` both mean "whatever this install calls its default workspace",
    so `#/w/default/…` is a link that works on any install (see the operator
    note in the README about renaming the default workspace by hand)."""
    slug = (slug or "").strip()
    if not slug or slug == DEFAULT_SLUG:
        return default_slug()
    # Re-validated on the way in AND on the way out of the registry: the README
    # tells operators to hand-edit workspaces.json to rename the default, so a
    # slug containing "/" or ".." can reach here without ever passing create().
    if not valid_slug(slug) or not exists(slug):
        raise UnknownWorkspace(slug)
    return slug


def create(slug: str, name: str = "") -> dict:
    slug = (slug or "").strip().lower()
    if not valid_slug(slug):
        raise ValueError(f"slug must be lowercase letters, digits and hyphens, at most {MAX_SLUG_LENGTH} characters")
    if slug in RESERVED_SLUGS:
        raise ValueError("'default' is a reserved slug")
    with _lock:
        registry = read_registry()
        if any(w["slug"] == slug for w in registry["workspaces"]):
            raise ValueError(f"workspace '{slug}' already exists")
        entry = {"slug": slug, "name": (name or "").strip() or slug,
                 "createdAt": now(), "lastSyncAt": ""}
        # Directory first: a registry entry whose directory does not exist is a
        # ghost that every later read of the registry has to cope with, and the
        # failure it causes is an unhandled OSError rather than a 400.
        try:
            root(slug).mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise ValueError(f"could not create the workspace directory: {error}") from error
        registry["workspaces"].append(entry)
        write_registry(registry)
    return dict(entry)


def get_last_sync_at(slug: str) -> str:
    for w in read_registry()["workspaces"]:
        if w["slug"] == slug:
            return w.get("lastSyncAt") or ""
    return ""


def set_last_sync_at(slug: str, when: str | None = None) -> str:
    """Recorded whether the sync succeeded or not — a failed sync still counts
    as "recently attempted", otherwise a broken tracker would re-trigger a full
    sync on every switch back to that workspace."""
    stamp = when or now()
    with _lock:
        registry = read_registry()
        for w in registry["workspaces"]:
            if w["slug"] == slug:
                w["lastSyncAt"] = stamp
                break
        else:
            registry["workspaces"].append({"slug": slug, "name": slug, "createdAt": now(), "lastSyncAt": stamp})
        write_registry(registry)
    return stamp


# ---------- the active workspace ----------

def current() -> str:
    return _active.get() or default_slug()


def active_override() -> str | None:
    """What the ContextVar literally holds — None when nothing set it."""
    return _active.get()


@contextlib.contextmanager
def use(slug: str):
    """Pin every path lookup inside this block to one workspace. Used by the
    request middleware, by background work (the sync timer, `sync-if-stale`),
    and by tests."""
    token = _active.set(slug)
    try:
        yield slug
    finally:
        _active.reset(token)


# ---------- migration ----------

def migrate_if_needed() -> dict:
    """Lift a pre-workspaces `data/` into `data/workspaces/default/`.

    Runs at server startup. The files are MOVED, never copied-and-re-synced —
    the reference install holds thousands of tickets and a fresh sync of those
    takes about an hour. The `*.example.json` files stay where they are; they
    are install-wide.

    **The registry file is the completion marker, and it is written last.**
    Not `data/db.json`'s absence: db.json is the first thing moved, so using it
    as the guard meant a crash part-way through left the remaining files
    stranded at the old root forever, with the server then starting cleanly on
    empty defaults and silently showing blank settings and categories. Guarding
    on the registry instead makes an interrupted migration resume on the next
    start. Each entry is moved only when its destination is free, so resuming
    never clobbers what an earlier attempt already moved, and a file that
    vanishes mid-move (a second process racing this one) is skipped rather than
    crashing startup — the other process has it.
    """
    result = {"migrated": False, "moved": []}
    with _lock:
        if registry_path().exists():
            return result
        legacy = [entry for entry in MIGRATED_ENTRIES if (DATA_ROOT / entry).exists()]
        if not legacy and not workspaces_dir().exists():
            return result  # fresh install: leave the tree byte-identical until someone needs a workspace

        destination = workspaces_dir() / DEFAULT_SLUG
        destination.mkdir(parents=True, exist_ok=True)
        for entry in MIGRATED_ENTRIES:
            source, target = DATA_ROOT / entry, destination / entry
            if not source.exists() or target.exists():
                continue
            try:
                shutil.move(str(source), str(target))
            except FileNotFoundError:
                continue  # a concurrently starting process moved it first
            result["moved"].append(entry)

        # Rebuild from what is actually on disk, so a registry lost or deleted
        # while workspaces existed comes back naming all of them rather than
        # hiding every workspace but the default.
        slugs = sorted(d.name for d in workspaces_dir().iterdir() if d.is_dir())
        if DEFAULT_SLUG not in slugs:
            slugs.insert(0, DEFAULT_SLUG)
        write_registry({
            "defaultWorkspace": DEFAULT_SLUG,
            "workspaces": [{"slug": slug, "name": slug.replace("-", " ").title(),
                            "createdAt": now(), "lastSyncAt": ""} for slug in slugs],
        })
        result["migrated"] = True
    print(f"[workspaces] moved {', '.join(result['moved']) or 'nothing'} into "
          f"data/workspaces/{DEFAULT_SLUG}/")
    return result
