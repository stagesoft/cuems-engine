# ActionHandler Architecture — Decision and Migration Plan

**Date:** 2026-05-15 — revised 2026-05-19 (post NNG→OSC migration, commit `29c28c1`) — revised 2026-08-10 (decision locked)
**Scope:** `src/cuemsengine/cues/ActionHandler.py` and its call sites
**Status:** **Accepted architectural decision.** Composition-owned instance with constructor DI is the sole
approach; alternatives were evaluated and discarded. Migration path below is authoritative.
**Companion:** `specs/planning/controller-integration-contracts.md` — the two documents MUST stay in sync.

---

## 0. Decision Summary

| Topic | Decision |
|---|---|
| Ownership | `CueHandler` constructs and owns one `ActionHandler`; no module-level singleton |
| Dependency direction | `ActionHandler` depends on `CueHandlerProtocol`, never on `CueHandler` or `PLAYER_HANDLER` |
| Outcome delivery | **Listener list.** Default NNG delivery is unconditional and internal; consumers register alongside it |
| Hook system | Retained as a **planned future feature**, justified by the controller-integration contracts. Reserved for extensions that *participate* in an outcome |
| Controller feedback | Uses **outcome listeners**, not `after_dispatch` hooks |
| `node_layer` registration layer | **Retained** |
| Multiple hardware controllers | **Supported.** Hooks are keyed by owner; registrations no longer evict each other |
| Action-type set | **Deliberately closed to runtime extension.** New actions ship as new entries in `_ACTION_HANDLERS` |
| Hardware-triggered actions | `dispatch_action(action_type, target, mtc, params=None)` — scheduled in this migration |
| Fade payload construction | Becomes a per-type builder registry before the next fadeable cue type (§7 B2) |

**Process scope.** `ActionHandler` exists only in the **node-engine process**. `ControllerEngine.py` imports
neither `CueHandler` nor `ActionHandler`. On a controller host running both services there are two independent
instances in two processes that share no state — the same rule that governs `MtcListener` and the OSC senders.

---

## 1. Current State: Three Architectural Layers Tangled Together

`ActionHandler.py` mixes three conceptual layers in a single file with no clean boundary.

### Layer A — The Class (`ActionHandler`)
Owns lifecycle state: hook registry, result sink, emit flag, cue-handler reference.
Responsibilities: hook registration, hook resolution, result delivery, dispatch coordination.

### Layer B — The Module-Level Handler Registry
`_ACTION_HANDLERS: dict[str, Callable]` — static mapping from action-type string to implementation.
`_handle_play` … `_handle_fade_action` — concrete per-action implementations.
`_ready_action_target`, `_build_fade_payload` — shared helpers with no class affiliation.
`_handle_fade_action` additionally reaches a second module-level singleton (`PLAYER_HANDLER`) directly.

### Layer C — The Proto-Singleton
`ACTION_HANDLER = ActionHandler()` at `ActionHandler.py:782` — a single instance created unconditionally at
import time. Three sites configure it afterwards:

| Site | What it does |
|------|--------------|
| `CueHandler.py:19` | top-level `from .ActionHandler import ACTION_HANDLER as _ACTION_HANDLER_SINGLETON` |
| `CueHandler.py:954` | `_ACTION_HANDLER_SINGLETON.bind_cue_handler(CUE_HANDLER)` |
| `NodeEngine.py:136-137` | `finalize_node_layer_bindings()` then `set_result_sink(self._action_result_sink)` |

The `NodeEngine` calls live in **`_setup_nng_command_callback`**, not `__init__`, and `finalize` runs *before*
`set_result_sink`.

### Two outcome mechanisms, never previously distinguished

This distinction is load-bearing and was undocumented. It governs every decision in §3.2.

| | `after_dispatch` hook | result sink / listener |
|---|---|---|
| Runs | inside `execute_action`, **before** the outcome is final | after the outcome is final |
| On exception | **rewrites the outcome to `failed`** and breaks the loop (`ActionHandler.py:338-348`) | swallowed and logged (`ActionHandler.py:208-211`) |
| Can change the result | **yes** | no |

`NodeEngine._action_result_sink` deliberately relies on sink semantics: its in-line comment at
`NodeEngine.py:918-920` states that an exception in the `cue_enabled` side effects must never starve the
Controller UI update. Converting it to a hook would let an unrelated side-effect failure turn an applied
`enable` into a `failed` outcome. **Hooks participate; listeners observe.**

---

## 2. Identified Problems

### P1 — Cross-coupling via class name (not interface)
Every module-level `_handle_*` function calls `ActionHandler._action_result(...)` (28 call sites in the file).
The implementations are coupled to the class **by name**, not to a protocol or injected factory. Handlers cannot
be reused or unit-tested without importing the full class.

