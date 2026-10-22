<!--
SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
SPDX-License-Identifier: GPL-3.0-or-later
-->

# R-2: the cue-name walk over a real version-2 script (T044)

`tests/test_controller_cue_names.py::test_the_walk_over_a_real_v2_script_descends_and_tolerates_an_empty_name`
and `::test_the_walk_gives_an_empty_string_for_a_cue_with_no_name_key` load
`dev/test_xml_files/projects/video_no_pixels_v2/script.xml` through `CuemsScript.load`.

**Both passed first time → characterization, no production change.** `_collect_cue_names` descends into the CueList
child, gives `""` for an emptied name and for a cue with no `name` key, and raises nothing.

**Finding on the task's premise.** T044 asks for a cue whose name is empty as `<name/>`. The version-2 schema refuses
that: `CuemsScript.load` fails with `XsdMinLengthFacet(value=1)` on `/CuemsScript/CueList/contents/CueList/contents/Cue/name`.
An empty name can therefore only reach the walk from code or from an older library, so the test empties the name
after the load instead of authoring `<name/>`.
