# Feature Specification: Gradient Motion Engine — Python-Side Integration (Phase 6)

**Feature Branch**: `004-gradient-engine-phase6`
**Created**: 2026-04-27
**Status**: Draft
**Input**: Phase 6 of the Gradient Motion Engine integration plan, scoped to the cuems-engine
Python changes required to dispatch and receive fade commands via the NNG bus.

## Clarifications

### Session 2026-04-27

- Q: Where does fade duration live in the data model? → A: A new dedicated `FadeCue` cue
  type carries the duration. The FadeCue model is:
  - `curve_type` — `FadeCurveType` enum: `linear`, `exponential`, `logarithmic`, `sigmoid`.
    Default `linear`.
  - `duration` — `CTimecode`, MUST be positive non-zero. `None` is allowed only transiently
    during deserialization.
  - `target_value` — `int` in `[0, 100]`. Default `0`.
  - `action_target` — required, identifies the cue being faded.
  - `action_type` — locked to `fade_action`; setting anything else post-init raises.

  Implication: there is no longer a `fade_in` vs `fade_out` action_type distinction. A single
  `FadeCue` represents "fade `action_target` to `target_value` over `duration` using
  `curve_type`". "Fade-in" semantics are achieved with `target_value` > current value;
  "fade-out" semantics with `target_value = 0`.
- Q: How is `fade_id` generated for the FadeCommand sent to gradient-motiond? → A:
  `fade_id = FadeCue.uuid` (the FadeCue's own cue identifier). Verified compatible with
  gradient-motion-engine which treats `fade_id` as an arbitrary controller-assigned
  `std::string` with no format restrictions. Mapping `fade_complete.fade_id → FadeCue →
  action_target` is a single registry lookup; no separate `fade_id → cue` map is required.
- Q: What happens when a FadeCue dispatches but gradient-motiond is unreachable (daemon not
  running, NNG send fails, etc.)? → A: Hard-fail. The FadeCue is rejected with a `failed`
  status through the existing ActionHandler result path; an error is logged identifying the
  unreachable daemon and the FadeCue UUID; the target_cue's state is NOT mutated (no arm,
  no play, no stop). The operator must observe the failure and react (restart daemon,
  re-fire). Silent drops and fallback-to-play/stop behaviours are explicitly rejected.
- Q: How does the Python engine recover the actual OSC value for `start_value` at FadeCue
  dispatch? → A: Read from the **target_cue's** local Ossia node cache via
  `target_cue._osc.get_value(path)` at dispatch time, where `target_cue =
  FadeCue.action_target`. The Python engine updates the target_cue's cache when it writes
  (existing behaviour in `run_audioCue` etc.), and additionally on every `fade_complete`
  STATUS by setting the cache entry for the target_cue's OSC path to the `end_value` that
  was dispatched in the originating FadeCommand (the Python engine retains this from its
  dispatch record keyed by `fade_id`). The current gradient-motiond `fade_complete`
  payload does NOT carry the final value, but the Python engine does not need it: it
  already knows what `end_value` it dispatched. This works correctly under the spec's
  "one active fade per target_cue" assumption. Naming convention: throughout the spec,
  `target_cue` (not `cue`, not `target`) is the canonical name for `FadeCue.action_target`
  to make it unambiguous that all OSC information (port, layer id, current value, master
  volume) is recovered from the target_cue, never from the FadeCue.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Fade-Up FadeCue (target_value > current) (Priority: P1)

A show operator fires a `FadeCue` whose `target_value` is greater than the action_target's
current level (commonly 100 from a silent/non-playing target — i.e. "fade in from silence").
The target media smoothly rises from its current value (or 0 if not yet playing) to
`target_value/100` over `duration` using `curve_type`, time-locked to the show's MTC timecode.

**Why this priority**: Fade-up (especially fade-in from silence to full) is the most common
use of gradient cues in live performance and is the baseline demonstrable MVP. Once it works
end-to-end, the FadeCue → NNG → gradient-motiond → OSC → player path is proven.

