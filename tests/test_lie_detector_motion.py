"""Tests for the motion-based Lie Detector detector (synthetic, no clips).

They pin down the properties the design relies on: integer alignment, the
duplicate-skipping reference picker, the fast input builder matching the
reference one, the leak-proof exclusion zones (the net provably cannot see a
cursor), the grid tracker following weak moving evidence, and the runtime
solver's WAIT -> ACQUIRE -> TRACK flow on a panning synthetic field.
"""
import cv2
import numpy as np
import pytest

from src.easymaple.detection import lie_detector_motion as LM

RNG = np.random.RandomState(7)


def test_shift_int_moves_content():
    img = np.zeros((10, 12), np.float32)
    img[2, 3] = 1.0
    out = LM.shift_int(img, 4, -1)
    assert out[1, 7] == 1.0 and out.sum() == 1.0


def test_pick_refs_skips_duplicates_outward():
    dup = np.zeros(20, bool)
    dup[[6, 12]] = True
    # offsets -4,-2,+2,+4 around t=10: t+2=12 is a duplicate -> step out to 13
    assert LM.pick_refs(10, dup, 20, (-4, -2, 2, 4)) == [6 - 1, 8, 13, 14]
    assert LM.pick_refs(1, dup, 20, (-4, -2, 2, 4)) is None


def _frames(h=60, w=80, n=5):
    return [RNG.randint(0, 255, (h, w, 3)).astype(np.uint8) for _ in range(n)]


def test_build_input_fast_matches_reference():
    cur, *refs = _frames()
    shifts = [(3.4, -2.6), (-7.0, 1.2), (0.4, 0.4), (12.0, 9.0)]
    hc = [(30.0, 20.0)]
    hr = [[(10.0, 10.0)], [], [(70.0, 50.0), (5.0, 50.0)], [(np.nan, np.nan)]]
    x1, v1 = LM.build_input(cur, refs, shifts, hc, hr)
    x2, v2 = LM.build_input_fast(cur, refs, shifts, hc, hr)
    assert np.abs(x1 - x2).max() < 1e-5
    assert (v1 == v2).all()


def test_pixels_a_reference_does_not_cover_are_unusable():
    """Texture that entered at the wall within the reference span is not in
    the older references: those outputs are not used. (Filling them from a
    newer reference was tried 2026-10-13: no measurable gain, and the net
    reads the filled strip as shape — it doubled a pull toward that wall.)"""
    cur, *refs = _frames()
    shifts = [(12, 0), (8, 0), (4, 0), (1, 0)]      # oldest -> newest, all from the left
    x, valid = LM.build_input_fast(cur, refs, shifts, [], [[], [], [], []])
    assert np.all(x[3:6, :, :12] == 0), "uncovered differences are zero"
    assert not valid[:, :12 + LM.NET_RF_R].any()
    assert valid[10:50, 12 + LM.NET_RF_R:70].all()


def test_reference_cursor_pixels_never_reach_the_input():
    """Randomising a reference's pixels inside its cursor disc changes no
    input value."""
    cur, *refs = _frames()
    shifts = [(12, 0), (8, 0), (4, 0), (1, 0)]
    hr = [[], [(6.0, 30.0)], [], [(30.0, 20.0)]]
    x1, _ = LM.build_input_fast(cur, refs, shifts, [], hr)
    refs2 = [r.copy() for r in refs]
    yy, xx = np.mgrid[0:60, 0:80]
    for r, hl in zip(refs2, hr):
        for (hx, hy) in hl:
            m = np.hypot(xx - hx, yy - hy) <= LM.HOLE_R
            r[m] = RNG.randint(0, 255, (int(m.sum()), 3))
    x2, _ = LM.build_input_fast(cur, refs2, shifts, [], hr)
    assert np.array_equal(x1, x2)


def test_valid_excludes_receptive_field_around_every_cursor():
    cur, *refs = _frames()
    shifts = [(5, 0), (0, 0), (0, 0), (-5, 0)]
    hc = [(40.0, 30.0)]
    hr = [[(20.0, 30.0)], [], [], []]           # ref 0's cursor lands at (25, 30)
    x, valid = LM.build_input_fast(cur, refs, shifts, hc, hr)
    yy, xx = np.mgrid[0:60, 0:80]
    for (cx, cy) in [(40, 30), (25, 30)]:
        near = np.hypot(xx - cx, yy - cy) < LM.EXCL_R - 0.5
        assert not valid[near].any()
        blank = np.hypot(xx - cx, yy - cy) <= LM.HOLE_R - 1
        assert np.all(x[:, blank] == 0)


