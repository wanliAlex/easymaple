"""Tests for the Lie Detector mini-game solver.

These are synthetic and self-contained (no recorded clips needed): a static
textured play-box with a bright disc that sits still, then moves while fading.
They guard the end-to-end pipeline — box detection, the static-background
plate, and shape tracking while the shape carries signal.
"""
import os

import cv2
import numpy as np
import pytest

from src.easymaple.detection import lie_detector_solver as S

RNG = np.random.RandomState(42)

# Frame + play-box geometry (box must clear the size/aspect/fill gates).
FRAME_W, FRAME_H = 1000, 800
BOX = (170, 150, 640, 420)                     # x, y, w, h (fits the central ROI)
TEXTURE = None


def _texture():
    """A fixed tan camouflage-like texture for the play-box (built once)."""
    global TEXTURE
    if TEXTURE is None:
        _, _, w, h = BOX
        noise = RNG.randint(0, 60, (h, w, 3), np.uint8)
        noise = cv2.GaussianBlur(noise, (0, 0), 6)     # smooth, low-frequency
        tan = np.array([110, 170, 200], np.uint8)      # BGR tan
        TEXTURE = np.clip(noise.astype(np.int16) + tan, 0, 255).astype(np.uint8)
    return TEXTURE


# The shape is a bright *cool* disc (high blue, low red) over the warm tan
# texture — like the real game, where the shape stays chromatically cool even as
# its brightness fades into the texture. ``DISC_BGR`` is bright enough to be
# acquired by luminance while opaque, and cooler than tan (B-R positive) so the
# tracker's B-R signal isolates it.
DISC_BGR = (255, 235, 175)                          # bright, cool (B=255 >> R=175)


def make_frame(disc_xy, alpha):
    """Build a frame: dark background, tan textured box, and a bright cool disc
    of opacity ``alpha`` (0..1) composited at ``disc_xy`` (box-interior coords)."""
    frame = np.full((FRAME_H, FRAME_W, 3), 20, np.uint8)
    x, y, w, h = BOX
    box = _texture().copy()
    if alpha > 0:
        overlay = box.copy()
        cv2.circle(overlay, (int(disc_xy[0]), int(disc_xy[1])), 34, DISC_BGR, -1)
        box = cv2.addWeighted(overlay, alpha, box, 1 - alpha, 0)
    frame[y:y + h, x:x + w] = box
    return frame


def synth_sequence():
    """Yield (frame, true_disc_center_in_frame_coords, alpha) for a full game:
    ~25 stationary opaque frames, then ~70 frames moving while fading."""
    x, y, w, h = BOX
    cx, cy = 250, 230                                  # interior start position
    seq = []
    for _ in range(25):                                # stationary, opaque
        seq.append(((cx, cy), 1.0))
    pos = np.array([cx, cy], float)
    vel = np.array([3.2, 1.7])
    for i in range(70):                                # moving + fading
        pos = pos + vel
        if not (40 < pos[0] < w - 40):
            vel[0] *= -1
        if not (40 < pos[1] < h - 40):
            vel[1] *= -1
        alpha = max(0.1, 1.0 - i / 60.0)
        seq.append((tuple(pos), alpha))
    return [(make_frame(p, a), (x + p[0], y + p[1]), a) for p, a in seq]


def test_detect_play_box_finds_the_box():
    frame, _, _ = synth_sequence()[0]
    box = S.detect_play_box(frame)
    assert box is not None
    x, y, w, h = box
    assert abs(x - BOX[0]) < 25 and abs(y - BOX[1]) < 25
    assert abs(w - BOX[2]) < 60 and abs(h - BOX[3]) < 60   # morphology trims a few px


def test_detect_play_box_rejects_small_tan_blobs():
    """A small tan rectangle (like a combat effect) must not be detected."""
    frame = np.full((FRAME_H, FRAME_W, 3), 20, np.uint8)
    frame[100:250, 100:340] = np.array([110, 170, 200], np.uint8)   # 240x150, too small
    assert S.detect_play_box(frame) is None