**Independent Test**: Can be fully tested by firing a single FadeCue (target_value=100,
duration=3s, curve_type=linear) against an AudioCue in a test session and observing that the
audio level rises smoothly from 0 to the cue's configured master volume over 3 seconds with
no audible step at start.

**Acceptance Scenarios**:

1. **Given** an AudioCue exists and a FadeCue targets it with `target_value=100`, **When**
   the operator fires the FadeCue, **Then** audio begins playing at silence and rises
   smoothly to the cue's configured master volume level within `duration`.
2. **Given** a VideoCue exists and a FadeCue targets it with `target_value=100`, **When** the
   operator fires the FadeCue, **Then** the video layer becomes visible at zero opacity and
   rises smoothly to full opacity within `duration`.
3. **Given** a FadeCue is in progress, **When** MTC transport is paused, **Then** the fade
   progression pauses with timecode and resumes when transport resumes.
4. **Given** a FadeCue with `target_value > 0` is in the cue list and a project is loaded,
   **When** the project loads (script arm phase), **Then** the FadeCue's `action_target` is
   pre-armed so no arm-delay occurs when the FadeCue fires.

---

### User Story 2 — Fade-Down FadeCue (target_value = 0) (Priority: P2)

A show operator fires a `FadeCue` whose `target_value` is `0` against a playing audio or
video cue. The media smoothly falls from its current level to silence/transparency, and when
the fade completes the target_cue is automatically disarmed.

**Why this priority**: Fade-down to 0 (fade-out) completes the essential fade pair. Without
it, operators have no smooth way to end playback, falling back to the abrupt `stop` action.

**Independent Test**: Can be tested by playing an AudioCue at full volume, then firing a
FadeCue (`target_value=0`, duration=3s) against it and verifying that the audio level drops
smoothly to 0 over 3 seconds, after which the AudioCue is in the disarmed state.

**Acceptance Scenarios**:

1. **Given** an AudioCue is playing at its configured volume, **When** the operator fires a
   FadeCue with `target_value=0` targeting it, **Then** the audio level smoothly falls to
   silence over `duration` and the AudioCue is disarmed after fade completion.
2. **Given** a VideoCue is playing at full opacity, **When** the operator fires a FadeCue
   with `target_value=0` targeting it, **Then** the video layer opacity smoothly falls to 0
   over `duration` and the VideoCue is disarmed after fade completion.
3. **Given** a fade-down is complete and the target is disarmed, **When** the operator
   re-arms and re-fires the AudioCue, **Then** playback resumes normally at the configured
   volume.
4. **Given** a FadeCue with `target_value=0` references a cue that is not currently playing,
   **When** the operator fires it, **Then** the system logs a warning and takes no action,
   leaving the target_cue state unchanged.

---

### User Story 3 — Clean Project Load and Stop (Priority: P3)

When an operator loads a new project or triggers a script stop, any fades that are actively
running are immediately cancelled, preventing stale volume or opacity commands from reaching
players that are no longer active.

**Why this priority**: A show that stops mid-fade must leave the system in a clean state.
Stale OSC commands sent after a player has stopped could cause unpredictable behaviour on the
next project load.

**Independent Test**: Can be tested by starting a long fade (e.g., 30-second fade-out), then
triggering a project stop before the fade completes, and verifying that no further OSC messages
are sent to the audio player after the stop.

**Acceptance Scenarios**:

1. **Given** a fade is in progress, **When** the operator stops the project, **Then** all
   active fades are cancelled before any players are stopped, and no further OSC messages reach
   the players.
2. **Given** a fade is in progress, **When** the operator loads a new project, **Then** all
   active fades from the previous project are cancelled before the new project initialises.
3. **Given** no fades are in progress, **When** a project stop is triggered, **Then** the
   system operates normally without errors.

---

### User Story 4 — Gradient Engine Message Routing Isolation (Priority: P4)

NNG bus messages destined for gradient-motiond are transparently forwarded without being
processed by the Python engine's own command dispatch. STATUS messages from gradient-motiond
are received and acted upon (fade_complete triggers disarm) or silently ignored by components
that are not concerned with them.

