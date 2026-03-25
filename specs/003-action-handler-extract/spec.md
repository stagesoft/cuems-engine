# Feature Specification: Dedicated Action Handler with Extensibility

**Feature Branch**: `003-action-handler-extract`  
**Created**: 2026-03-25  
**Status**: Draft  
**Input**: User description: "extract all ActionCue related methods from CueHandler into a new ActionHandler class. It should be able to accept external methods to redirect them as part of the logic of it's internal handlers"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - No regression for live action cues (Priority: P1)

As a show operator, I need action cues to behave the same as before this change so live
shows do not gain new failures or surprises during playback.

**Why this priority**: Operational continuity is mandatory; refactoring must not weaken
reliability of action-driven cue control.

**Independent Test**: Run the full action-cue acceptance set for all supported action
types and invalid inputs; compare outcomes to the pre-change baseline (same visible cue
states, same safety on errors).

**Acceptance Scenarios**:

1. **Given** a loaded show with actionable targets, **When** each supported cue-level
   action is triggered, **Then** the target cue reaches the same end state as before the
   refactor.
2. **Given** invalid or unsupported action input, **When** it is processed, **Then** the
   system rejects it safely without corrupting unrelated cue state, matching prior
   behavior.

---

### User Story 2 - Integrators can extend action handling (Priority: P2)

As an integrator or maintainer, I need to supply custom behavior that participates in
action processing so site-specific or experimental flows can run without forking core
orchestration.

**Why this priority**: Extensibility reduces long-term cost and supports controlled
customization without duplicating lifecycle logic.

**Independent Test**: Register an externally supplied behavior for a defined hook point;
trigger a matching action and verify the custom path ran (observable side effect or
trace) while defaults still apply when no extension is registered.

**Acceptance Scenarios**:

1. **Given** a valid extension registration for a documented hook, **When** a matching
   action is processed, **Then** the registered behavior is invoked in the documented
   order relative to default handling.
2. **Given** no extension registered, **When** the same action is processed, **Then**
   default handling alone applies with the same outcome as User Story 1.
3. **Given** extensions registered from both the cue orchestration layer and the node
   runtime layer, **When** an action runs, **Then** both registration sources are honored
   according to the documented merge order without duplicate or ambiguous application.

---

### User Story 3 - Clear separation of responsibilities (Priority: P3)

As a maintainer, I need action-command logic isolated from general cue lifecycle
orchestration so reviews and changes to actions do not entangle arm, go, and player
coordination.

**Why this priority**: Separation improves reviewability and lowers risk of unintended
side effects when editing action behavior.

**Independent Test**: Inspect product documentation or architecture notes: action
processing responsibilities are listed under one dedicated component; general cue list
and playback orchestration no longer list per-action-type branching for action cues.

**Acceptance Scenarios**:

1. **Given** the runtime architecture description, **When** an engineer locates where
   action cues are executed, **Then** a single dedicated action-handling component is
   named as the owner of that behavior.
2. **Given** a change request affecting only action types, **When** the change is
   implemented, **Then** the touch surface is confined to the action-handling component
   and its contracts, not to unrelated orchestration modules.

### Edge Cases

- Two extensions registered for the same hook: resolution MUST follow FR-008 and be
  covered by an automated test.
- Extension raises an error mid-processing: failure MUST be contained, logged, and MUST
  not leave the show in an undefined mixed state.
- Extension requests to fully replace default handling: contract MUST state whether
  replacement is allowed and how fallbacks work.
- Action arrives while target is mid-transition: behavior MUST remain deterministic and
  safe (idempotent or ordered application per contract).
- Registrations from cue orchestration vs node runtime conflict: resolution MUST follow
  FR-009 and be covered by tests.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: All processing specific to action cues (validation, dispatch, and
  per-action-type behavior) MUST be owned by a dedicated action-handling component,
  separate from general cue lifecycle orchestration.
- **FR-002**: The general cue orchestration entry path for running an action cue MUST
  delegate to the dedicated action-handling component without duplicating per-action
  branching.
- **FR-003**: The action-handling component MUST expose a documented way to register
  externally supplied behaviors (callbacks or equivalent) that are invoked at defined
  points during processing of supported action types.
- **FR-004**: The contract for external behaviors MUST specify invocation order (e.g.
  before default, after default, or replace default when indicated), and what context
  is passed (action type, target identity, outcome channel).