### P2 — `@staticmethod` that doesn't belong on the class
`_action_result` is a pure data factory with no access to `self` or `cls`. As a `@staticmethod` consumed
primarily by module-level functions it is the worst of both worlds: not a method (no `self` use), not free
(requires the class import).

### P3 — Singleton-but-not-enforced
`ACTION_HANDLER` is created unconditionally at module load, but nothing prevents `ActionHandler()` being
instantiated again. The singleton is implicit, undocumented and unenforceable.

Under the decision, P3 is **scoped, not eliminated**: `CUE_HANDLER` remains a module-level singleton, so
`CUE_HANDLER.action_handler` is a shorter path to the same process-global. What changes is that there is exactly
one owner and one construction site. True application-level DI would require threading the instance from a
composition root (`NodeEngine`) and making `CUE_HANDLER` lazily constructed — see §3.1, *Why the constructor
cannot take the sink*.

### P4 — Multi-phase initialization across three files
The constructor leaves the object incomplete. `bind_cue_handler` must run before any dispatch method is useful;
`set_result_sink` must run after comms are ready. This temporal coupling is invisible to the type system and
silently produces broken objects if initialization order changes.

Note that one of the three phases is hollow: `finalize_node_layer_bindings()` (`ActionHandler.py:158-163`) is a
`return`-only stub with a single caller.

### P5 — Circular import — **RESOLVED (commit `4d53856`)**
Historically `ActionHandler` referenced `CueHandler` and vice-versa, broken by lazy imports.

**Commit `4d53856` ("Resolve ActionHandler → CueHandler circular import using a protocol") fixed this.**
`ActionHandler.py` now declares the `CueOrchestrator` Protocol (`ActionHandler.py:51-63`) and imports no
`CueHandler`. Its transitive imports (`NodeCommunications` → `AsyncCommsThread`, `NodesHub`) do not reach
`CueHandler` either. **There is no cycle today.**

Two residues remain:

1. **Five vestigial lazy imports** that no longer break any cycle and are now pure misdirection —
   `CueHandler.py:835`, `CueHandler.py:849`, `run_cue.py:559`, `NodeEngine.py:134`, `NodeEngine.py:902`.
   `run_cue.py:66` carries a comment citing the ActionHandler lazy import as precedent, propagating the stale
   belief.
2. **Naming divergence.** The protocol is called `CueOrchestrator` in code and `CueHandlerProtocol` in both
   planning documents. **`CueHandlerProtocol` is the chosen name; the code is renamed in Step 4.**

### P6 — Test-isolation API bleeding into production
`clear_action_extensions()` and `set_emit_enabled()` exist purely to reset the singleton between tests
(`test_action_cue.py:68-73`, `:612`, `:622`, `:627`, `:638`). Test concerns exposed in the production API.

### P7 — `NodeEngine` accesses a protected method, and the sink shape is inverted
`NodeEngine._action_result_sink` (`NodeEngine.py:898`) calls `ACTION_HANDLER._default_result_sink(outcome)` at
`NodeEngine.py:905`, bypassing the public interface.

The protected access is a symptom. The cause is that installing a sink **replaces** the transport, so every
sink implementer is expected to call the transport back by hand. Forgetting that one line silently stops all
`action_cue_outcome` NNG traffic to the Controller — a failure with no error on the UI path. The single slot
also means the first controller module that wants outcomes must steal it from `NodeEngine`. §3.2 replaces the
shape rather than renaming the method.

### P8 — `_ALL_ACTIONS` is a misleading sentinel
`_ALL_ACTIONS: frozenset[str] = frozenset()` (`ActionHandler.py:48`) means "no filter / match all", not "the set
of all actions". Consumers: `register_action_hook` (`:141`), `unregister_action_hook` (`:153`); the wildcard
semantics are implemented by truthiness in `_filter_matches` (`:66-69`) and inline in `_wrap_for_action`
(`:192`). Non-obvious at every one of those sites.

### P9 — `_handle_fade_action` depends on a second hidden global (introduced by `29c28c1`)
`_handle_fade_action` calls `PLAYER_HANDLER.get_gradient_client()` (`ActionHandler.py:605`) with
`PLAYER_HANDLER` imported at module top level (`:24`). The handler receives `ch: CueHandlerProtocol` as its
first argument and then bypasses it to reach `GradientClient` through a parallel global, making the `ch`
injection pointless for this dependency. `CueHandler` already imports `PLAYER_HANDLER` itself
(`CueHandler.py:17`), so a forwarding accessor costs no new import there.