def test_net_cannot_see_inside_blanked_discs():
    torch = pytest.importorskip("torch")
    torch.manual_seed(0)
    net = LM.make_net(4).eval()
    cur, *refs = _frames(96, 128)
    x, valid = LM.build_input_fast(cur, refs, [(2, 1), (0, 0), (1, 0), (-3, 2)],
                                   [(60.0, 48.0)], [[(50.0, 40.0)], [], [], []])
    blank = np.abs(x).sum(0) == 0
    x2 = x.copy()
    x2[:, blank] = RNG.normal(0, 1, (x.shape[0], int(blank.sum()))).astype(np.float32)
    with torch.no_grad():
        a = net(torch.from_numpy(x)[None])[0, 0].numpy()
        b = net(torch.from_numpy(x2)[None])[0, 0].numpy()
    assert valid.any()
    assert np.abs(a - b)[valid].max() == 0.0


def test_grid_tracker_follows_weak_moving_evidence():
    h, w = 100, 160
    trk = LM.GridTracker((h * 2, w * 2), (40.0, 100.0), cell=2, q=4.5, beta=0.8)
    yy, xx = np.mgrid[0:h, 0:w]
    errs = []
    for k in range(60):
        px, py = 20 + 1.5 * k, 50 + 15 * np.sin(k / 10)       # grid coords
        ev = 1.2 * np.exp(-((xx - px) ** 2 + (yy - py) ** 2) / (2 * 8 ** 2))
        ev += RNG.normal(0, 0.6, (h, w))                       # per-frame clutter
        x, y = trk.step(ev.astype(np.float32))
        errs.append(np.hypot(x / 2 - px, y / 2 - py))
    assert np.median(errs[10:]) < 8          # within the evidence bump (sigma 8 cells)


def test_evidence_over_few_usable_pixels_is_not_inflated():
    h, w = 200, 300
    logit = np.zeros((h, w), np.float32)
    valid = np.ones((h, w), bool)
    yy, xx = np.mgrid[0:h, 0:w]

    def disc(x, y):
        return np.hypot(xx - x, yy - y) <= 12

    logit[disc(80, 100)] = 1.0                    # mid-field
    logit[disc(240, 100)] = 1.0                   # the same, but nothing else usable around it
    valid[:, 190:] = False
    valid[disc(240, 100)] = True
    A = LM.evidence_grid(logit, valid)
    mid, few = A[100 // LM.GRID, 80 // LM.GRID], A[100 // LM.GRID, 240 // LM.GRID]
    assert 0 < mid and few < 3 * mid              # a plain mean over few pixels: ~8x


def _bump(shape, x, y, a=1.0, s=4.0):
    yy, xx = np.mgrid[0:shape[0], 0:shape[1]]
    return (a * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * s ** 2))).astype(np.float32)