**Why this priority**: Correct routing is a system correctness prerequisite for all other
stories. If the Python engine erroneously processes or discards gradient commands, fades will
break silently.

**Independent Test**: Can be tested by sending a synthetic `gradientengine`-targeted NNG
command via the bus and verifying that the Python NodeEngine does not attempt to process it
as a local command, and that gradient-motiond receives it.

**Acceptance Scenarios**:

1. **Given** the NNG bus carries a command with `target="gradientengine"`, **When** NodeEngine
   processes the incoming message, **Then** it passes through without error and no local
   handler attempts to execute it.
2. **Given** gradient-motiond sends a `fade_complete` STATUS message on the bus, **When**
   NodeEngine receives it, **Then** the relevant fade-out cue's target is disarmed.
3. **Given** gradient-motiond sends any STATUS message, **When** ControllerEngine receives
   it (because the bus broadcasts to all peers), **Then** ControllerEngine silently ignores
   it without logging errors or attempting processing.

---

### Edge Cases

- What happens when a fade-up FadeCue fires but the target_cue (AudioCue/VideoCue) arm
  fails (player not ready)? The FadeCommand MUST NOT be dispatched if the target_cue failed
  to arm; the FadeCue is rejected with a `failed` ActionHandler result.
- What happens when two FadeCues reference the same target_cue concurrently (e.g., a fade-up
  followed immediately by a fade-down before the first completes)? The second command
  replaces/cancels the first within gradient-motiond; the Python engine MUST NOT leave the
  target_cue in an inconsistent armed/disarmed state.
- What if MTC transport is stopped mid-fade? The fade pauses until MTC resumes — it does not
  snap to `target_value`.
- If `fade_complete` is never received from gradient-motiond after a fade-down
  (`target_value=0`) is dispatched (e.g., gradient-motiond crashes mid-fade), the Python
  engine MUST apply a timeout of (`duration` + 1 second). On expiry, the target_cue is
  forcibly disarmed and a warning is logged. This prevents permanently stuck armed cues
  without requiring operator intervention.
- If gradient-motiond is unreachable at FadeCue dispatch time, the FadeCue fails with a
  logged error; the target_cue is NOT mutated. (See FR-013.)

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST route all NNG commands with `target="gradientengine"` to
  gradient-motiond without executing any local Python handler for them.
- **FR-002**: The system MUST register a STATUS message handler that listens for
  `fade_complete` events from gradient-motiond and uses the carried `fade_id` (which equals
  the originating `FadeCue.uuid`) to identify the FadeCue, resolve its `action_target`
  (the target_cue), and disarm the target_cue.
- **FR-003**: When a FadeCue fires, the system MUST dispatch a fade-start command to
  gradient-motiond specifying the target OSC endpoint (resolved from the target_cue per
  FR-018), the start value (the target_cue's current normalised OSC value per FR-014, or
  0.0 if the target_cue is not yet playing), the end value (`FadeCue.target_value / 100`),
  the duration (derived from the FadeCue's `CTimecode`), and the curve type.
- **FR-004**: When a FadeCue with `target_value > 0` fires against a target_cue that is not
  currently playing, the system MUST start the target_cue's playback at value 0 before
  dispatching the fade so gradient-motiond's first OSC message is not preceded by an
  audible or visible jump.
- **FR-005**: When a FadeCue with `target_value = 0` fires, the system MUST dispatch a
  fade-start command to gradient-motiond with the target_cue's current OSC value (per
  FR-014) as `start_value` and `0.0` as `end_value`, then wait for the `fade_complete`
  status before disarming the target_cue.
- **FR-006**: The system MUST pre-arm the FadeCue's `action_target` (the target_cue) at
  project load time when `target_value > 0`, applying the same timing as `play`-type
  pre-arming, to eliminate arm latency at cue fire time. Pre-arming is NOT applied for
  `target_value = 0` because the target_cue is expected to already be playing (already
  armed by an earlier cue).
- **FR-007**: On project stop and immediately before initialising a new project, the system
  MUST dispatch a `CANCEL_ALL` command to gradient-motiond before stopping any players.