### P10 — Two unsynchronised sources of truth for the action set
`SUPPORTED_CUE_ACTIONS` (`ActionHandler.py:31-43`) and the keys of `_ACTION_HANDLERS` (`:768-780`) are
hand-maintained duplicates of the same list. `execute_action` gates on the frozenset (`:245`) and again on the
dict (`:285`), and the second branch — `"No handler registered for {action_type}"` — is **currently
unreachable**. Any future divergence is a silent behaviour change.

### P11 — Hook registration silently evicts prior registrations
`self._hooks[key] = fn` with `key = (phase, source, filter_key)` (`ActionHandler.py:141-144`). Two consumers
registering the same `(phase, source, filter)` — which the controller-integration Pattern A does — means the
second **deletes** the first with no error. `unregister_action_hook` has the mirror defect: it pops by the same
key, so one module's `detach()` removes another module's hook. Multiple simultaneous hardware controllers are a
confirmed requirement, so this is a correctness defect, not a theoretical one.

### P12 — `ch` may be `None` at dispatch, failing silently
`execute_action` passes `self._cue_handler` (Optional) straight into handlers (`:293-296`), and
`_ready_action_target` calls `ch.arm` unguarded (`:389`). Before binding this raises `AttributeError`, which the
blanket `except` at `:328` converts into a generic `"failed"` outcome with no indication of the real cause — a
silent-failure class the constitution forbids. Constructor DI removes the state by construction.

### P13 — Fade dispatch loses `end_value` records on partial failure
`_handle_fade_action` (`:631-665`) sends layer-by-layer, then records `end_value` for every entry in a second
loop. On a failure at layer *N* it returns early, so the layers `0..N-1` that **did** receive the fade never get
recorded. Their next fade computes `start_value` from a stale pre-fade level — the exact defect class that
`2608ea8` and `afebe48` were written to eliminate.

The comment at `:627-630` states the intent as "dispatch ALL entries before mutating anything… state must
remain unchanged". That invariant is unachievable: the OSC sends are not atomic, so layers `0..N-1` *are*
already faded on the player. The engine-side record must mirror what was actually sent. Folded into §7 B2 as an
acceptance criterion.

---

## 3. The Decision — Composition-Owned Instance with Constructor DI

`ActionHandler` becomes a plain class that receives its dependencies at construction time. `CueHandler` creates
and owns the instance. `NodeEngine` receives it via `CueHandler`, not by importing a module singleton.

Formal-singleton (`__new__`/Borg) and all-static-class variants were evaluated and discarded: both make the
hidden global state more ceremonious without addressing P1, P2, P4, P6, P7, P9, P11 or P12, and neither can be
injected under test.

### 3.1 Structural changes

```python
# ActionHandler.py — no module-level singleton, no bind_cue_handler()
class ActionHandler:
    def __init__(self, cue_handler: "CueHandlerProtocol") -> None:
        self._ch = cue_handler          # set at construction, never None
        self._lock = threading.Lock()
        self._hooks: dict[HookKey, Callable[[ActionHookContext], Any]] = {}
        self._listeners: list[Callable[[dict], None]] = []

# CueHandler.py — owns the instance
class CueHandler:
    def __init__(self) -> None:
        ...
        self.action_handler = ActionHandler(self)

    def get_gradient_client(self):
        """Forwarding accessor — PLAYER_HANDLER is already imported here."""
        return PLAYER_HANDLER.get_gradient_client()
```

**Why the constructor cannot take the sink.** `CUE_HANDLER = CueHandler()` is constructed at **module import
time** (`CueHandler.py:952`), so under this design `ActionHandler` is constructed at import time too — while
`NodeEngine`, the only object that owns a sink, is constructed much later and imports `CUE_HANDLER` at
`NodeEngine.py:17`. Constructor-only injection of the outcome consumer is therefore impossible without making
`CUE_HANDLER` lazily constructed, which would touch every `from .cues.CueHandler import CUE_HANDLER` site.
`ActionHandler.__init__` takes **no** `result_sink` parameter; outcome consumers register post-construction via
§3.2.

**Module-level result factory** — extracted from the class, fixes P1 and P2:

```python
def _make_action_result(
    status: str, action_type: str, target_id: str | None, reason: str | None = None
) -> dict:
    return {"status": status, "action_type": action_type,
            "target_id": target_id, "reason": reason}
```

All `_handle_*` functions call it directly. No reference to the `ActionHandler` class name remains outside the
class body.

**`_handle_fade_action` routes `GradientClient` through `ch`** — fixes P9:

