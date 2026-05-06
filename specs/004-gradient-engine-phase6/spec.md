# Feature Specification: Gradient Motion Engine — Python-Side Integration (Phase 6)

**Feature Branch**: `004-gradient-engine-phase6`
**Created**: 2026-04-27
**Status**: Draft
**Input**: Phase 6 of the Gradient Motion Engine integration plan, scoped to the cuems-engine
Python changes required to dispatch fade commands via the NNG bus.

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
  `FadeCue` with action_type `fade_action` represents "fade `action_target` to `target_value`
  over `duration` using `curve_type`".
- Q: How is `fade_id` generated for the FadeCommand sent to gradient-motiond? → A:
  `fade_id = FadeCue.uuid` (the FadeCue's own cue identifier). Verified compatible with
  gradient-motion-engine which treats `fade_id` as an arbitrary controller-assigned
  `std::string` with no format restrictions.
- Q: What happens when a FadeCue dispatches but gradient-motiond is unreachable (daemon not
  running, NNG send fails, etc.)? → A: Hard-fail. The FadeCue is rejected with a `failed`
  status through the existing ActionHandler result path; an error is logged identifying the
  unreachable daemon and the FadeCue UUID; the target_cue's state is NOT mutated (no arm,
  no play, no stop). The operator must observe the failure and react (restart daemon,
  re-fire). Silent drops and fallback-to-play/stop behaviours are explicitly rejected.
- Q: How does the Python engine recover the actual OSC value for `start_value` at FadeCue
  dispatch? → A: Read from the **target_cue's** local Ossia node cache via
  `target_cue._osc.get_value(path)` at dispatch time, where `target_cue =
  FadeCue.action_target`. The target_cue MUST already be playing for fade_action to make
  sense; envelope-style "fade from silence" semantics are explicitly out of scope for
  Phase 6 and deferred to a future iteration. Naming convention: throughout the spec,
  `target_cue` is the canonical name for `FadeCue.action_target` to make it unambiguous
  that all OSC information (port, layer id, current value) is recovered from the
  target_cue, never from the FadeCue.
- Q: Does fade_action disarm the target_cue on `fade_complete`? → A: No. fade_action MUST
  NOT disarm `target_cue`. The FadeCue itself follows general cue lifecycle (disarms
  itself when its `loop_fadeCue` block exits at `_end_mtc`). The target_cue is disarmed
  by whatever player-stop or follow-up cue would normally have disarmed it.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Fade Action (Priority: P1) 🎯 MVP

A show operator fires a `FadeCue` against a currently-playing target_cue (Audio or Video).
The target media's volume/opacity smoothly transitions from its current value to
`target_value/100` over `duration` using `curve_type`, time-locked to the show's MTC
timecode. The FadeCue itself runs for the full `duration` (occupying the cue runner) so
follow-up cues sequence correctly; gradient-motiond drives the OSC value changes on the
player.

**Why this priority**: Fade-action is the baseline gradient capability. Once it works
end-to-end, the FadeCue → NNG → gradient-motiond → OSC → player path is proven for both
fade-up (target above current) and fade-to-zero (target below current) directions, since
both are the same operation with different `target_value`s.

**Independent Test**: Can be fully tested by playing an AudioCue, then firing a FadeCue
(target_value=80, duration=3s, curve_type=linear) targeting it and observing that the audio
level transitions smoothly from its current level to 80% over 3 seconds with no audible
step.

**Acceptance Scenarios**:

1. **Given** an AudioCue is playing at full volume and a FadeCue targets it with
   `target_value=0`, **When** the operator fires the FadeCue, **Then** the audio level
   smoothly falls from its current level to silence within `duration`, the FadeCue
   occupies the cue runner for `duration`, and the target_cue remains armed (general
   cue lifecycle decides any subsequent disarm).
2. **Given** a VideoCue is playing at some opacity and a FadeCue targets it with
   `target_value=100`, **When** the operator fires the FadeCue, **Then** the video layer
   opacity smoothly rises to full within `duration`.
3. **Given** a FadeCue is in progress, **When** MTC transport is paused, **Then** the
   fade progression pauses with timecode and resumes when transport resumes.
4. **Given** a FadeCue is in the cue list and a project is loaded, **When** the project
   loads (script arm phase), **Then** the FadeCue's `action_target` is pre-armed so no
   arm-delay occurs when the FadeCue fires.

---

### User Story 2 — Clean Project Load and Stop (Priority: P2)

When an operator loads a new project or triggers a script stop, any fades that are actively
running are immediately cancelled, preventing stale volume or opacity commands from reaching
players that are no longer active.

**Why this priority**: A show that stops mid-fade must leave the system in a clean state.
Stale OSC commands sent after a player has stopped could cause unpredictable behaviour on
the next project load.