- **FR-008**: ControllerEngine MUST silently discard STATUS messages whose sender identifies
  as gradient-motiond, to prevent bus-broadcast messages from causing processing errors in
  multi-node setups.
- **FR-009**: AudioCue fade endpoints MUST target the AudioPlayer's OSC port with address
  `/volmaster`. VideoCue fade endpoints MUST target port 7000 with address
  `/videocomposer/layer/{layer_id}/opacity`.
- **FR-010**: All values dispatched to gradient-motiond MUST be normalised to the 0.0–1.0
  range, converting from the FadeCue's `target_value` (0–100 integer) and from the
  target_cue's existing volume representation where necessary.
- **FR-011**: After dispatching a fade-down command (`target_value = 0`), the system MUST
  start a timeout equal to the FadeCue `duration` plus one second. If `fade_complete` is
  not received within that window, the system MUST forcibly disarm the target_cue and log
  a warning identifying the FadeCue UUID, the target_cue UUID, and the fade ID.
- **FR-012**: The FadeCue's `curve_type` (one of `linear`, `exponential`, `logarithmic`,
  `sigmoid`) MUST be passed through to gradient-motiond in the fade-start command. The
  Python engine MUST NOT interpret the curve; it is consumed by gradient-motiond.
- **FR-013**: If dispatch to gradient-motiond fails (NNG send error, daemon unreachable,
  serialization error), the system MUST reject the FadeCue with a `failed` ActionHandler
  result, log an error identifying the FadeCue UUID and the failure cause, and leave the
  target_cue's state unchanged. The system MUST NOT fall back to `play`/`stop` semantics or
  silently drop the cue.

#### FadeCue → FadeCommand value & time mapping

- **FR-014**: At FadeCue dispatch time, the system MUST recover the FadeCommand
  `start_value` from the **target_cue's** local Ossia node cache via
  `target_cue._osc.get_value(path)` for the resolved OSC path (`/volmaster` for audio,
  `/videocomposer/layer/{N}/opacity` for video). The OSC client and node cache MUST be
  read from the target_cue, never from the FadeCue. The system MUST NOT derive
  `start_value` from cached cue configuration (e.g., `target_cue.master_vol`) when the
  target_cue is already playing, because a prior fade may have moved the actual OSC value
  away from the configured one. If the target_cue is not yet playing (fade-up case from
  FR-004), `start_value` is `0.0`.
- **FR-014a**: The Python engine MUST retain a dispatch record (at minimum:
  `fade_id → (target_cue, osc_path, end_value)`) for every dispatched FadeCommand, for the
  lifetime of the fade. On receipt of a `fade_complete` STATUS, the system MUST ensure that
  the next call to `target_cue._osc.get_value(path)` for that OSC path returns the
  dispatched `end_value`, so a subsequent FadeCue dispatch reads a correct `start_value`.
  The exact cache-update mechanism (e.g., `node.parameter.value` direct assignment vs. a
  quiet-set helper) is plan-level — what matters is that the target_cue's cache reflects
  post-fade truth without re-emitting a duplicate OSC message to the player.
- **FR-015**: The FadeCommand `end_value` MUST be derived from `FadeCue.target_value / 100.0`,
  clamped to `[0.0, 1.0]`.
- **FR-016**: The FadeCommand time fields MUST be derived from the current MTC time at
  dispatch (`current_mtc_ms`) and the FadeCue's `duration` (`CTimecode`):
  - `start_mtc_ms = current_mtc_ms` — the fade begins at the moment of dispatch.
  - `duration_ms = duration` converted from `CTimecode` to integer milliseconds.
  - The wire format encodes these as `start_mtc_ms` + `duration_ms` per gradient-motion-engine
    spec FR-011; conceptually they represent `start_time` and `end_time = start_time +
    duration` for curve evaluation.
- **FR-017**: The FadeCue's `curve_type` enum MUST be encoded as the lowercase string of the
  enum value (`"linear"`, `"exponential"`, `"logarithmic"`, `"sigmoid"`) in the FadeCommand
  payload.