def test_build_plate_recovers_static_background():
    """The plate must recover the background despite a bright moving disc."""
    seq = synth_sequence()
    x, y, w, h = BOX
    m = S.BOX_INNER_MARGIN
    grays, masks = [], []
    for frame, _, _ in seq[30:]:                       # moving phase
        crop = frame[y + m:y + h - m, x + m:x + w - m]
        grays.append(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY).astype(np.float32))
        masks.append(np.zeros(grays[-1].shape, np.uint8))
    plate = build = S.build_plate(grays, masks)
    truth = cv2.cvtColor(_texture(), cv2.COLOR_BGR2GRAY).astype(np.float32)
    truth = truth[m:h - m, m:w - m]
    # Median plate should match the true texture closely almost everywhere.
    assert np.median(np.abs(plate - truth)) < 8.0


def test_solver_tracks_shape_while_signal_present():
    """End-to-end: the solver should follow the disc within ~a shape width
    while the shape still carries signal (opaque + early fade)."""
    solver = S.LieDetectorSolver()
    errs_with_signal = []
    reached_track = False
    for frame, truth_xy, alpha in synth_sequence():
        target = solver.process(frame)
        if solver.state == "TRACK":
            reached_track = True
        if target is not None and alpha >= 0.4:
            errs_with_signal.append(np.hypot(target[0] - truth_xy[0],
                                             target[1] - truth_xy[1]))
    assert reached_track, "solver never transitioned to TRACK"
    errs = np.array(errs_with_signal)
    # While the shape is reasonably visible, stay within ~one shape width.
    assert np.median(errs) < 70, f"median error {np.median(errs):.0f}px too high"
    assert np.mean(errs < 80) > 0.6, f"only {100*np.mean(errs<80):.0f}% within 80px"


def test_cool_channel_isolates_cool_shape_over_warm_texture():
    """The B-R signal must be clearly positive on a cool shape and ~zero on the
    warm texture — the contrast the tracker relies on."""
    frame = make_frame((300, 300), 0.6)
    x, y, w, h = BOX
    m = S.BOX_INNER_MARGIN
    crop = frame[y + m:y + h - m, x + m:x + w - m]
    cool = S.cool_channel(crop)
    shape = cool[300 - m, 300 - m]                     # at the disc centre
    bg = np.median(cool)                               # texture dominates the box
    assert shape - bg > 25, f"cool contrast {shape - bg:.0f} too weak"


def test_solver_tracks_cool_shape_through_deep_fade():
    """The chromatic signal must keep the lock as the shape fades to near the
    texture's brightness — where luminance tracking collapses. Asserts coverage
    deep into the fade (alpha < 0.3)."""
    solver = S.LieDetectorSolver()
    deep, locked = [], []
    for frame, truth_xy, alpha in synth_sequence():
        target = solver.process(frame)
        if solver.state == "TRACK" and target is not None and alpha < 0.3:
            deep.append(alpha)
            locked.append(np.hypot(target[0] - truth_xy[0], target[1] - truth_xy[1]) < 60)
    assert len(deep) >= 10, "sequence did not reach the deep-fade phase under TRACK"
    assert np.mean(locked) > 0.6, f"only {100*np.mean(locked):.0f}% locked in deep fade"


def test_green_cursor_is_masked_from_tracking():
    """A bright green reticle drawn on the box must not be tracked as the shape
    (at runtime it is our own cursor)."""
    frame = make_frame((300, 300), 0.0)                # no shape
    x, y, w, h = BOX
    m = S.BOX_INNER_MARGIN
    crop = frame[y + m:y + h - m, x + m:x + w - m]
    mask = S.green_cursor_mask(crop)
    assert mask.sum() == 0                             # no green present
    cv2.circle(crop, (200, 200), 12, (0, 255, 0), -1)  # add green reticle
    mask = S.green_cursor_mask(crop)
    assert mask[200, 200] > 0                          # green detected -> maskable


def _star(cx, cy, r_out, r_in, points=6):
    """Vertices of a `points`-pointed star (a low-circularity shape)."""
    pts = []
    for i in range(2 * points):
        r = r_out if i % 2 == 0 else r_in
        a = np.pi * i / points - np.pi / 2
        pts.append([cx + r * np.cos(a), cy + r * np.sin(a)])
    return np.array(pts, np.int32)


