"""Tests for Configurable.load_config — must merge saved pickles over
defaults so new DEFAULT_CONFIG keys don't break old saves."""
import os
import pickle

from src.easymaple.common import interfaces
from src.easymaple.common.interfaces import Configurable


class _Sample(Configurable):
    DEFAULT_CONFIG = {'a': 1, 'b': 2, 'c': 3}


def _seed_pickle(tmp_path, monkeypatch, target, payload):
    settings_dir = tmp_path / '.settings'
    settings_dir.mkdir()
    monkeypatch.setattr(interfaces, 'SETTINGS_DIR', str(settings_dir))
    with open(os.path.join(str(settings_dir), target), 'wb') as f:
        pickle.dump(payload, f)


def test_old_pickle_picks_up_new_default_keys(tmp_path, monkeypatch):
    """User upgraded; saved pickle predates the 'c' key. Must not raise,
    and 'c' must take its default."""
    _seed_pickle(tmp_path, monkeypatch, 'sample_old', {'a': 10, 'b': 20})
    cfg = _Sample('sample_old')
    assert cfg.config == {'a': 10, 'b': 20, 'c': 3}


def test_saved_values_override_defaults(tmp_path, monkeypatch):
    """Pickle is the source of truth for keys it contains."""
    _seed_pickle(tmp_path, monkeypatch, 'sample_full', {'a': 99, 'b': 88, 'c': 77})
    cfg = _Sample('sample_full')
    assert cfg.config == {'a': 99, 'b': 88, 'c': 77}


def test_missing_pickle_writes_defaults(tmp_path, monkeypatch):
    """No pickle yet -> defaults are saved so subsequent loads see them."""
    settings_dir = tmp_path / '.settings'
    settings_dir.mkdir()
    monkeypatch.setattr(interfaces, 'SETTINGS_DIR', str(settings_dir))

    cfg = _Sample('sample_new')
    assert cfg.config == {'a': 1, 'b': 2, 'c': 3}
    assert os.path.isfile(os.path.join(str(settings_dir), 'sample_new'))


def test_extra_keys_in_pickle_preserved(tmp_path, monkeypatch):
    """If a key was removed from DEFAULT_CONFIG but the pickle still has it,
    keep it — matches prior behavior (no destructive cleanup on load)."""
    _seed_pickle(tmp_path, monkeypatch, 'sample_extra', {'a': 1, 'b': 2, 'c': 3, 'old_key': 'x'})
    cfg = _Sample('sample_extra')
    assert cfg.config['old_key'] == 'x'
