"""Tests for Capture detection logic using injected fakes."""

from pathlib import Path

import numpy as np
import pytest

from src.easymaple.modules.capture import Capture
from tests.fakes import FileFrameSource, FixedWindowLocator

FIXTURES = Path(__file__).parent / 'fixtures'


def make_capture(fixture: str = 'test_image_1.PNG') -> Capture:
    """Return a Capture wired to a fixture file, never touching the real screen."""
    return Capture(
        frame_source=FileFrameSource(FIXTURES / fixture),
        window_locator=FixedWindowLocator(),
    )


# ---------------------------------------------------------------------------
# Minimap sanity check — pure logic, no real images needed
# ---------------------------------------------------------------------------

class TestMinimapSanityCheck:
    def setup_method(self):
        self.cap = make_capture()

    def test_valid_bounds_pass(self):
        assert self.cap._mini_map_sanity_check((10, 10), (210, 110)) is True

    def test_too_narrow_fails(self):
        assert self.cap._mini_map_sanity_check((10, 10), (90, 80)) is False

    def test_too_wide_fails(self):
        assert self.cap._mini_map_sanity_check((10, 10), (520, 100)) is False

    def test_too_short_fails(self):
        assert self.cap._mini_map_sanity_check((10, 10), (200, 55)) is False

    def test_too_tall_fails(self):
        assert self.cap._mini_map_sanity_check((10, 10), (200, 520)) is False


# ---------------------------------------------------------------------------
# Minimap bounds detection — requires test_image_1.PNG with visible minimap
# ---------------------------------------------------------------------------

class TestFindMinimapBounds:
    def test_finds_bounds_in_real_frame(self, test_frame):
        cap = make_capture()
        bounds = cap._find_minimap_bounds(test_frame)
        if bounds is None:
            pytest.skip(
                "Minimap not detected in tests/fixtures/test_image_1.PNG — "
                "replace the fixture with a fresh in-game screenshot that shows the minimap."
            )
        mm_tl, mm_br = bounds
        assert mm_tl[0] < mm_br[0], "mm_tl x should be left of mm_br x"
        assert mm_tl[1] < mm_br[1], "mm_tl y should be above mm_br y"

    def test_returns_none_for_blank_frame(self):
        cap = make_capture()
        blank = np.zeros((768, 1366, 3), dtype=np.uint8)
        assert cap._find_minimap_bounds(blank) is None


# ---------------------------------------------------------------------------
# Player detection — requires minimap crop from a real frame
# ---------------------------------------------------------------------------

class TestDetectPlayer:
    def test_returns_none_on_blank_minimap(self):
        cap = make_capture()
        blank = np.zeros((100, 200, 3), dtype=np.uint8)
        assert cap._detect_player(blank) is None

    def test_relative_coords_in_valid_range_when_player_found(self, test_frame):
        cap = make_capture()
        bounds = cap._find_minimap_bounds(test_frame)
        if bounds is None:
            pytest.skip("minimap not detected in test_image_1.PNG")
        mm_tl, mm_br = bounds
        minimap = test_frame[mm_tl[1]:mm_br[1], mm_tl[0]:mm_br[0]]
        pos = cap._detect_player(minimap)
        if pos is None:
            pytest.skip("player icon not visible in test_image_1.PNG minimap")
        x, y = pos
        assert 0.0 <= x <= 1.0, f"player x={x} out of [0, 1]"
        assert y >= 0.0, f"player y={y} is negative"


# ---------------------------------------------------------------------------
# FileFrameSource contract
# ---------------------------------------------------------------------------

class TestFileFrameSource:
    def test_grab_returns_numpy_array(self):
        src = FileFrameSource(FIXTURES / 'test_image_1.PNG')
        frame = src.grab({'left': 0, 'top': 0, 'width': 1366, 'height': 768})
        assert isinstance(frame, np.ndarray)
        assert frame.ndim == 3

    def test_raises_on_missing_file(self):
        with pytest.raises(FileNotFoundError):
            FileFrameSource(FIXTURES / 'nonexistent_fixture.jpg')

    def test_grab_returns_independent_copy(self):
        """Mutating one grab result must not affect the next."""
        src = FileFrameSource(FIXTURES / 'test_image_1.PNG')
        f1 = src.grab({})
        original_pixel = f1[0, 0, 0]
        f1[0, 0, 0] = (original_pixel + 1) % 256
        f2 = src.grab({})
        assert f2[0, 0, 0] == original_pixel