def test_bright_blob_is_shape_agnostic_and_skips_the_countdown_band():
    """Acquisition must not assume a disc. A bright STAR (circularity ~0.2) in the
    body of the box is acquired; a bright countdown-digit glyph up in the top band
    is ignored (the real game hides discs, triangles, stars, pins... behind a
    matching camouflage, and the digits/START text glow across the top)."""
    hh, ww = 440, 680
    gray = np.full((hh, ww), 40, np.float32)           # dark box interior
    star_c = (330, int(0.55 * hh))                     # in the body
    cv2.fillPoly(gray, [_star(star_c[0], star_c[1], 52, 24, 6)], 255)
    area_star = int((gray >= S.ACQUIRE_BRIGHT).sum())
    # a bright glyph in the top countdown band (must be skipped)
    cv2.putText(gray, "3", (300, int(0.2 * hh)), cv2.FONT_HERSHEY_SIMPLEX, 4.0, 255, 14)

    circ = 4 * np.pi * area_star / (cv2.arcLength(
        _star(star_c[0], star_c[1], 52, 24, 6).reshape(-1, 1, 2), True) ** 2 + 1e-6)
    assert circ < 0.4, f"test star not low-circularity enough ({circ:.2f})"

    blob, area = S._bright_blob(gray)
    assert blob is not None, "shape-agnostic acquisition missed the star"
    assert abs(blob[0] - star_c[0]) < 30 and abs(blob[1] - star_c[1]) < 30, \
        f"acquired {blob}, expected the body star near {star_c} (not the digit)"


def test_solver_accepts_bgra_frames_from_the_live_capture():
    """At runtime ``config.capture.frame`` is the raw 4-channel BGRA mss grab —
    not the 3-channel BGR the recorded clips are stored in. The solver must
    accept both (the alpha plane is simply dropped), or the live auto-solver
    crashes on its very first frame."""
    frame = make_frame((250, 230), 1.0)
    bgra = np.dstack([frame, np.full(frame.shape[:2], 255, np.uint8)])
    solver = S.LieDetectorSolver()
    target = solver.process(bgra)
    assert solver.state == "ACQUIRE", "box/shape not found in a BGRA frame"
    x, y, _, _ = BOX
    assert target is not None
    assert abs(target[0] - (x + 250)) < 20 and abs(target[1] - (y + 230)) < 20


def _run_pilot(pilot, targets):
    """Step the pilot over a target sequence; return the array of positions."""
    return np.array([pilot.step(t) for t in targets])


def _steps(path):
    return np.linalg.norm(np.diff(path, axis=0), axis=1)


def test_pilot_never_teleports_and_settles_on_the_target():
    """The cursor must reach a far target quickly but *continuously* — per-frame
    steps capped at PILOT_SPEED (a brisk human flick), settling on the target."""
    pilot = S.CursorPilot((0.0, 0.0))
    path = _run_pilot(pilot, [(400.0, 300.0)] * 60)
    assert _steps(path).max() <= S.PILOT_SPEED + 1e-6, "teleport / superhuman step"
    assert np.linalg.norm(path[-1] - (400, 300)) < 3, f"did not settle: {path[-1]}"
    # settled means *stays* settled (no limit-cycle wobble)
    assert _steps(path[-10:]).max() < 1.5, "still oscillating after settling"


def test_pilot_accelerates_and_brakes_smoothly():
    """No instant velocity snaps: per-frame velocity change is capped at
    PILOT_ACCEL, giving the bell-shaped speed profile of a human correction."""
    pilot = S.CursorPilot((0.0, 0.0))
    path = _run_pilot(pilot, [(400.0, 0.0)] * 60)
    vel = np.diff(path, axis=0)
    dvel = np.linalg.norm(np.diff(vel, axis=0), axis=1)
    assert dvel.max() <= S.PILOT_ACCEL + 1e-6, f"accel spike {dvel.max():.1f}"