- **FR-005**: When no external behavior is registered for a hook, processing MUST match
  the current product behavior for that action type (regression baseline).
- **FR-006**: Unsupported action types and missing or invalid targets MUST still be
  rejected safely with no unintended changes to unrelated cues, consistent with existing
  safety guarantees.
- **FR-007**: Every processed action MUST still yield a single observable outcome
  category (success, no-op success, rejected, or failed) suitable for operator
  diagnostics, at least as informative as today.
- **FR-008**: If more than one external behavior is registered for the same hook, the
  product MUST follow exactly one documented resolution rule (for example: last
  registration wins, first wins, or duplicate registration is rejected at register
  time).
- **FR-009**: External behaviors MUST be registrable from both the cue orchestration
  entry point and the node runtime entry point; the product MUST document how
  registrations from each source combine (ordering, precedence, and deduplication).
- **FR-010**: When an extension or default handler produces a result that must reach the
  controller or other peers, the product MUST support sending that outcome through the
  standard node-to-controller NNG channel and MUST allow substituting an alternative
  sender that implements the same documented delivery contract (including other
  `AsyncCommsThread`-style communication threads used for NNG-backed sends).

### Non-Functional Requirements *(mandatory)*

- **NFR-001 (Code Quality)**: The implementation MUST satisfy defined linting,
  formatting, and static-analysis checks for impacted modules.
- **NFR-002 (Testing)**: Behavior changes MUST be covered by automated tests at the
  appropriate level, including regression tests for all supported action types and tests
  that prove at least one external behavior is invoked when registered.
- **NFR-003 (UX Consistency)**: Operator-visible terminology, log messages, and error
  semantics for action outcomes MUST remain consistent with existing show-control
  patterns unless explicitly approved in this specification.
- **NFR-004 (Performance)**: Action processing MUST remain within the same agreed
  live-operation time budget as before the refactor (no regression beyond a documented
  tolerance); validation MUST include sampling or automated timing checks on the action
  path.

### Key Entities *(include if feature involves data)*

- **Action command**: A received instruction with action type, target reference, and
  source identity, applied during show runtime.
- **Dedicated action-handling component**: The runtime unit responsible for validating
  and executing action commands and for hosting extension hooks.
- **Extension registration**: A binding between a hook point and an externally supplied
  behavior, including scope (which action types or categories it applies to).
- **Processing outcome**: The result of one action command (applied, applied without
  change, rejected, or failed) with optional human-readable reason.
- **Result delivery sink**: An abstraction through which action outcomes (or extension
  telemetry) are forwarded to peers; the default aligns with the existing node NNG
  client, with optional injection of an equivalent implementation.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of supported cue-level action types pass the same acceptance checks as
  the pre-refactor baseline in automated verification.
- **SC-002**: 100% of invalid or unsupported action cases remain safely rejected without
  unintended changes to unrelated running cues, verified by automated checks.
- **SC-003**: At least one automated test demonstrates that a registered external
  behavior is invoked when configured, and skipped when not configured; at least one
  test demonstrates registration from each supported entry point (cue orchestration and
  node runtime) when both are required by the contract.
- **SC-004**: Documented hook contract (order, replace vs augment, error handling) is
  complete and referenced from the action-handling component’s public contract.
- **SC-005**: Automated verification demonstrates that a substitute result-delivery sink
  receives at least one emitted action outcome when configured, and that the default
  path uses the standard node-to-controller messaging client when no substitute is
  configured.
- **SC-006**: No new mandatory quality-gate violations are introduced in the modified
  scope (lint, format, static analysis as defined for the repository).
- **SC-007**: All required automated verification for this change passes in the
  standard pre-merge workflow.
- **SC-008**: Operator-facing action outcome wording remains aligned with existing
  show-control vocabulary in a documented review (no unexplained renames).
- **SC-009**: Action-path latency under normal show load stays within the same agreed
  live-operation budget as before this change, verified by a defined sampling or timing
  method documented for the release.

## Assumptions

- The set of supported cue-level action types and safety rules match the current product
  baseline unless a separate change updates that list.
- "External methods" means integrator-supplied callables or equivalent registrations,
  not ad-hoc string scripts, unless a future specification adds scripting.
- The dedicated component may retain a stable name in code (e.g. ActionHandler) for
  discoverability; this specification describes responsibilities, not file layout.
