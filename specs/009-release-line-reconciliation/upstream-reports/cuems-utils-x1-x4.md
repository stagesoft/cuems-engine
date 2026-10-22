<!--
SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
SPDX-License-Identifier: GPL-3.0-or-later
-->

# For cuems-utils: what cuems-engine 0.1.1-1 still needs (X-1 … X-4)

Written by cuems-engine's feature 009 (release-line reconciliation), 2026-10-22. **Successor path:**
`specs/009-release-line-reconciliation/` in cuems-engine. cuems-utils' 017 pre-spec cites the engine's work order at
commit `945ccba`, which 009 deletes at its end; please re-point those references to this directory. Linking this
report from cuems-utils' "still owed" list is cuems-utils' edit, not the engine's.

Nothing in cuems-utils was changed by this feature.

## X-1 — `stop_project` in the version-2 `ActionType` (needed)

The engine ships the `stop_project` ActionCue (869fhjdq5, `0.1.0rc6-5`): the authored end of an unattended show. A
project that holds one is loaded and saved through cuems-utils' schema, so cuems-utils 0.1.1 has to carry the value.

**Measured, 2026-10-22:**

| cuems-utils | `stop_project` in `script.xsd` | Engine X-1 tests |
|---|---|---|
| tag `xml-refactor-merge-candidate` (`4b336cd`) | **absent** (`ActionType` lists `pause_project`, `resume_project` and no `stop_project`) | 2 `xfailed`: `CuemsScript.load` refuses the document |
| `feat/xml-refactor` head (`b592a57` when measured) | **present**, targetless (017 A-1) | 2 passed |

So the obligation is met on the branch and **not on the tag the engine's CI gate defaults to**. Re-cutting the candidate
tag on a head that carries 017 closes X-1. The engine's tests are `tests/test_stop_project_xsd.py`: a targetless
`<action_type>stop_project</action_type>` (a) loads and yields an `ActionCue`, (b) saves back through the published
write path. They are `xfail(strict=True)` **only while the installed library refuses the document**, and plain tests
once it accepts it, so neither a stale tag nor a landed fix needs a manual step on the engine side.

**Engine-side evidence for 017's S-1 and D5:** the engine's expectation is **targetless** (`<action_target />`, which
parses to `None`). rc17's authors write exactly that, and `ActionHandler.PROJECT_SCOPE_ACTIONS = {"stop_project"}` skips
the "Missing target" rejection for it. The engine does not need `pause_project` / `resume_project`: nothing in `src/` reads them (a comment in
`ActionHandler.py` lists them as unsupported, and two tests assert they are rejected).

Also for the ActionCue documentation of cuems-utils: the value and its project scope (no target).

## X-2 — keep `Replaces: cuems-engine (<< 0.1.0rc6-2~)` (needed)

`cuems-engine` stopped shipping `/usr/lib/cuems/bin/cffi-gen-src` in `0.1.0rc6-2`; cuems-utils ships the same file. Installing
over a release that still ships it fails with "trying to overwrite" unless cuems-utils declares
`Replaces: cuems-engine (<< 0.1.0rc6-2~)`. Please keep it and add the row to 016's relation matrix. The `0.1.1-1` engine deb
does not ship the file (`dpkg -c … | grep -c cffi-gen-src` → 0; evidence `bookworm-build.md`).

## X-3 — `CACHEDIR.TAG` (measured, nothing owed by the engine)

Both engine debs were built on bookworm with 016's `tools/bookworm-build.sh` and carry **no**
`/usr/lib/cuems/CACHEDIR.TAG`, so the engine strips nothing (`bookworm-build.md`). If cuems-utils' own deb still ships one,
that is cuems-utils' to strip the way its rules do.

## X-4 — `Media` "unset" versus "nothing" on a version-2 load (confirmed as is)

A version-2 `Media` that never stored `pixel_width`, `pixel_height` or `file_size` answers `media.get("pixel_width")` →
`None`: the key is absent, `Unset` does not appear. The engine reads these with `.get()` and treats a non-positive
integer as missing (the probe runs). Test: `tests/test_cue_media_dimensions.py::test_a_loaded_v2_project_without_stored_sizes_takes_the_probe_path`,
over `projects/video_no_pixels_v2`; record `evidence/r1-media-unset.md`. **Please keep it that way**, or tell the engine
before changing it.

## Other observations (information only)

- A version-2 `<name/>` on a cue is refused (`minLength 1`); the engine's cue-name walk tolerates an empty name anyway
  (R-2, `evidence/r2-cue-names.md`).
- The engine's test layout copies cuems-utils' directory vocabulary (`unit/`, `integration/`, `contract/`, `support/`,
  `data/`). About 20 `test_*.py` files and one `testdev_*.py` still sit at the root of cuems-utils' `tests/`.
