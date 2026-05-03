"""Smoke tests for the rune solver facade."""
from __future__ import annotations

import os
from unittest.mock import patch

import cv2
import numpy as np
import pytest

from src.easymaple.detection.rune_solver import RuneSolver

REF = "assets/rune_panel_template.png"


@pytest.fixture(scope="module")
def monkeypatch_module():
    from _pytest.monkeypatch import MonkeyPatch
    mp = MonkeyPatch()
    yield mp
    mp.undo()


@pytest.fixture(scope="module")
def vit_only_solver(monkeypatch_module):
    """RuneSolver with no API key in env -> ViT only."""
    monkeypatch_module.delenv("ROBOFLOW_API_KEY", raising=False)
    return RuneSolver()


def test_vit_mode_selected_without_api_key(vit_only_solver):
    assert vit_only_solver._mode == "vit"
    assert vit_only_solver._hybrid is None


def test_solve_reference_image_returns_four_downs(vit_only_solver):
    img = cv2.imread(REF)
    result = vit_only_solver.solve(img)
    assert result == ["down", "down", "down", "down"]


def test_hybrid_failure_falls_through_to_vit():
    """If the hybrid backend raises, the facade returns the ViT result silently."""
    with patch.dict(os.environ, {"ROBOFLOW_API_KEY": "fake"}):
        solver = RuneSolver()
    assert solver._mode == "hybrid+vit"
    assert solver._hybrid is not None

    def boom(_image):
        raise RuntimeError("simulated network error")
    solver._hybrid.solve = boom

    img = cv2.imread(REF)
    result = solver.solve(img)
    assert result == ["down", "down", "down", "down"]


def test_empty_input_returns_empty_list(vit_only_solver):
    assert vit_only_solver.solve(np.zeros((0, 0, 3), dtype=np.uint8)) == []
    assert vit_only_solver.solve(None) == []