```python
def _handle_fade_action(ch, action_cue, target, mtc, frozen_mtc_ms):
    gradient_client = ch.get_gradient_client()
```

The `from ..players.PlayerHandler import PLAYER_HANDLER` import is removed from `ActionHandler.py`.

**Sentinel rename** — fixes P8: `_ALL_ACTIONS` → `_MATCH_ALL`, with the wildcard semantics documented at
`_filter_matches` and `_wrap_for_action`.

### 3.2 Outcome delivery — listener list

The replaceable single sink is removed. Default NNG delivery becomes unconditional and internal; consumers
register alongside it.

```python
def add_outcome_listener(self, fn: Callable[[dict], None]) -> None: ...
def remove_outcome_listener(self, fn: Callable[[dict], None]) -> None: ...

def _emit_outcome(self, outcome: dict) -> None:      # stays private
    self._deliver_default(outcome)                    # NNG status — always
    for fn in listeners_snapshot:                     # snapshot under the lock,
        try:                                          # call outside it
            fn(outcome)
        except Exception as exc:
            Logger.error(f"Action outcome listener raised: {exc}")
```

Rules, all of which must be stated in the docstring:

- The default NNG `action_cue_outcome` delivery **always** runs and cannot be suppressed or replaced.
- Listeners run in registration order, after the default.
- A listener exception is logged and swallowed. **A listener can never change an outcome.**
- The listener list is snapshotted under `self._lock` and invoked outside it — the same discipline
  `_matching_hooks` already uses at `:171-172`.

`NodeEngine` becomes a pure listener; `_action_result_sink` loses its first line and its lazy import:

```python
CUE_HANDLER.action_handler.add_outcome_listener(self._action_result_sink)
```

This eliminates P7 rather than renaming it, keeps
`controller-integration-contracts.md`'s prohibition on touching `_default_result_sink` intact, and lets N
controller modules observe outcomes without contending for a slot.

**Behaviour delta.** A custom sink can no longer suppress the default. In-tree production callers relying on
that: **zero**. Test callers (`test_action_cue.py:613`, `:621`, `:628`) are removed in Step 5.

### 3.3 Hook system — retained, reserved, and made multi-owner

The hook system has no production registrations today (only the `CueHandler` forwarder and tests). It is
retained as a **planned future feature** whose concrete, current requirement is the hardware controller
integration specified in `controller-integration-contracts.md` — this satisfies Constitution IV, and that
justification must be restated whenever the hook system is reviewed.

Scope is narrowed by the §1 distinction:

- **Hooks** are for extensions that legitimately *participate* in an outcome: `cue_layer` show-script logic and
  `wrap_dispatch` interception. A hook that raises intentionally fails the action.
- **Controller feedback** (LED state, motor-fader position) uses **outcome listeners**, because the expected
  failure mode is an unplugged device, and an unplugged device must never turn an applied `play` into a
  `failed` outcome on the Controller UI.
- **`node_layer` is retained** as a registration layer for controller-owned participating hooks and for the
  existing cue-layer-then-node-layer resolution order.

**Multi-owner registration** (fixes P11). Hook identity gains an owner component:

```python
HookKey = tuple[HookPhase, RegistrationLayer, frozenset[str], str]   # + owner

def register_action_hook(self, phase, fn, *, source="cue_layer",
                         action_types=None, owner="default") -> None: ...
def unregister_action_hook(self, phase, *, source,
                           action_types=None, owner="default") -> None: ...
def unregister_all_hooks(self, owner: str) -> None: ...
```

- `before_dispatch` / `after_dispatch` **fan out to every owner**, cue_layer first then node_layer, and within a
  layer in registration order (dict insertion order).
- `wrap_dispatch` accepts **one hook per `(source, action_types)`**. A second registration for the same key
  raises `ValueError` instead of silently evicting — nesting wraps from independent owners has no defensible
  ordering.
- `owner` defaults to `"default"`, preserving today's last-registration-wins for existing callers.
- Controller modules pass `owner=self.module_id` and call `unregister_all_hooks(self.module_id)` in `detach()`.

### 3.4 The action set is deliberately closed

`SUPPORTED_CUE_ACTIONS` is the engine's **stable vocabulary**, shared by the XSD schema (`script.xsd`
`ActionType`), the editor/frontend, and the cross-node protocol. It is **closed to runtime extension**: no
public `register_action()` exists, and none will. New actions ship as new entries in `_ACTION_HANDLERS` together
with their schema, tests and documentation.

**Single source of truth** (fixes P10): `SUPPORTED_CUE_ACTIONS` is *derived* from `_ACTION_HANDLERS`, and the
now-provably-unreachable "No handler registered" branch in `execute_action` is deleted. The set stays closed; it
simply stops being maintained twice.