**Independent Test**: Can be tested by starting a long fade (e.g., 30-second fade), then
triggering a project stop before the fade completes, and verifying that no further OSC
messages are sent to the audio player after the stop.

**Acceptance Scenarios**:

1. **Given** a fade is in progress, **When** the operator stops the project, **Then** all
   active fades are cancelled before any players are stopped, and no further OSC messages
   reach the players.
2. **Given** a fade is in progress, **When** the operator loads a new project, **Then**
   all active fades from the previous project are cancelled before the new project
   initialises.
3. **Given** no fades are in progress, **When** a project stop is triggered, **Then** the
   system operates normally without errors.

---

### User Story 3 — Gradient Engine Message Routing Isolation (Priority: P3)

NNG bus messages destined for gradient-motiond are transparently forwarded without being
processed by the Python engine's own command dispatch. STATUS messages from gradient-motiond
are silently ignored by ControllerEngine.

**Why this priority**: Correct routing is a system correctness prerequisite for all other
stories. If the Python engine erroneously processes or discards gradient commands, fades
will break silently.

**Independent Test**: Can be tested by sending a synthetic `gradientengine`-targeted NNG
command via the bus and verifying that the Python NodeEngine does not attempt to process
it as a local command, and that gradient-motiond receives it.

**Acceptance Scenarios**:

1. **Given** the NNG bus carries a command with `target="gradientengine"`, **When**
   NodeEngine processes the incoming message, **Then** it passes through without error
   and no local handler attempts to execute it.
2. **Given** gradient-motiond sends any STATUS message, **When** ControllerEngine
   receives it (because the bus broadcasts to all peers), **Then** ControllerEngine
   silently ignores it without logging errors or attempting processing.

---

### Edge Cases

- What happens when a FadeCue fires but the target_cue is not armed? The handler MUST
  arm the target_cue (general cue logic) before dispatching the FadeCommand. If arming
  fails, the FadeCue is rejected with a `failed` ActionHandler result and no FadeCommand
  is dispatched.
- What happens when two FadeCues reference the same target_cue concurrently? The second
  command replaces/cancels the first within gradient-motiond; the Python engine MUST NOT
  leave the target_cue in an inconsistent state.
- What if MTC transport is stopped mid-fade? The fade pauses until MTC resumes — it does
  not snap to `target_value`.
- If gradient-motiond is unreachable at FadeCue dispatch time, the FadeCue fails with a
  logged error; the target_cue is NOT mutated. (See FR-013.)

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST route all NNG commands with `target="gradientengine"` to
  gradient-motiond without executing any local Python handler for them.
