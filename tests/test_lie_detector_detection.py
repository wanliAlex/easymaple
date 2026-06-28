"""Tests for Lie Detector mini-game template detection in the notifier.

Guards the templates and matching threshold against regressions using real
in-game screenshots committed under tests/fixtures/.
"""

import os

import cv2
import pytest

from src.easymaple.common import utils
from src.easymaple.modules import notifier

FIXTURES = os.path.join(os.path.dirname(__file__), 'fixtures')


def _gray(name):
    path = os.path.join(FIXTURES, name)
    img = cv2.imread(path)
    assert img is not None, f'fixture not found: {path}'
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


@pytest.fixture
def prep_screen():
    return _gray('lie_detector_prep_screen.png')


@pytest.fixture
def progress_screen():
    return _gray('lie_detector_in_progress_screen.png')


def test_prep_template_matches_prep_screen(prep_screen):
    score = utils.match_score(prep_screen, notifier.LIE_DETECTOR_PREP_TEMPLATE)
    assert score >= notifier.LIE_DETECTOR_THRESHOLD


def test_prep_template_does_not_match_progress_screen(progress_screen):
    score = utils.match_score(progress_screen, notifier.LIE_DETECTOR_PREP_TEMPLATE)
    assert score < 0.5


def test_progress_template_matches_progress_screen(progress_screen):
    score = utils.match_score(progress_screen, notifier.LIE_DETECTOR_PROGRESS_TEMPLATE)
    assert score >= notifier.LIE_DETECTOR_THRESHOLD


def test_progress_template_does_not_match_prep_screen(prep_screen):
    score = utils.match_score(prep_screen, notifier.LIE_DETECTOR_PROGRESS_TEMPLATE)
    assert score < 0.5