def test_pilot_tracks_a_shape_speed_target_with_small_lag():
    """Velocity feed-forward: chasing a target moving at the shape's top speed
    (~20 px/frame) must hold the cursor well inside the game's tolerance."""
    pilot = S.CursorPilot((100.0, 100.0))
    tpos = np.array([100.0, 100.0])
    errs = []
    for i in range(90):
        tpos = tpos + (14.0, 14.3)                     # ~20 px/frame diagonal
        pos = pilot.step(tuple(tpos))
        if i > 25:                                     # after catch-up transient
            errs.append(np.hypot(pos[0] - tpos[0], pos[1] - tpos[1]))
    assert max(errs) < 40, f"lag {max(errs):.0f}px would break the lock"


def test_pilot_glides_through_a_target_jump():
    """A tracker re-acquisition teleports the *target*; the cursor must glide
    over (bounded steps) and re-settle quickly — like a human's corrective flick."""
    pilot = S.CursorPilot((0.0, 0.0))
    targets = [(50.0, 50.0)] * 30 + [(300.0, 50.0)] * 40
    path = _run_pilot(pilot, targets)
    assert _steps(path).max() <= S.PILOT_SPEED + 1e-6
    assert np.linalg.norm(path[-1] - (300, 50)) < 3, "did not re-settle after jump"
    settle = np.nonzero(np.linalg.norm(path[30:] - (300, 50), axis=1) < 10)[0]
    assert settle.size and settle[0] <= 30, "took >1s to correct a 250px jump"


def test_pilot_glides_to_a_stop_when_target_vanishes():
    """No target (box lost / game over): the cursor brakes smoothly to rest
    instead of freezing mid-motion or drifting away."""
    pilot = S.CursorPilot((0.0, 0.0))
    _run_pilot(pilot, [(400.0, 300.0)] * 12)           # get it moving fast
    coast = _run_pilot(pilot, [None] * 40)
    dvel = np.linalg.norm(np.diff(np.diff(coast, axis=0), axis=0), axis=1)
    assert dvel.max() <= S.PILOT_ACCEL + 1e-6, "brake was not smooth"
    assert _steps(coast)[-1] < 0.5, "still moving long after target vanished"


def _run_fadeout_game(cursor_follows=True, reappear_at=None, noise_sigma=2.0):
    """Synthetic game modelled on the 2026-07-10_14-34-09 live failure: the
    shape fades to COMPLETE invisibility mid-game (and may reappear). A cool
    'reticle halo' ring is painted at the commanded cursor position each frame
    (the live capture contains our own cursor; its anti-aliased glow leaks past
    the green mask). Returns (targets, truths, phases) per moving frame; phase
    is 'visible', 'blind' or 'reappeared'."""
    rng = np.random.RandomState(11)
    solver = S.LieDetectorSolver()
    x, y, w, h = BOX
    cursor = None

    def process(frame, disc_xy):
        nonlocal cursor
        if cursor is not None:
            # our own reticle: green core + a leaky cool halo ring around it
            c = (int(cursor[0] - x), int(cursor[1] - y))
            cv2.circle(frame[y:y + h, x:x + w], c, 16, (230, 200, 170), 3)
            cv2.circle(frame[y:y + h, x:x + w], c, 9, (0, 255, 0), -1)
        noisy = np.clip(frame.astype(np.float32)
                        + rng.normal(0, noise_sigma, frame.shape), 0, 255
                        ).astype(np.uint8)
        t = solver.process(noisy, cursor_xy=cursor)
        if t is not None and cursor_follows:
            cursor = t                       # the player parks the cursor on the target
        return t

    for _ in range(25):
        process(make_frame((250, 230), 1.0), (250, 230))
    pos = np.array([250.0, 230.0])
    vel = np.array([3.0, 1.7])
    out = []
    for i in range(110):
        pos = pos + vel
        if not (55 < pos[0] < w - 55):
            vel[0] *= -1
        if not (55 < pos[1] < h - 55):
            vel[1] *= -1
        # The shape stays trackable well past TRACK start (like the real game,
        # where the deep fade comes seconds into tracking), then vanishes.
        if i < 60:
            alpha, phase = max(0.35, 1.0 - i / 55.0), "visible"
        elif reappear_at is not None and i >= reappear_at:
            alpha, phase = 0.5, "reappeared"
        else:
            alpha, phase = 0.0, "blind"      # completely gone, like the real clip
        t = process(make_frame(tuple(pos), alpha), tuple(pos))
        if solver.state == "TRACK" and t is not None:
            out.append((t, (x + pos[0], y + pos[1]), phase))
    return out