- **FR-003**: When a FadeCue fires, the system MUST dispatch a fade-start command to
  gradient-motiond specifying the target OSC endpoint (resolved from the target_cue per
  FR-018), the start value (the target_cue's current OSC value per FR-014), the target
  value (`FadeCue.target_value`), the duration (derived from the FadeCue's `CTimecode`),
  the start time (current MTC), and the curve type.
- **FR-006**: The system MUST pre-arm the FadeCue's `action_target` (the target_cue) at
  project load time, applying the same timing as `play`-type pre-arming, to eliminate
  arm latency at cue fire time.
- **FR-007**: On project stop and immediately before initialising a new project, the
  system MUST dispatch a `CANCEL_ALL` command to gradient-motiond before stopping any
  players.
- **FR-008**: ControllerEngine MUST silently discard STATUS messages whose sender
  identifies as gradient-motiond, to prevent bus-broadcast messages from causing
  processing errors in multi-node setups.
- **FR-009**: AudioCue fade endpoints MUST target the AudioPlayer's OSC port with address
  `/volmaster`. VideoCue fade endpoints MUST target port 7000 with address
  `/videocomposer/layer/{layer_id}/opacity`.
- **FR-012**: The FadeCue's `curve_type` (one of `linear`, `exponential`, `logarithmic`,
  `sigmoid`) MUST be passed through to gradient-motiond in the fade-start command. The
  Python engine MUST NOT interpret the curve; it is consumed by gradient-motiond.
- **FR-013**: If dispatch to gradient-motiond fails (NNG send error, daemon unreachable,
  serialization error), the system MUST reject the FadeCue with a `failed` ActionHandler
  result, log an error identifying the FadeCue UUID and the failure cause, and leave the
  target_cue's state unchanged. The system MUST NOT fall back to `play`/`stop` semantics
  or silently drop the cue.
- **FR-014**: At FadeCue dispatch time, the system MUST recover the FadeCommand
  `start_value` from the **target_cue's** local Ossia node cache via
  `target_cue._osc.get_value(path)` for the resolved OSC path (`/volmaster` for audio,
  `/videocomposer/layer/{N}/opacity` for video). The OSC client and node cache MUST be
  read from the target_cue, never from the FadeCue.
- **FR-018**: The FadeCommand OSC endpoint fields (`osc_port`, `osc_path`) MUST
  be resolved from the **target_cue** at dispatch time. The target_cue's `_osc` and
  `_layer_ids` attributes are the canonical sources; the FadeCue MUST NOT carry or
  override these values:
  - target_cue is an AudioCue → `osc_port = target_cue._osc.remote_port`,
    `osc_path = "/volmaster"`.
  - target_cue is a VideoCue → `osc_port = 7000`,
    `osc_path = f"/videocomposer/layer/{target_cue._layer_ids[0]}/opacity"`.
- **FR-019**: A FadeCue MUST occupy the cue runner for its `duration` so that
  general cue lifecycle (auto-disarm of the FadeCue itself via the end-of-cue path)
  fires only after the gradient fade has elapsed. This is implemented by a
  `loop_fadeCue` branch in `loop_cue.py` that blocks until `mtc.main_tc.milliseconds
  >= cue._end_mtc.milliseconds` (with `_stop_requested` cancellation polling).
- **FR-020**: The FadeCue MUST NOT have a branch in the `run_cue` singledispatch
  registry. It MUST inherit `ActionCue` dispatch behaviour up through `_ACTION_HANDLERS`,
  which routes to the `fade_action` handler. The `fade_action` handler MUST NOT call
  `disarm` on the target_cue and MUST NOT use side-channel attributes such as
  `_fade_initial_volume` (envelope-style fades are deferred to a future iteration).

### Key Entities

- **FadeCue**: A new cue type that triggers a gradient fade. Fields:
  - `curve_type`: `FadeCurveType` enum — `linear`, `exponential`, `logarithmic`, `sigmoid`.
    Default `linear`.
  - `duration`: `CTimecode`, positive non-zero (None only transient during deserialization).
  - `target_value`: `int` in `[0, 100]`. Default `0`.
  - `action_target`: required reference to the cue being faded.
  - `action_type`: locked to `fade_action`; mutation post-init raises.
- **FadeCommand** (NNG payload): The data structure sent to gradient-motiond to initiate
  a fade. Built by `ActionHandler._build_payload(target_cue, fade_cue, start_time)`,
  then wrapped by `NodeCommunications.send_fade_command` which injects envelope fields
  (`command="start_fade"`, `fade_id=FadeCue.uuid`, `osc_host="127.0.0.1"`,
  `curve_params={}`). See [contracts/fade_command.json](contracts/fade_command.json).
- **target_cue** (AudioCue or VideoCue): The media cue being faded, referenced by
  `FadeCue.action_target`. The target_cue is the canonical source of OSC information for
  every FadeCommand: `target_cue._osc.get_value(path)` provides `start_value`,
  `target_cue._osc.remote_port` provides the audio OSC port,
  `target_cue._layer_ids[0]` provides the video layer id. The Python engine MUST resolve
  all these from the target_cue, never from the FadeCue itself.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A fade action produces a perceptibly smooth, uninterrupted level transition
  with no audible clicks, visual steps, or abrupt jumps at the start or end.
- **SC-002**: The first OSC message from gradient-motiond reaches the player within one
  MTC quarter-frame (~5 ms) of the fade command being received, ensuring no perceptible
  delay between cue fire and fade onset.
- **SC-004**: On project stop, all active fades halt and no further OSC volume or opacity
  messages are sent to any player after the stop command is processed.
- **SC-005**: Gradient engine-targeted NNG messages produce no error log entries in
  either NodeEngine or ControllerEngine; all routing is transparent.
- **SC-006**: Pre-arming of fade targets at project load introduces no additional latency
  compared to the equivalent `play`-type pre-arm path.

## Assumptions

- `gradient-motiond` is already running on the node before any fade cue fires; the Python
  engine is not responsible for its process lifecycle.
- The NNG bus topology is already established; gradient-motiond joins the bus as a dialer
  and no topology changes are required in the Python engine.
- Fade curve type is set per-FadeCue via `curve_type`; the Python engine passes it through
  in the FadeCommand payload without interpreting or validating curve mathematics.
- DMX cues retain their existing player-side fade mechanism and are out of scope.
- `target_cue._osc.remote_port` is available on an armed AudioCue, and
  `target_cue._layer_ids` is available on an armed VideoCue, at the point the
  ActionHandler dispatches the FadeCommand.
- A target_cue is expected to be already playing when its FadeCue fires (envelope-style
  start-from-silence is out of scope for Phase 6).
- Only one active fade per target_cue is expected at a time; concurrent fades on the
  same target are resolved by gradient-motiond's replace/cancel logic.
- `CTimecode.milliseconds_rounded` returns an integer-millisecond representation suitable
  for direct JSON serialisation in the FadeCommand payload.
