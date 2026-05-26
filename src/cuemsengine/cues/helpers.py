# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>

from cuemsutils.cues.Cue import Cue
from cuemsutils.tools.CTimecode import CTimecode

from ..tools.MtcListener import MtcListener


def find_timing(
    cue: Cue, mtc: MtcListener, in_frames: bool = False
) -> tuple[int, CTimecode]:
    """Find the duration and offset of a cue

    Args:
        cue (Cue): The cue with _start_mtc defined to find the timing
        mtc (Mtc): The main timecode object
        in_frames (bool): If True, return the offset in frames instead of
        milliseconds

    Returns:
        tuple[int, CTimecode]: The offset in frames and the duration
    """
    if not cue._start_mtc:
        # Frame-domain construction (mirrors the surgical fix at
        # loop_cue.py:107,224) to skip the lossy ms→seconds→frames round-trip.
        cue._start_mtc = CTimecode(
            framerate=mtc.main_tc.framerate, frames=mtc.main_tc.frames
        )

    if in_frames:
        time_attribute = "frame_number"
    else:
        time_attribute = "milliseconds"

    # Calculate duration
    duration = cue.media.regions[0].out_time - cue.media.regions[0].in_time
    duration = duration.return_in_other_framerate(mtc.main_tc.framerate)
    # Set cue end timecode
    cue._end_mtc = cue._start_mtc + duration
    in_time_fr_adjusted = cue.media.regions[
        0
    ].in_time.return_in_other_framerate(mtc.main_tc.framerate)
    # Calculate offset to go
    offset_to_go = (
        in_time_fr_adjusted[time_attribute] - cue._start_mtc[time_attribute]
    )
    return offset_to_go, duration
