"""Categories + knowledge-base docs. Same pattern as db.py: real data lives in the
gitignored data/workspaces/<slug>/categories.json / docs.json; a committed .example.json
at the data root lets a fresh clone — or a brand-new empty workspace — render a generic
board with zero setup.

The real files are per-workspace (each board has its own lanes and knowledge base); the
examples are install-wide, so they stay at the data root and are shared by every workspace.
"""
import json
import threading

import workspaces

_lock = threading.Lock()


def data_dir():
    """This workspace's directory — see workspaces.py for why it is resolved
    per call rather than pinned at import."""
    return workspaces.root()


def categories_path():
    return data_dir() / "categories.json"


def _read_json_with_fallback(real_name, example_name):
    real_path = data_dir() / real_name
    path = real_path if real_path.exists() else workspaces.example_path(example_name)
    with open(path) as f:
        return json.load(f)


def read_categories():
    return _read_json_with_fallback("categories.json", "categories.example.json")


def write_categories(categories):
    """Written from the Settings page — categories.json only, docs.json (the
    knowledge-base content itself) stays hand-edited/read-only via this
    feature. Rejects an empty/duplicate id or an empty name outright rather
    than writing a board that would silently confuse the category dropdowns
    that key off `id`."""
    if not isinstance(categories, list):
        raise ValueError("categories must be a list")
    seen_ids = set()
    for cat in categories:
        cat_id = (cat.get("id") or "").strip()
        name = (cat.get("name") or "").strip()
        if not cat_id:
            raise ValueError("every category needs a non-empty id")
        if not name:
            raise ValueError(f"category '{cat_id}' needs a non-empty name")
        if cat_id in seen_ids:
            raise ValueError(f"duplicate category id: {cat_id}")
        seen_ids.add(cat_id)
    target = categories_path()
    with _lock:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".json.tmp")
        with open(tmp, "w") as f:
            json.dump(categories, f, indent=2, sort_keys=True)
        tmp.replace(target)  # atomic on POSIX
    return categories


def set_category_diagram(category_id, diagram):
    """Persists {mermaid, generatedAt} on one category — a generated overarching diagram of
    its subject (see diagram_gen.generate_category_diagram), not a category-definition edit.
    Deliberately bypasses category_management.update_categories: regenerating a diagram isn't
    something "Category history" restores should track alongside real id/name/memories edits."""
    categories = read_categories()
    for cat in categories:
        if cat.get("id") == category_id:
            cat["diagram"] = diagram
            write_categories(categories)
            return cat
    raise ValueError(f"no such category: {category_id}")


def read_doc(doc_id):
    docs = _read_json_with_fallback("docs.json", "docs.example.json")
    return docs.get(doc_id)
