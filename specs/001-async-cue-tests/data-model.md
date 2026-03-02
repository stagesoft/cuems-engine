# Data Model: Async Cue Execution Test Suite

**Branch**: `001-async-cue-tests` | **Date**: 2026-02-26

This feature is a test suite — there are no new persistent data entities.
This document describes the **test-domain entities** (mocks, fixtures, helpers)
that model the production entities under test.

## Production Entities Under Test

### Cue (abstract base)

| Attribute | Type | Test Relevance |
|---|---|---|
| `id` | `str` (UUID) | Unique identity for armed-cues tracking |
| `loaded` | `bool` | Guards `go()` — must be `True` after arm |
| `enabled` | `bool` | Guards arm — disabled cues are disarmed |
| `prewait` | `CTimecode` | Delay before `run_cue()` — tested in US1 |
| `postwait` | `CTimecode` | Delay after `run_cue()` — tested in US1 |
| `loop` | `int` | Loop count: 0 = no loop (play once), < 0 = infinite, > 0 = repeat N times — tested in US4 |
| `post_go` | `str \| None` | `'go'` or `'go_at_end'` — tested in US3 |
| `_target_object` | `Cue \| None` | Next cue for post_go chaining |
| `_local` | `bool` | Whether cue runs on this node |
| `_osc` | `PlayerClient \| None` | OSC client assigned during arm |
| `_start_mtc` | `CTimecode \| None` | Set during `run_cue()` |
| `_end_mtc` | `CTimecode \| None` | Set during `run_cue()` |

**Concrete types under test**: `AudioCue`, `VideoCue`, `ActionCue`, `CueList`
**Excluded**: `DmxCue` (partially implemented)

### CueHandler (singleton)

| Attribute | Type | Test Relevance |
|---|---|---|
| `_armed_cues` | `list[Cue]` | Concurrent access target — US2, US5 |
| `_armed_cues_set` | `set[str]` | Fast lookup — thread-safety tests |
| `_lock` | `threading.Lock` | Contention target for stress tests |

**Key methods under test**:
- `arm(cue, init)` → adds to armed list, calls `arm_cue()`
- `disarm(cue)` → removes player, clears loaded flag
- `go(cue, mtc)` → submits `_go_async` to cue orchestration loop
- `_go_async(cue, mtc)` → prewait → run → postwait → loop → post_go → disarm
- `wait_for_cue(task)` → **missing** — tested as expected failure (FR-013)

### AsyncCommsThread (thread manager)

| Attribute | Type | Test Relevance |
|---|---|---|
| `event_loop` | `asyncio.AbstractEventLoop` | IPC loop — must NOT be used for cues |
| `_cue_loop` | `asyncio.AbstractEventLoop` | **New** — cue orchestration loop (FR-011) |

**Key properties under test**:
- Loop isolation: IPC and cue loops are distinct objects
- Task affinity: `go()` submits to `_cue_loop`, not `event_loop`

### PlayerHandler (singleton)

| Attribute | Type | Test Relevance |
|---|---|---|
| `_cue_players` | `dict[Cue, Player]` | Store/remove during arm/disarm — US1, US5 |
| `_lock` | `threading.Lock` | Concurrent access — US2 |

### MtcListener (daemon thread)

| Attribute | Type | Test Relevance |
|---|---|---|
| `main_tc` | `CTimecode` | Polled by `loop_cue()` every 5 ms — US4 |

## Test-Domain Entities (New)

### MockCueFactory

Produces mock Cue objects with configurable attributes. Supports presets
for each cue type.

```
MockCueFactory.audio(prewait=0, postwait=0, loop=1, post_go=None) → AudioCue mock
MockCueFactory.video(prewait=0, postwait=0, loop=1, post_go=None) → VideoCue mock
MockCueFactory.action(action_type='play', target=None) → ActionCue mock
```

### EventLoopFixture

Provides an asyncio event loop running in a background daemon thread.
Mimics the AsyncCommsThread cue orchestration loop.

```
loop, thread = EventLoopFixture.start() → (AbstractEventLoop, Thread)
EventLoopFixture.stop(loop, thread) → None
```

### MockMtcListener

Controllable MTC time source. Tests advance time programmatically.

```
mtc = MockMtcListener(initial_tc='0:0:0:0', framerate='25')
mtc.advance_to(tc: str) → None
mtc.advance_by(milliseconds: int) → None
```

### MockOscClient

Records all `set_value` / `get_value` calls for assertion.

```
osc = MockOscClient()
osc.set_value(key, value) → records (key, value)
osc.get_calls() → list[tuple[str, Any]]
```

## State Transitions

### Cue Lifecycle (canonical)

```
idle ──arm()──→ armed ──go()──→ running ──loop_cue()──→ stopped ──disarm()──→ idle
                                   ↕
                                 paused
                                   │
                                   └──error──→ idle (after cleanup)
```

### Test-Observable States

| Transition | Observable Side Effect |
|---|---|
| idle → armed | `cue.loaded = True`, player in `_cue_players`, OSC client assigned |
| armed → running | `_go_async` task created on cue loop, `_start_mtc` set |
| running → stopped | `loop_cue` exits, MTC disconnected (OSC `/mtcfollow` = 0) |
| stopped → idle | `disarm()` called, player killed, `cue.loaded = False` |
| any → error | Exception logged, resources cleaned, cue disarmed |