**Reconciliation with Open/Closed.** OCP is satisfied at two seams, and the closed action set is a deliberate,
documented exception to it:

| Seam | Open for extension? | Mechanism |
|---|---|---|
| Fadeable target types | **Yes** | `_FADE_BUILDERS` registry (§7 B2) |
| Outcome observation | **Yes** | outcome listeners (§3.2) |
| Dispatch interception | **Yes** | hook system (§3.3) |
| Action-type vocabulary | **No — by decision** | new entry in `_ACTION_HANDLERS` + schema + tests |

Rationale for the exception: a fixed vocabulary is the only thing that keeps the XSD, the UI labels, and the
cross-node dispatch protocol in agreement. An action type that exists on one node and not another is a show-stop
failure, and runtime registration makes that state reachable.

### 3.5 `dispatch_action` — discrete hardware triggers

Hardware buttons represent a named action on a named target. They must not construct a synthetic `ActionCue`
with `_action_target_object` pre-set.

```python
@dataclass
class ActionParams:
    """Optional payload for actions needing more than (action_type, target).

    Field names mirror FadeCue so `_handle_fade_action` consumes it unchanged.
    Mutable: the fade handler writes _start_mtc / _end_mtc back.
    """
    id: str | None = None
    curve_type: str | None = None
    target_value: float | None = None
    duration: "CTimecode | None" = None
    _start_mtc: "CTimecode | None" = None
    _end_mtc: "CTimecode | None" = None


def dispatch_action(
    self,
    action_type: str,
    target: Cue,
    mtc: MtcListener,
    frozen_mtc_ms: float | None = None,
    params: ActionParams | None = None,
) -> dict: ...
```

Implementation: extract the pipeline body of `execute_action` into a private
`_dispatch(action_type, target, mtc, frozen_mtc_ms, *, cue=None, params=None)`. `execute_action` resolves and
validates `cue.action_type` / `cue._action_target_object` and delegates; `dispatch_action` validates
`action_type in SUPPORTED_CUE_ACTIONS` and `target is not None` and delegates. Both run the identical hook
pipeline and produce the identical outcome dict.

- `params` supplies the FadeCue-shaped attribute surface that `_handle_fade_action` requires, so **`fade_action`
  is dispatchable from hardware** with no change to the handler. Passing `action_type="fade_action"` with
  `params=None` is rejected with a `failed` outcome naming the missing payload.
- `ActionHookContext` gains a trailing `params: ActionParams | None = None` field and its `cue` field widens to
  `ActionCue | None`. Both changes are additive and source-compatible for existing integrators; the field
  *names* remain stable, which is what §6 protects.

---

## 4. Import Graph (target state)

```
CueHandler       imports  ActionHandler       (top-level — already true, CueHandler.py:19)
ActionHandler    DOES NOT import CueHandler   (CueHandlerProtocol — already true, 4d53856)
ActionHandler    DOES NOT import PLAYER_HANDLER  (GradientClient routed through ch — Step 4)
```

`CueHandlerProtocol` — corrected against the code, replacing the incorrect surface previously published here and
in the contracts document:

```python
class CueHandlerProtocol(Protocol):
    """Subset of CueHandler needed by action dispatch (avoids circular import)."""

    communications_thread: "NodeCommunications | None"

    def arm(self, cue: Cue, init: bool = False) -> bool: ...
    def disarm(self, cue: Cue) -> bool: ...
    def go_from(self, start_cue: Cue, mtc: MtcListener,
                seed_ms: float | None = None) -> Thread | None: ...
    def get_gradient_client(self) -> "GradientClient | None": ...
```

**`go_from`, not `go`.** Handlers use `go_from` deliberately: a plain `go()` bails when the target is local to
another node, dropping this node's own cues on a cross-node loop-back. See the in-line rationale at
`ActionHandler.py:429-434` and `:534-537`. Any document or protocol publishing `go` for this purpose is wrong.

`arm` and `disarm` return `bool`, not `None`. `communications_thread` is an **attribute**, currently reached via
`getattr` at `:219`; declaring it on the protocol removes the `getattr` while keeping the `None` check.

---

## 5. Migration Path

Each step lists its TDD gate. Per Constitution I, Steps 3 onward require a failing test **confirmed failing**
before implementation. Steps 1–2 are pure moves with no behaviour change; the existing suite is their safety
net, and that exemption must not be extended further.

### Step 1 — Extract `_make_action_result` free function
Move `@staticmethod _action_result` out of the class. Update all 28 call sites in `ActionHandler.py`.
**Gate:** existing suite green, unchanged. Fixes P1, P2.

