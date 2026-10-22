<!--
SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
SPDX-License-Identifier: GPL-3.0-or-later
-->

# R-1: Media sizes that were never stored (T043)

`tests/test_cue_media_dimensions.py::test_a_loaded_v2_project_without_stored_sizes_takes_the_probe_path`
loads `dev/test_xml_files/projects/video_no_pixels_v2/script.xml` (moves to `tests/data/` in T097) through the
real `CuemsScript.load`. Its VideoCue has `file_name` and `duration` and none of `pixel_width`, `pixel_height`,
`file_size`.

**Result: it passed first time → characterization, no production change.** `Unset` is **key-absent** on 0.1.1:
`media.get("pixel_width")` is `None` (research R3), which the engine's `_positive_int` guards treat as missing.
`PlayerHandler.cue_media_dimensions` takes the probe path (the mocked probe is called once with `clip.mp4`) and
`own_media_size_mismatches` treats `file_size` as missing (an existing copy is not reported; a missing one is
`("gone.mp4", None, None)`).

The check against `cuemsutils.helpers.Unset` that T043 lists as the fix is not needed. This is also the evidence
for X-4 in `upstream-reports/cuems-utils-x1-x4.md` ("`Media` `Unset` stays key-absent").
