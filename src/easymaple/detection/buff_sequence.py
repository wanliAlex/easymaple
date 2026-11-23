"""Finds the Buff Sequence dialog and its 'Use Unapplied Buffs' button.

Pressing the Buff Sequence key while some of its buffs are still active opens::

    ┌───────────────────────────────────────────────┐
    │ The following Buff Sequence buffs              │  <- TOP (fixed)
    │ are currently not applied.                     │
    ├───────────────────────────────────────────────┤
    │ 2x EXP Coupon (30 min) ...                     │  <- the missing buffs: text and
    │ ...                                            │     height change every time
    ├───────────────────────────────────────────────┤
    │ Please select the buff effect range.           │  <- PROMPT (fixed)
    │ [Use All Buffs] [Use Unapplied Buffs] [Cancel] │
    └───────────────────────────────────────────────┘

So only the fixed top and the prompt line are matched; the button sits at a
fixed offset below the prompt. The buttons themselves are left out of the
templates because their highlight changes with the mouse hover.
"""

import cv2
import numpy as np

from src.easymaple.common import utils

# The header box ("The following Buff Sequence buffs are currently not applied.")
TOP_TEMPLATE = utils.load_image('assets/buff_template_3.png', cv2.IMREAD_GRAYSCALE)
# "Please select the buff effect range."
PROMPT_TEMPLATE = utils.load_image('assets/buff_sequence_prompt.png', cv2.IMREAD_GRAYSCALE)

# From the prompt template's top-left corner to the centre of the
# 'Use Unapplied Buffs' button (measured on a 1047x822 window capture).
UNAPPLIED_OFFSET = (178, 73)

PROMPT_THRESHOLD = 0.8
TOP_THRESHOLD = 0.8
# The top can be hidden (e.g. by the "item effect has disappeared" banner
# when the dialog is tall): then the prompt alone has to be this sure.
PROMPT_ALONE_THRESHOLD = 0.9
# Top and prompt are centred in the same dialog.
MAX_CENTRE_OFFSET_X = 12
MIN_TOP_TO_PROMPT_Y, MAX_TOP_TO_PROMPT_Y = 60, 700


def _best(gray, template):
    """(score, top-left) of the best match; (0.0, None) if it cannot match."""
    if gray is None or template.shape[0] > gray.shape[0] or template.shape[1] > gray.shape[1]:
        return 0.0, None
    try:
        result = cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED)
    except cv2.error:
        return 0.0, None
    _, score, _, loc = cv2.minMaxLoc(result)
    return (0.0 if np.isnan(score) else float(score)), loc


def find_unapplied_button(gray):
    """Where to click 'Use Unapplied Buffs' in the grayscale frame GRAY.

    Returns (point, info): POINT is the button centre in frame coordinates, or
    None when the dialog is not on screen; INFO holds the match scores.
    """
    prompt_score, prompt_loc = _best(gray, PROMPT_TEMPLATE)
    info = {'prompt': prompt_score, 'top': None, 'lined_up': False}
    if prompt_score < PROMPT_THRESHOLD:
        return None, info

    top_score, top_loc = _best(gray, TOP_TEMPLATE)
    info['top'] = top_score
    if top_loc is not None and top_score >= TOP_THRESHOLD:
        prompt_cx = prompt_loc[0] + PROMPT_TEMPLATE.shape[1] / 2
        top_cx = top_loc[0] + TOP_TEMPLATE.shape[1] / 2
        dy = prompt_loc[1] - top_loc[1]
        info['lined_up'] = (abs(prompt_cx - top_cx) <= MAX_CENTRE_OFFSET_X
                            and MIN_TOP_TO_PROMPT_Y <= dy <= MAX_TOP_TO_PROMPT_Y)

    if not info['lined_up'] and prompt_score < PROMPT_ALONE_THRESHOLD:
        return None, info
    return (prompt_loc[0] + UNAPPLIED_OFFSET[0], prompt_loc[1] + UNAPPLIED_OFFSET[1]), info