### Step 2 — Rename `_ALL_ACTIONS` → `_MATCH_ALL`
Update `register_action_hook` (`:141`) and `unregister_action_hook` (`:153`); document the wildcard semantics at
`_filter_matches` (`:66-69`) and `_wrap_for_action` (`:192`).
**Gate:** existing suite green, unchanged. Fixes P8.

### Step 3 — Single source of truth for the action set
Derive `SUPPORTED_CUE_ACTIONS` from `_ACTION_HANDLERS`; delete the unreachable "No handler registered" branch.
**Gate (RED):** a test asserting `SUPPORTED_CUE_ACTIONS == frozenset(_ACTION_HANDLERS)`, plus a test that every
name in the XSD `ActionType` enum is either supported or on the documented not-yet-implemented list. Fixes P10.

### Step 4 — Protocol rename, correction, and `GradientClient` through `ch`
- Rename `CueOrchestrator` → `CueHandlerProtocol`; correct its surface per §4 (`go_from`, `bool` returns,
  `communications_thread` attribute, `get_gradient_client`).
- Add `CueHandler.get_gradient_client()` forwarding accessor.
- Replace `PLAYER_HANDLER.get_gradient_client()` at `:605` with `ch.get_gradient_client()`; remove the
  `PLAYER_HANDLER` import at `:24`.
- Replace the `getattr(ch, "communications_thread", None)` at `:219` with a direct access plus `None` check.

**Gate (RED):** a test asserting `ActionHandler.py` exposes no `PLAYER_HANDLER` attribute, and a fade test whose
`GradientClient` is supplied by the stub cue handler rather than by patching `PLAYER_HANDLER`. Fixes P9.

### Step 5 — Constructor DI, singleton removal, lazy-import cleanup, test fixtures
**These cannot be split.** Removing `bind_cue_handler` breaks the `test_action_cue.py` fixture in the same
change, so the fixture rewrite lands with it.

- `ActionHandler.__init__(self, cue_handler)`; remove `bind_cue_handler()`.
- `CueHandler.__init__` sets `self.action_handler = ActionHandler(self)`; remove `CueHandler.py:19` and the
  module-level binding at `CueHandler.py:954`.
- Delete `ACTION_HANDLER = ActionHandler()` (`:782`).
- Update `CueHandler.execute_action` (`:835`), `CueHandler.register_action_hook` (`:849`),
  `run_cue.reveal_actionCue` (`:559`), `NodeEngine._setup_nng_command_callback` (`:134`) and
  `NodeEngine._action_result_sink` (`:902`) to use `self.action_handler` / `CUE_HANDLER.action_handler` —
  **deleting all five vestigial lazy imports**, and correcting the stale precedent comment at `run_cue.py:66`.
- Rewrite test fixtures to construct a fresh `ActionHandler(stub_ch)` per test; drop `bind_cue_handler` and
  `clear_action_extensions` usage.

**Gate (RED):** a top-level import smoke test (`import cuemsengine.cues.ActionHandler` first, then
`cuemsengine.cues.CueHandler`, and the reverse) proving no cycle in either order; a test that two
`ActionHandler` instances hold independent hook registries. Fixes P3 (scoped), P4 (partly), P5 residue, P12.

### Step 6 — Outcome listeners
- Add `add_outcome_listener` / `remove_outcome_listener`; make `_deliver_default` unconditional.
- Move `NodeEngine` onto `add_outcome_listener(self._action_result_sink)` and delete the
  `_default_result_sink(outcome)` call at `NodeEngine.py:905`.
- Delete `set_result_sink()` and `set_emit_enabled()`.

**Gate (RED):** a test that the default NNG delivery still fires when a listener is registered; a test that a
raising listener neither propagates nor alters the outcome; a test that two listeners both receive every
outcome in registration order. Fixes P6, P7.

### Step 7 — Multi-owner hook registry
Add the `owner` key component, `unregister_all_hooks(owner)`, fan-out for before/after, and the `ValueError` on
duplicate `wrap_dispatch` per `(source, action_types)`.
**Gate (RED):** a test that two owners registering the same `(phase, source, filter)` both fire; a test that one
owner's `unregister_all_hooks` leaves the other's hooks intact; a test that a duplicate `wrap_dispatch`
registration raises. Fixes P11.

### Step 8 — `dispatch_action` and `ActionParams`
Extract `_dispatch(...)`; add `dispatch_action(...)` and the `ActionParams` dataclass; widen
`ActionHookContext.cue` and add `ActionHookContext.params`.
**Gate (RED):** parity tests asserting `dispatch_action("play", target, mtc)` produces an outcome identical to
the equivalent `execute_action`, that the full hook pipeline fires for both, that a `fade_action` dispatch with
`params` reaches `_handle_fade_action` unchanged, and that `fade_action` without `params` returns `failed` with
a payload-missing reason.

