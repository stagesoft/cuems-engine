# Changelog

## Unreleased

CTimecode hardening migration (closes ClickUp 869cyndtv PR #7) and 24h MTC rollover detection (closes ClickUp 869cpdbzy layer 2). Pins `cuemsutils` to `0.1.0rc7` to consume the playhead-semantic CTimecode and `.milliseconds_rounded` / `.milliseconds_exact` precision-split.

### Changed
- Pinned `cuemsutils` from `0.1.0rc5` to `0.1.0rc7`. This brings:
  - Playhead-semantic `CTimecode.__init__` (same real time → same frames regardless of `start_seconds` vs `start_timecode` ctor path).
  - Frame-domain `return_in_other_framerate` (no more 1-frame loss per round-trip at fractional framerates).
  - Fixed `__add__`/`__sub__` (no more 1-frame off-by-one — the loop-drift root cause documented in the surgical fix at `loop_cue.py:107,224`).
  - Same-framerate assertion on arithmetic operators (cross-framerate ops now raise `CTimecodeError` instead of silently using `other.frames`).
  - `framerate` getter returns canonical numeric types (`int` for SMPTE, `float` for fractional, `int 1000` for ms).
  - `__str__` monotonic past 24h (no SMPTE rollover at the string level).
- Migrated every `.milliseconds` call-site to the precision-explicit `.milliseconds_rounded` (int, rounded — used for sleep durations, polling comparisons, OSC bundle args) or `.milliseconds_exact` (float, precise — used for the `BaseEngine.go_offset` calculation). Affected files:
  - `src/cuemsengine/NodeEngine.py`
  - `src/cuemsengine/core/BaseEngine.py` — `go_offset` math now uses `_exact` to avoid sub-ms truncation drift.
  - `src/cuemsengine/cues/CueHandler.py` — prewait/postwait sleep + mtc_ms capture.
  - `src/cuemsengine/cues/loop_cue.py` — loop-end polling comparisons.
  - `src/cuemsengine/cues/run_cue.py` — frozen-MTC paths and start/end mtc construction.
  - `src/cuemsengine/cues/helpers.py` — `find_timing` `_start_mtc` fallback.
  - `src/cuemsengine/tools/MtcListener.py`.
- A strict `python -W error::DeprecationWarning pytest tests/` sweep on this branch surfaces zero remaining `.milliseconds` call-sites in cuemsengine. The only `DeprecationWarning` left is pre-existing `websockets.server.serve` from a third-party import.

### Fixed
- **24h MTC rollover detection in `MtcListener` (869cpdbzy layer 2).** MIDI MTC encodes hours in a 5-bit field (0–23) and real SMPTE senders reset to `00:00:00:00` after 24h. `MtcListener.__mtc_decode` reconstructs CTimecode from raw MIDI bytes that wrap independently of CTimecode's internal counter, so layer 1 (cuemsutils PR #10's `__str__` fix) alone was not enough — without rollover detection, every new MIDI message would reset the listener's effective MTC to a low value at the 24h mark, breaking the `while mtc.main_tc.milliseconds < self._end_mtc.milliseconds` checks in audio/video/dmx loop cues. The listener now compares each decoded TC to the previous one, detects backward jumps consistent with a 24h wrap (delta < -1h), and accumulates a 24h offset that is applied to all subsequent constructed CTimecodes. Persists across the QF interpolation `+1` advance at `MtcListener.py:105`.

### Tests
- Updated two `TestLoopDmxCue` mocks (`test_loop_dmx_cue_local_guard`, `test_loop_dmx_cue_remote`) to set `.milliseconds_rounded` on the MTC mock instead of `.milliseconds` — the production `loop_dmxCue` now reads the rounded variant. Other `.milliseconds=` mock sites in `tests/test_cues_dmx.py` don't reach the comparison path (tests fail earlier on unrelated baseline issues out of scope here).
- Added `TestMtcListenerRollover` in `tests/test_mtclistener.py` covering the wrap-detection state machine: clean 24h boundary crossing, the offset persisting across decode calls, manual seek (small backward jump within the same 24h block) NOT being treated as a rollover, and forward jumps past the boundary.
- Net test results vs the integration branch baseline: −1 failure (3 ossia tests no longer fail, 2 dmx-mock tests now pass with the fixture update; the rest are pre-existing baseline issues unrelated to this work).

### Notes
- The surgical 1-frame fix at `loop_cue.py:107,224` from the sister task (869cy1yjb) remains untouched in this PR — it is now redundant with the `__add__`/`__sub__` fix in cuemsutils PR #6, but ripping it out can be done in a follow-up alongside a focused regression test rather than bundled here.
- The engine's existing CTimecode call-sites that use frame-domain arithmetic (PR #6 surgical sites, MtcListener QF advance) already worked correctly under the old behavior and continue to work — the migration only touched `.milliseconds` consumers and trusted the cuemsutils PR #6 fixes for the rest.
