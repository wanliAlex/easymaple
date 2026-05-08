"""Tests for recent-files cache helpers."""
import os, sys, json, tempfile, importlib
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


def _reload_cache_with_tmpdir(tmpdir):
    """Reloads cache module pointing at a temp resources dir."""
    from src.easymaple.common import config
    config.RESOURCES_DIR = tmpdir
    from src.easymaple.common import cache
    importlib.reload(cache)
    return cache


def test_add_recent_dedupes_and_trims_to_limit(tmp_path, monkeypatch):
    cache = _reload_cache_with_tmpdir(str(tmp_path))

    # Create 7 fake routine files on disk so the existence filter doesn't drop them
    paths = []
    for i in range(7):
        p = tmp_path / f"r{i}.csv"
        p.write_text("# fake")
        paths.append(str(p))

    for p in paths:
        cache.add_recent_routine(p)

    recent = cache.get_recent_routines()
    assert len(recent) == cache.RECENT_LIMIT == 5
    # most-recent-first
    assert recent[0] == paths[-1]
    assert recent[-1] == paths[-cache.RECENT_LIMIT]


def test_add_recent_dedupes_existing_entry(tmp_path):
    cache = _reload_cache_with_tmpdir(str(tmp_path))

    a = tmp_path / "a.py"; a.write_text("# fake")
    b = tmp_path / "b.py"; b.write_text("# fake")

    cache.add_recent_command_book(str(a))
    cache.add_recent_command_book(str(b))
    cache.add_recent_command_book(str(a))  # re-touch a

    recent = cache.get_recent_command_books()
    assert recent == [str(a), str(b)]


def test_get_recent_filters_missing_files(tmp_path):
    cache = _reload_cache_with_tmpdir(str(tmp_path))

    a = tmp_path / "a.py"; a.write_text("# fake")
    cache.add_recent_command_book(str(a))
    cache.add_recent_command_book(str(tmp_path / "missing.py"))  # never created

    recent = cache.get_recent_command_books()
    assert recent == [str(a)]