### Step 9 — Delete `finalize_node_layer_bindings()`
The stub has no consumer and node-layer wiring is now explicit (`add_outcome_listener`, and later
`ControllerModule.attach`). Deleting it removes the last hollow initialization phase.
**Gate:** existing suite green. Completes P4.

### Step 10 — (separate feature branch) `_FADE_BUILDERS` registry
§7 B2. Own spec, own branch, own tasks — not part of this refactor. Blocks the next fadeable cue type.

---

## 6. Invariants — What Must NOT Change

- The `_ACTION_HANDLERS` dict-based registry pattern. Adding an action means adding an entry; it is not a
  runtime extension point (§3.4).
- The `HookPhase` / `RegistrationLayer` vocabulary, including `node_layer`. `RegistrationLayer` values are part
  of the controller-integration contract.
- `ActionHookContext` **field names** — stable API for integrators. Additive fields and type widening are
  permitted (§3.5); renames and removals are not.
- `_ready_action_target` stays a module-level helper.
- `motion_id` terminology (renamed from `fade_id` in `29c28c1`) is finalized; do not revert.
- The `go_from`-not-`go` choice in `_handle_play` / `_handle_fade_in`, and the `_local` guard that precedes it.
- The `{status, action_type, target_id, reason}` outcome key set, pinned by
  `test_action_cue.py::test_action_outcome_dict_keys_stable`.
- `_build_fade_payload` and its current shape are frozen **until the next fadeable cue type is introduced**, at
  which point §7 B2 supersedes this entry.

---

## 7. Forward-Looking Architectural Boundaries

Assumed by the decision but not enforced by it. They must be explicitly respected when adding new modules;
without them, future integrators will place code in the wrong layer.

### B1 — Scripted vs Live Control

`ActionHandler` is the **discrete-event** pipeline: `execute_action` for show-script events at a timecode,
`dispatch_action` for hardware triggers. It is **not** a general command bus.

Real-time hardware controllers (MIDI CC faders, OSC control surfaces, USB HID encoders) generate **continuous
parameter streams** that must route through a separate live-control layer — the `route_audio_message` /
`route_dmx_message` pattern on `CueHandler`, dispatched from `NodeEngine._handle_player_control_message`
(`NodeEngine.py:158`). New controller modules add a `route_*` method to `CueHandler` and a branch in
`_handle_player_control_message`; they never feed continuous events into `execute_action` or `dispatch_action`.

Routing a 127-step CC fader through the action pipeline would invoke the full hook pipeline on every tick — a
performance and coupling failure.

`controller-integration-contracts.md` Contract 4 proposes a single `CueHandler.route_control_event(namespace,
parameter, value)` front door that dispatches to the per-namespace methods. **It does not exist yet** and has no
step in this plan; it is a prerequisite for the first controller module, tracked in that document.

### B2 — `_build_fade_payload` Must Become a Registry Before the Next Media Type

`_build_fade_payload` selects OSC endpoint logic via `isinstance(target_cue, AudioCue) / isinstance(target_cue,
VideoCue)` (`:740`, `:745`). Every new fadeable target type (EqCue, EffectCue, MidiDeviceCue, LightingCue)
extends that if-elif chain — an Open/Closed violation at the one seam §3.4 declares open.

Before any new fadeable cue type is introduced, replace it with a per-type builder registry:

```python
_FADE_BUILDERS: dict[type, "FadePayloadBuilderProtocol"] = {}

def register_fade_builder(cue_type: type, builder: "FadePayloadBuilderProtocol") -> None:
    _FADE_BUILDERS[cue_type] = builder

def _build_fade_payload(target_cue, fade_cue, start_mtc_ms, motion_id) -> list[dict]:
    builder = _FADE_BUILDERS.get(type(target_cue))
    if builder is None:
        raise ValueError(f"No fade builder for {type(target_cue).__name__}")
    return builder.build(target_cue, fade_cue, start_mtc_ms, motion_id)
```

`AudioCue` and `VideoCue` builders register at module load; new types register their own; the isinstance chain
disappears. Full contract for `FadePayloadBuilderProtocol` is in
`specs/planning/controller-integration-contracts.md` Contract 5.

**Acceptance criteria for the B2 work — these are defects to fix, not behaviour to preserve:**

