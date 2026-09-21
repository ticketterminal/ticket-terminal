"""Shared test plumbing for the per-workspace data layout.

Before workspaces, tests patched `db.DB_PATH`, `settings_store.SETTINGS_PATH`
and `content`'s paths at a flat temp directory. Those constants are now
functions resolving through `workspaces`, so a test instead points the whole
data root at a temp directory laid out the way a real install is
(`<tmp>/workspaces/<slug>/`) and enters that workspace on the ContextVar.

Nothing here ever touches the real `data/` tree.
"""
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import workspaces


class TempWorkspaces:
    """A temp data root with one workspace entered.

    `root` is that workspace's directory — the one db.json, settings.json,
    categories.json and category-management.json land in, so a test that used
    to assert against `<tmp>/db.json` asserts against `fixture.root/'db.json'`.
    """

    def __init__(self, slug='default', extra_slugs=()):
        self.slug = slug
        self.temp = tempfile.TemporaryDirectory()
        self.data_root = Path(self.temp.name)
        self.root = self.data_root / 'workspaces' / slug
        for s in (slug, *extra_slugs):
            (self.data_root / 'workspaces' / s).mkdir(parents=True, exist_ok=True)
        self._patch = patch.object(workspaces, 'DATA_ROOT', self.data_root)
        self._entered = None

    def start(self):
        self._patch.start()
        self._entered = workspaces.use(self.slug)
        self._entered.__enter__()
        return self

    def register(self, slug, name=''):
        """Add a workspace to the registry as `workspaces.create` would, but
        without caring whether the slug is reserved — some tests need a second
        workspace whatever it is called."""
        registry = workspaces.read_registry()
        if not any(w['slug'] == slug for w in registry['workspaces']):
            registry['workspaces'].append(
                {'slug': slug, 'name': name or slug, 'createdAt': workspaces.now(), 'lastSyncAt': ''})
        workspaces.write_registry(registry)
        (self.data_root / 'workspaces' / slug).mkdir(parents=True, exist_ok=True)

    def stop(self):
        if self._entered is not None:
            self._entered.__exit__(None, None, None)
            self._entered = None
        self._patch.stop()
        self.temp.cleanup()