def test_tracker_does_not_lock_onto_its_own_cursor_halo():
    """THE live failure of 2026-07-10_14-34-09: once the shape faded to
    nothing, the strongest stable cool blob was our own reticle's halo, so the
    tracker froze on itself. With the commanded cursor position masked, the
    blind-phase output must NOT sit parked on the cursor halo."""
    out = _run_fadeout_game(cursor_follows=True)
    blind = [(t, tr) for t, tr, ph in out if ph == "blind"]
    assert len(blind) >= 30, "game never reached the blind phase under TRACK"
    # A self-locked tracker emits (almost) the same point forever. Require the
    # blind-phase output to keep moving initially (coast), i.e. not frozen.
    pts = np.array([t for t, _ in blind[:20]])
    travel = np.linalg.norm(np.diff(pts, axis=0), axis=1).sum()
    assert travel > 40, f"tracker froze on its own cursor (travel {travel:.0f}px)"


def test_tracker_relocks_when_the_shape_reappears():
    """A blind stretch must not be a one-way door: when the shape comes back
    above the noise floor, the smoother's best path switches to it and the
    tracker follows again."""
    out = _run_fadeout_game(cursor_follows=False, reappear_at=75)
    re = [(t, tr) for t, tr, ph in out if ph == "reappeared"]
    assert len(re) >= 20, "no reappeared phase captured"
    errs = [np.hypot(t[0] - tr[0], t[1] - tr[1]) for t, tr in re[8:]]
    assert np.mean(np.array(errs) < 80) > 0.7, \
        f"failed to re-lock after reappearance (median err {np.median(errs):.0f}px)"


def test_smoother_rejects_transient_distractors_and_holds_to_the_end():
    """End-tracking (the pass criterion): the fixed-lag smoother must keep the
    lock on the smoothly moving, fading shape through the finish while *transient*
    bright cool flashes (the real texture's shimmer / momentary distractors) pop
    up far away. Each flash is the strongest blob for the frame it exists, so a
    greedy global tracker would snap to it and lose the end; the smooth-path DP
    drops it because a one-frame spike never lies on a smooth trajectory."""
    rng = np.random.RandomState(7)
    solver = S.LieDetectorSolver()
    x, y, w, h = BOX
    for _ in range(25):                                 # opaque, stationary
        solver.process(make_frame((250, 230), 1.0))
    pos = np.array([250.0, 230.0])
    vel = np.array([3.0, 1.7])
    n = 95
    end_ok = []
    for i in range(n):
        pos = pos + vel
        if not (55 < pos[0] < w - 55):
            vel[0] *= -1
        if not (55 < pos[1] < h - 55):
            vel[1] *= -1
        alpha = max(0.30, 1.0 - i / 60.0)               # fades but stays detectable
        frame = make_frame(tuple(pos), alpha)
        if i > 30 and i % 3 == 0:                       # a one-frame flash, far from the shape
            fx, fy = rng.randint(x + 45, x + w - 45), rng.randint(y + 45, y + h - 45)
            if np.hypot(fx - (x + pos[0]), fy - (y + pos[1])) > 160:
                cv2.circle(frame, (fx, fy), 26, DISC_BGR, -1)
        t = solver.process(frame)
        if i >= n - 20 and t is not None and solver.state == "TRACK":
            truth = (x + pos[0], y + pos[1])
            end_ok.append(np.hypot(t[0] - truth[0], t[1] - truth[1]) < 90)
    assert end_ok, "solver never reached TRACK at the end"
    assert np.mean(end_ok) > 0.6, \
        f"lost the end to transient distractors ({100*np.mean(end_ok):.0f}% locked)"