1. **P13, partial-dispatch record loss.** `end_value` must be recorded for **every entry whose OSC send
   succeeded**, including when a later entry fails. Record per-entry immediately after its own successful send;
   delete the "state must remain unchanged on failure" comment at `:627-630` — that invariant is unachievable
   because the sends are not atomic, and pursuing it is what causes the stale `start_value` on the next fade.
   **Gate (RED):** a multi-layer VideoCue fade where layer 2's send raises must leave layer 1's `end_value`
   recorded on `target._osc`.
2. **Payload-dict ownership.** `_handle_fade_action` currently does `entry.pop("motion_id")` in the dispatch
   loop and the record loop then re-reads the same dicts (`:632`, `:665`). Contract 5 mandates `motion_id` as a
   returned key, so pop-vs-copy becomes a contract detail. The builder returns dicts it does not retain; the
   caller must not mutate them — read `entry["motion_id"]` without popping.
3. **Error surface.** `builder.build` raises `ValueError` for invalid target state; the caller converts it to a
   `failed` outcome, matching today's `except (ValueError, TypeError)` at `:622`.

---

## 8. Risk Assessment and Rollback

| Risk | Likelihood | Mitigation |
|------|-----------|-----------|
| Import-order regression during Step 5 | Medium | Top-level import smoke test in both orders (Step 5 gate) |
| Steps 5+6 both touch `NodeEngine` outcome wiring | Medium | Land in order; Step 6's gate covers the default-delivery path explicitly |
| Test-suite global state between tests | High (current) → Low (after Step 5) | Fresh instance per fixture eliminates bleed |
| `run_cue.py` singledispatch referencing wrong handler | Low | Covered by `test_action_cue.py` |
| Fade tests patch `PLAYER_HANDLER.get_gradient_client` | Certain at Step 4 | Patch target moves to `stub_ch.get_gradient_client`; same PR |
| Multi-owner hooks change resolution order | Low | Fan-out preserves cue_layer-then-node_layer; registration order within a layer is newly specified and tested |
| `dispatch_action` diverges from `execute_action` | Medium | Both routed through one `_dispatch`; parity tests are the Step 8 gate |

**Rollback.** Steps 1–4 and 7–9 are independently revertable single commits. Step 5 is the only wide-blast-radius
change (6 source files + 5 test files) and must be a single revertable commit — do not split it across a merge.
Step 6 depends on Step 5 and reverts cleanly on top of it.

**Deployment.** Per the project CLAUDE.md, a controller host runs both `cuems-controller-engine` and
`cuems-node-engine` from the same source tree. Any step landed on a live box requires **restarting both
services**, even though `ActionHandler` only executes in the node role — a stale node-engine process keeps
running the old dispatch path.

---

## 9. Test Impact Inventory

| File | Coupling | Breaks at |
|---|---|---|
| `tests/test_action_cue.py:57-73` | fixture uses `bind_cue_handler`, `clear_action_extensions`, `set_emit_enabled` | Step 5 (rewrite lands with it), Step 6 |
| `tests/test_action_cue.py:613,621,628` | `set_result_sink` | Step 6 |
| `tests/test_node_engine.py:244` | patches `cuemsengine.cues.ActionHandler.ACTION_HANDLER` | Step 5 |
| `tests/test_reveal_mechanism.py:72` | patches `...ActionHandler.ACTION_HANDLER` | Step 5 |
| `tests/test_fade_action_handler.py:719` | patches `...ActionHandler.ACTION_HANDLER` | Step 5 |
| `tests/test_fade_action_handler.py` (`_build_fade_payload`, `_ACTION_HANDLERS` imports) | module-level private imports | Step 4 (patch target), Step 10 (registry) |
| `tests/test_chain_anchoring.py:148` | module import of `ActionHandler` | Step 5 |

**Pre-existing defect to fix during the Step 5 fixture rewrite:** several `test_action_cue.py` cases patch
`handler.go`, but `_handle_play` / `_handle_fade_in` call `go_from`. Those patches are inert and the real stub
method runs.

---

## 10. Open Items

- `CueHandler.route_control_event` (B1 / contracts Contract 4) has no owner and no step.
- `CueHandler.get_cue_by_id` (contracts Contract 3) does not exist; required before the first controller module.
- ~~`ControllerModuleProtocol.attach()` does not receive an `MtcListener`~~ — resolved: `attach()` now takes
  `mtc` (contracts Contract 1).
- ~~Controller-module lifecycle ambiguity~~ — resolved: `attach` once per process, `detach` only at shutdown,
  never on project load (contracts, *Lifecycle*).
- `NodeEngine` needs a controller-module registry and the `attach`/`detach` call sites. Not scheduled — it is
  the first task of the controller-integration feature, not of this refactor.