def test_wall_floor_damps_few_pixel_means_at_the_walls_only():
    h, w = 200, 300
    logit = _bump((h, w), 4, 4, a=2.0) + _bump((h, w), 150, 100, a=2.0)   # corner spike, mid-field shape
    valid = np.ones((h, w), bool)
    plain = LM.evidence_grid(logit, valid, wall_floor=0.0)
    walls = LM.evidence_grid(logit, valid)
    c = 4 // LM.GRID
    assert 0 < walls[c, c] < plain[c, c]          # the corner disc is mostly outside the field
    inner = slice(LM.WALL_BAND // LM.GRID + 2, -(LM.WALL_BAND // LM.GRID + 2))
    np.testing.assert_allclose(walls[inner, inner], plain[inner, inner], atol=1e-6)


def test_clutter_background_suppresses_what_stays_put_not_the_moving_shape():
    shape = (60, 120)
    bg = LM.ClutterBackground(tau=1.0, k=0.5)
    for k in range(60):                                       # 2 s at 30 Hz
        sx = 10 + 1.5 * k                                     # the shape moves on
        out = bg.apply(_bump(shape, 30, 20) + _bump(shape, sx, 45), k / 30.0)
    assert out[20, 30] < 0.65                                 # still clutter: ~43% off
    assert out[45, int(round(sx))] > 0.85                     # the shape: nearly intact


def test_clutter_background_is_not_rebuilt_from_one_frame_after_a_stall():
    shape = (60, 120)
    bg = LM.ClutterBackground(tau=0.5, k=0.5)
    for k in range(30):
        bg.apply(_bump(shape, 30, 20), k / 30.0)
    # the stream stalls for 2 s; the first frame after it shows the shape elsewhere
    bg.apply(_bump(shape, 30, 20) + _bump(shape, 90, 40), 1.0 + 2.0)
    out = bg.apply(_bump(shape, 30, 20) + _bump(shape, 91, 40), 3.0 + 1 / 30.0)
    assert out[40, 91] > 0.85                                 # not suppressed after one frame


def test_clutter_background_off_leaves_the_evidence_untouched():
    bg = LM.ClutterBackground(tau=1.0, k=0.0)
    ev = _bump((30, 40), 10, 10)
    for k in range(10):
        assert bg.apply(ev, k / 30.0) is ev


# --- runtime solver on a synthetic panning field ---------------------------
FRAME_W, FRAME_H = 1060, 830
BOX = (160, 150, 730, 448)
TAN = np.array([110, 170, 200], np.int16)


def _field():
    noise = RNG.randint(0, 70, (900, 1200, 3)).astype(np.uint8)
    noise = cv2.GaussianBlur(noise, (0, 0), 3)
    return np.clip(noise.astype(np.int16) + TAN - 30, 0, 255).astype(np.uint8)


def _frame(field, off, disc):
    fr = np.full((FRAME_H, FRAME_W, 3), 25, np.uint8)
    x, y, w, h = BOX
    box = field[off[1]:off[1] + h, off[0]:off[0] + w].copy()
    if disc is not None:
        cv2.circle(box, disc, 40, (250, 250, 250), -1)
    fr[y:y + h, x:x + w] = box
    return fr


def test_solver_flow_wait_acquire_track():
    torch = pytest.importorskip("torch")
    torch.manual_seed(0)
    net = LM.make_net(len(LM.REF_OFFSETS)).eval()
    solver = LM.MotionLieDetectorSolver(net=net, device="cpu")
    field = _field()
    states, targets = [], []
    assert solver.process(np.full((FRAME_H, FRAME_W, 3), 25, np.uint8)) is None
    for k in range(80):
        moving = k >= 30
        off = (100 + (5 * (k - 30) if moving else 0), 100 + (2 * (k - 30) if moving else 0))
        disc = (365, 260) if not moving else None              # opaque, then gone
        targets.append(solver.process(_frame(field, off, disc), cursor_xy=(500.0, 400.0), t=k / 30))
        states.append(solver.state)
    # the box is locked once it has been detected consistently for BOX_LOCK_S
    assert states[0] == "WAIT" and states[6] == "ACQUIRE"
    assert "TRACK" in states
    t0 = states.index("TRACK")
    assert 30 <= t0 <= 45                                       # START = field pans
    # during the countdown it follows the opaque disc (frame coords)
    x, y = targets[20]
    assert abs(x - (BOX[0] + 365)) < 4 and abs(y - (BOX[1] + 260)) < 4
    assert all(t is not None for t in targets[t0:])


def test_reference_frames_chosen_by_time_not_count():
    """Live, frames may arrive at ~15 Hz: references must still be ~1/30,
    3/30, 5/30, 7/30 s back (the recordings' spacing), not 1..7 frames back."""
    pytest.importorskip("torch")
    net = LM.make_net(4).eval()
    solver = LM.MotionLieDetectorSolver(net=net, device="cpu")
    solver.ref_offsets = (-7, -5, -3, -1)
    for k in range(12):                          # a 15 Hz feed: every 2/30 s
        solver._frames[k] = None
        solver._times[k] = k * 2 / 30
        solver._dup[k] = False
    solver._T = 11
    refs = solver._refs_by_time(11)
    # targets 7/30, 5/30, 3/30, 1/30 s back = 3.5, 2.5, 1.5, 0.5 frames back
    back = [(solver._times[11] - solver._times[r]) * 30 for r in refs]
    assert len(set(refs)) == 4                      # four distinct frames
    assert max(back) < 8.01 and min(back) > 1.99    # within one frame of 7/30 .. 1/30 s
    assert back == sorted(back, reverse=True)       # in offset order
    assert solver._refs_by_count(11) == [4, 6, 8, 10]   # what the count rule would do


def test_solver_scores_at_most_30hz_on_a_faster_feed():
    """With fast capture (~60 Hz) the tracker still steps at its tuned ~30 Hz;
    every frame still gets a (extrapolated) target."""
    torch = pytest.importorskip("torch")
    torch.manual_seed(0)
    solver = LM.MotionLieDetectorSolver(net=LM.make_net(4).eval(), device="cpu")
    field = _field()
    steps = []
    targets = []
    for k in range(140):
        t = k / 60.0
        moving = t >= 0.5
        dk = (k - 30) / 2.0
        off = (100 + int(5 * dk) if moving else 100, 100 + int(2 * dk) if moving else 100)
        disc = None if moving else (365, 260)
        targets.append(solver.process(_frame(field, off, disc), cursor_xy=(500.0, 400.0), t=t))
        if solver.tracker is not None and not hasattr(solver.tracker, "_wrapped"):
            orig = solver.tracker.step

            def counted(ev, dt_scale=1.0, _o=orig):
                steps.append(dt_scale)
                return _o(ev, dt_scale=dt_scale)
            solver.tracker.step = counted
            solver.tracker._wrapped = True
    assert solver.state == "TRACK"
    track_frames = sum(1 for _ in steps)
    assert track_frames > 10
    assert all(s >= 0.9 for s in steps), "never scores faster than ~1/30 s apart"
    assert all(tg is not None for tg in targets[-40:])


def test_phase_correlation_sizes_avoid_the_opencv_quirks():
    """OpenCV 4.9 biases phaseCorrelate by +0.5 px on axes padded to an odd
    size and windows its inputs in place when no padding is needed."""
    for n in (217, 225, 361, 367, 216, 360):
        m = LM.pc_size(n)
        assert m <= n and m % 2 == 0 and cv2.getOptimalDFTSize(m) == m


def test_alignment_follows_the_field_not_a_still_shape_at_its_centre():
    """Right after START the opaque shape sits still at the field's centre
    while the field pans. A Hanning window weights the centre, so the
    correlation followed the shape (on the live games 8-29% of tracking
    frames were > 2 px off); unwindowed it follows the field."""
    pytest.importorskip("torch")
    solver = LM.MotionLieDetectorSolver(net=LM.make_net(4).eval(), device="cpu")
    # the real camouflage is high-contrast (gray std ~30), unlike _field()
    g = cv2.GaussianBlur(RNG.rand(900, 1200).astype(np.float32), (0, 0), 2)
    g = np.clip(150 + 30 * (g - g.mean()) / g.std(), 0, 255).astype(np.uint8)
    field = cv2.cvtColor(g, cv2.COLOR_GRAY2BGR)
    box = (150, 140, 746, 496)
    solver._lock(box)
    for k, off in enumerate([(100, 100), (106, 103)]):     # field moves (+6, +3) px
        fr = _box_frame(field, (off[0] + 8, off[1] + 8), box)
        cv2.circle(fr, (box[0] + box[2] // 2, box[1] + box[3] // 2), 60, (245, 245, 245), -1)
        solver._push(solver._crop(fr), None, k * LM.FRAME_DT)
    dx, dy, _ = solver._shift(0, 1)
    assert abs(dx - -3) < 0.5 and abs(dy - -1.5) < 0.5, (dx, dy)


def test_a_model_aligns_the_way_it_was_trained(tmp_path):
    """Checkpoints from before the unwindowed alignment (no ``pc_window`` key)
    were trained on windowed alignment and keep it; new ones say so."""
    torch = pytest.importorskip("torch")
    net = LM.make_net(4)
    for extra, want in (({}, True), ({"pc_window": False}, False)):
        p = tmp_path / "m.pt"
        torch.save({"state": net.state_dict(), "ref_offsets": LM.REF_OFFSETS, "width": 48, **extra}, p)
        loaded, _ = LM.load_net(str(p), "cpu")
        assert loaded.pc_window is want
        assert LM.MotionLieDetectorSolver(net=loaded, device="cpu").pc_window is want


def _box_frame(field, off, box, fh=800, fw=1000):
    fr = np.full((fh, fw, 3), 25, np.uint8)
    x, y, w, h = box
    fr[y:y + h, x:x + w] = field[off[1]:off[1] + h, off[0]:off[0] + w]
    return fr


def test_repeated_frames_at_60hz_are_duplicates_and_start_still_fires():
    """A 30 fps stream captured at 60 Hz: every frame twice. With a box whose
    half-res height (217) pads to an odd FFT size the repeats read a 0.5 px
    shift and START never fired."""
    torch = pytest.importorskip("torch")
    torch.manual_seed(0)
    solver = LM.MotionLieDetectorSolver(net=LM.make_net(4).eval(), device="cpu")
    field = _field()
    box = (160, 126, 730, 452)              # crop 436 -> 218 half-res rows: FFT pads to 225
    states, dups = [], []
    for k in range(160):
        c = k // 2                          # content frame (30 fps), shown twice
        moving = c >= 30
        off = (100 + (4 * (c - 30) if moving else 0), 100 + (2 * (c - 30) if moving else 0))
        fr = _box_frame(field, off, box)
        if not moving:
            cv2.circle(fr, (box[0] + 365, box[1] + 230), 40, (250, 250, 250), -1)
        solver.process(fr, cursor_xy=(500.0, 400.0), t=k / 60)
        states.append(solver.state)
        if moving and c > 30:
            dups.append((k % 2 == 1, solver._dup[solver._T]))
    assert solver.box[3] == 452, "the refined box is the whole field"
    assert cv2.getOptimalDFTSize(solver._frames[solver._T].shape[0]) % 2 == 1, "odd FFT padding case"
    assert all(d for repeat, d in dups if repeat), "every repeated frame is a duplicate"
    assert not any(d for repeat, d in dups if not repeat), "and no moving frame is"
    t0 = states.index("TRACK")
    assert 60 <= t0 <= 60 + 2 * 12, "START within ~12 content frames of the pan"


def test_solver_survives_a_frozen_stream_in_track():
    """The stream freezes mid-game (every frame a repeat for > BUF frames):
    no crash, and the target stays inside the box."""
    torch = pytest.importorskip("torch")
    torch.manual_seed(0)
    solver = LM.MotionLieDetectorSolver(net=LM.make_net(4).eval(), device="cpu")
    field = _field()
    last = None
    for k in range(200):
        c = min(k, 80)                      # content stops changing at frame 80
        moving = c >= 30
        off = (100 + (5 * (c - 30) if moving else 0), 100 + (2 * (c - 30) if moving else 0))
        disc = (365, 260) if not moving else None
        last = solver.process(_frame(field, off, disc), cursor_xy=(500.0, 400.0), t=k / 30)
    assert solver.state == "TRACK" and last is not None
    x, y, w, h = solver.box
    assert x <= last[0] <= x + w and y <= last[1] <= y + h


def test_a_momentary_false_box_is_not_locked():
    """A combat effect passing for the box for a frame must not be locked;
    a box that stays put is."""
    pytest.importorskip("torch")
    solver = LM.MotionLieDetectorSolver(net=LM.make_net(4).eval(), device="cpu")
    field = _field()
    blank = np.full((FRAME_H, FRAME_W, 3), 25, np.uint8)
    seq = [_frame(field, (100, 100), None)] + [blank] * 5
    for k, fr in enumerate(seq):
        solver.process(fr, t=k / 30)
    assert solver.box is None and solver.state == "WAIT"
    for k in range(10):
        solver.process(_frame(field, (100, 100), None), t=1 + k / 30)
    assert solver.box is not None and solver.state == "ACQUIRE"


def test_box_loss_is_measured_in_time_not_frames():
    """At 60 Hz, 15 missing frames are 0.25 s: the box must survive a 0.3 s
    gap (BOX_LOST_S = 0.5) whatever the frame rate."""
    pytest.importorskip("torch")
    solver = LM.MotionLieDetectorSolver(net=LM.make_net(4).eval(), device="cpu")
    field = _field()
    blank = np.full((FRAME_H, FRAME_W, 3), 25, np.uint8)
    for k in range(12):
        solver.process(_frame(field, (100, 100), (365, 260)), t=k / 60)
    assert solver.state == "ACQUIRE"
    for k in range(18):                                   # 0.3 s of no box at 60 Hz
        solver.process(blank, t=(12 + k) / 60)
    assert solver.state == "ACQUIRE"
    for k in range(30):                                   # another 0.5 s: gone
        solver.process(blank, t=(30 + k) / 60)
    assert solver.state == "WAIT"



def test_refine_box_recovers_the_clipped_field_edges():
    """detect_play_box searches only the central region and clips the field's
    bottom/left; refine_box grows it back to the tan field's real edges and no
    further (the dark dialog border stops it)."""
    from src.easymaple.detection.lie_detector_solver import detect_play_box
    field = _field()
    real = (130, 126, 760, 520)             # bottom at 646 > the ROI's 576
    fr = _box_frame(field, (100, 100), real)
    b = detect_play_box(fr)
    assert b[1] + b[3] < real[1] + real[3] - 40, "the detector clips the bottom"
    assert LM.refine_box(fr, b) == real


def test_refine_box_trims_the_dialog_header():
    """While the dialog opens the detector's box can start at the dark
    "LIE DETECTOR" header 19 px above the field (live 2026-10-13: every box
    locked at y=126 instead of 145); refine_box must trim non-field rows too."""
    field = _field()
    real = (147, 145, 746, 496)
    fr = _box_frame(field, (100, 100), real)
    assert LM.refine_box(fr, (158, 126, 735, 467)) == real
