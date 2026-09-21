"""Tiny JSON-file datastore. No ORM, no SQLite — the data is small (a few
hundred documents) and a real database would be unjustified complexity for a
single local user. Guarded by a lock since FastAPI/uvicorn can run handlers
concurrently."""
import json
import threading

import workspaces

_lock = threading.RLock()


def db_path():
    """Resolved per call, not pinned at import: which db.json this is depends
    on the workspace the current request (or background task) is in — see
    workspaces.py."""
    return workspaces.path("db.json")


def _empty():
    return {"jiraTickets": {}, "people": {}, "teamOptions": []}


def read():
    path = db_path()
    with _lock:
        if not path.exists():
            return _empty()
        with open(path) as f:
            return json.load(f)


def write(db):
    path = db_path()
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        with open(tmp, "w") as f:
            json.dump(db, f, indent=2, sort_keys=True)
        tmp.replace(path)  # atomic on POSIX — never leaves a half-written db.json


def update_ticket(key, patch):
    with _lock:
        db = read()
        ticket = db["jiraTickets"].get(key, {"key": key})
        ticket.update(patch)
        db["jiraTickets"][key] = ticket
        write(db)
        return ticket


def add_note(key, text):
    with _lock:
        import datetime
        db = read()
        ticket = db["jiraTickets"].get(key, {"key": key})
        notes = ticket.setdefault("notes", [])
        notes.append({"at": datetime.datetime.now().isoformat(timespec="seconds"), "text": text})
        db["jiraTickets"][key] = ticket
        write(db)
        return ticket


def upsert_person(person_id, data):
    with _lock:
        db = read()
        db["people"][person_id] = data
        write(db)
        return data


def set_team_options(options):
    with _lock:
        db = read()
        db["teamOptions"] = options
        write(db)
        return options