- **FR-018**: The FadeCommand OSC endpoint fields (`osc_host`, `osc_port`, `osc_path`) MUST
  be resolved from the **target_cue** at dispatch time. The target_cue's `_osc` and
  `_layer_ids` attributes are the canonical sources; the FadeCue MUST NOT carry or override
  these values:
  - target_cue is an AudioCue → `osc_host = "127.0.0.1"`,
    `osc_port = target_cue._osc.remote_port`, `osc_path = "/volmaster"`.
  - target_cue is a VideoCue → `osc_host = "127.0.0.1"`, `osc_port = 7000`,
    `osc_path = f"/videocomposer/layer/{target_cue._layer_ids[0]}/opacity"`.

### Key Entities

- **FadeCue**: A new cue type that triggers a gradient fade. Fields:
  - `curve_type`: `FadeCurveType` enum — `linear`, `exponential`, `logarithmic`, `sigmoid`.
    Default `linear`.
  - `duration`: `CTimecode`, positive non-zero (None only transient during deserialization).
  - `target_value`: `int` in `[0, 100]`. Default `0`.
  - `action_target`: required reference to the cue being faded.
  - `action_type`: locked to `fade_action`; mutation post-init raises.
- **FadeCommand** (NNG payload): The data structure sent to gradient-motiond to initiate a
  fade — includes target OSC endpoint (host, port, path), start/end values in 0.0–1.0 range,
  duration in seconds, curve type, and a unique fade ID.
- **fade_complete STATUS** (NNG payload): The message gradient-motiond sends when a fade
  finishes — carries the fade ID that maps back to the target_cue for disarm.
- **target_cue** (AudioCue or VideoCue): The media cue being faded, referenced by
  `FadeCue.action_target`. The target_cue is the canonical source of OSC information for
  every FadeCommand: `target_cue._osc.get_value(path)` provides `start_value`,
  `target_cue._osc.remote_port` provides the audio OSC port, `target_cue._layer_ids[0]`
  provides the video layer id, and `target_cue.master_vol` provides the configured volume
  baseline. The Python engine MUST resolve all these from the target_cue, never from the
  FadeCue itself. The target_cue transitions to disarmed state after a fade-down completes.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A fade-in or fade-out cue produces a perceptibly smooth, uninterrupted level
  transition with no audible clicks, visual steps, or abrupt jumps at the start or end.
- **SC-002**: The first OSC message from gradient-motiond reaches the player within one MTC
  quarter-frame (~5 ms) of the fade command being received, ensuring no perceptible delay
  between cue fire and fade onset.
- **SC-003**: After a fade-out completes, the target_cue transitions to disarmed state within
  one second of the `fade_complete` status being received, ready for re-arm.
- **SC-004**: On project stop, all active fades halt and no further OSC volume or opacity
  messages are sent to any player after the stop command is processed.
- **SC-005**: Gradient engine-targeted NNG messages produce no error log entries in either
  NodeEngine or ControllerEngine; all routing is transparent.
- **SC-006**: Pre-arming of fade-in targets at project load introduces no additional latency
  compared to the equivalent `play`-type pre-arm path.

## Assumptions

- `gradient-motiond` is already running on the node before any fade cue fires; the Python
  engine is not responsible for its process lifecycle.
- The NNG bus topology is already established; gradient-motiond joins the bus as a dialer and
  no topology changes are required in the Python engine.
- Fade curve type is set per-FadeCue via `curve_type`; the Python engine passes it through
  in the FadeCommand payload without interpreting or validating curve mathematics.
- DMX cues retain their existing player-side fade mechanism and are out of scope.
- `target_cue._osc.remote_port` is available on an armed AudioCue, and
  `target_cue._layer_ids` is available on an armed VideoCue, at the point the
  ActionHandler dispatches the FadeCommand. The Python engine resolves these from the
  target_cue (the cue referenced by `FadeCue.action_target`), never from the FadeCue.
- Only one active fade per target_cue is expected at a time; concurrent fades on the same
  target are resolved by gradient-motiond's replace/cancel logic, not the Python engine.
- The unit conversion for volume (0–100 integer → 0.0–1.0 float) follows the same convention
  already used in `run_cue.py` line 140.
