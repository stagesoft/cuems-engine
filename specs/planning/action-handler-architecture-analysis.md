# ActionHandler Architecture — Decision and Migration Plan

**Date:** 2026-05-15 — revised 2026-05-19 (post NNG→OSC migration, commit `29c28c1`) — revised 2026-08-10
(decision locked) — **validated 2026-08-10 against commit `e210b26`**
**Scope:** `src/cuemsengine/cues/ActionHandler.py` and its call sites
**Status:** **Accepted architectural decision, code-validated.** Composition-owned instance with constructor DI
is the sole approach; alternatives were evaluated and discarded. The migration path below is authoritative and
every claim in it has been checked against the working tree — see §11.
**Companion:** `specs/planning/controller-integration-contracts.md` — the two documents MUST stay in sync.

> **Line-number convention.** Every `file.py:N` reference in this document is pinned to commit **`e210b26`**
> (branch `rc_1`). They were re-derived from the working tree on 2026-08-10 and are correct as of that commit.
> Re-verify before relying on them if the tree has moved; prefer the symbol name over the number.

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
| Hardware-triggered actions | `dispatch_action(action_type, target, mtc, frozen_mtc_ms=None, params=None)` — scheduled in this migration |
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
`_ACTION_HANDLERS: dict[str, Callable]` (`ActionHandler.py:775-787`) — static mapping from action-type string to
implementation.
`_handle_play` … `_handle_fade_action` (`:411-681`) — concrete per-action implementations.
`_ready_action_target` (`:376`), `_build_fade_payload` (`:684`) — shared helpers with no class affiliation.
`_handle_fade_action` additionally reaches a second module-level singleton (`PLAYER_HANDLER`) directly.

### Layer C — The Proto-Singleton
`ACTION_HANDLER = ActionHandler()` at `ActionHandler.py:789` — a single instance created unconditionally at
import time. Three sites configure it afterwards:

| Site | What it does |
|------|--------------|
| `CueHandler.py:20` | top-level `from .ActionHandler import ACTION_HANDLER as _ACTION_HANDLER_SINGLETON` |
| `CueHandler.py:966` | `_ACTION_HANDLER_SINGLETON.bind_cue_handler(CUE_HANDLER)` |
| `NodeEngine.py:136-137` | `finalize_node_layer_bindings()` then `set_result_sink(self._action_result_sink)` |

The `NodeEngine` calls live in **`_setup_nng_command_callback`** (`NodeEngine.py:110`), not `__init__`, and
`finalize` runs *before* `set_result_sink`.

### 1.1 `CueHandler` is itself a `__new__`-based singleton — and has no `__init__`

Load-bearing for §3.1 and previously undocumented. `CueHandler` declares `_instance: "CueHandler | None" = None`
(`CueHandler.py:34`) and overrides `__new__` (`:44-53`), initialising instance attributes inside the
`if cls._instance is None:` block. **There is no `CueHandler.__init__` anywhere in the class.**

Two consequences the migration must respect:

1. Ownership of the `ActionHandler` must be established **inside the `if cls._instance is None:` block of
   `__new__`**, next to `_armed_cues` / `_lock`.
2. **Adding an `__init__` is a trap.** `__new__` returns the *existing* instance on every subsequent
   `CueHandler()` call, but Python still calls `__init__` on the returned object each time. An
   `__init__` that does `self.action_handler = ActionHandler(self)` would silently rebuild the handler on any
   stray `CueHandler()` call, **dropping every registered outcome listener and hook**. Do not add one.

### 1.2 `communications_thread` is a declared-but-unset attribute

`CueHandler.communications_thread: NodeCommunications` (`CueHandler.py:42`) is a bare class annotation — it
creates no attribute. The attribute is bound only by `set_nng_comms()` (`CueHandler.py:64`). Until that runs,
`CUE_HANDLER.communications_thread` raises `AttributeError`, which is why the codebase guards it with `hasattr`
/ `getattr` at `NodeEngine.py:121`, `NodeEngine.py:264`, `ControllerEngine.py:380`, `:828`, `:1117`, `:1199`,
and why `_default_result_sink` uses `getattr(ch, "communications_thread", None)` (`ActionHandler.py:218`).

**This getattr is correct and must be preserved.** See §5 Step 4, which previously scheduled its removal.

### Two outcome mechanisms, never previously distinguished

This distinction is load-bearing and was undocumented. It governs every decision in §3.2.

| | `after_dispatch` hook | result sink / listener |
|---|---|---|
| Runs | inside `execute_action`, **before** the outcome is final | after the outcome is final |
| On exception | **rewrites the outcome to `failed`** and breaks the loop (`ActionHandler.py:337-347`) | swallowed and logged (`ActionHandler.py:207-210`) |
| Can change the result | **yes** | no |

`NodeEngine._action_result_sink` deliberately relies on sink semantics: its in-line comment at
`NodeEngine.py:957-960` states that an exception in the `cue_enabled` side effects must never starve the
Controller UI update. Converting it to a hook would let an unrelated side-effect failure turn an applied
`enable` into a `failed` outcome. **Hooks participate; listeners observe.**

---

## 2. Identified Problems

### P1 — Cross-coupling via class name (not interface)
`_action_result` is reached through the class name from module level. **28 call sites in
`ActionHandler.py`: 22 written `ActionHandler._action_result(...)` from module-level functions, 6 written
`self._action_result(...)` inside `execute_action`.** The module-level implementations are coupled to the class
**by name**, not to a protocol or injected factory. Handlers cannot be reused or unit-tested without importing
the full class.

### P2 — `@staticmethod` that doesn't belong on the class
`_action_result` (`ActionHandler.py:356-368`) is a pure data factory with no access to `self` or `cls`. As a
`@staticmethod` consumed primarily by module-level functions it is the worst of both worlds: not a method (no
`self` use), not free (requires the class import).

### P3 — Singleton-but-not-enforced
`ACTION_HANDLER` is created unconditionally at module load, but nothing prevents `ActionHandler()` being
instantiated again. The singleton is implicit, undocumented and unenforceable.

Under the decision, P3 is **scoped, not eliminated**: `CUE_HANDLER` remains a module-level singleton *and* a
`__new__` singleton (§1.1), so `CUE_HANDLER.action_handler` is a shorter path to the same process-global. What
changes is that there is exactly one owner and one construction site. True application-level DI would require
threading the instance from a composition root (`NodeEngine`) and making `CUE_HANDLER` lazily constructed — see
§3.1, *Why the constructor cannot take the sink*.

### P4 — Multi-phase initialization across three files
The constructor leaves the object incomplete. `bind_cue_handler` must run before any dispatch method is useful;
`set_result_sink` must run after comms are ready. This temporal coupling is invisible to the type system and
silently produces broken objects if initialization order changes.

Note that one of the three phases is hollow: `finalize_node_layer_bindings()` (`ActionHandler.py:157-162`) is a
`return`-only stub with a single caller (`NodeEngine.py:136`).

### P5 — Circular import — **RESOLVED (commit `4d53856`), re-verified 2026-08-10**
Historically `ActionHandler` referenced `CueHandler` and vice-versa, broken by lazy imports.

**Commit `4d53856` ("Resolve ActionHandler → CueHandler circular import using a protocol") fixed this.**
`ActionHandler.py` now declares the `CueOrchestrator` Protocol (`ActionHandler.py:50-62`) and imports no
`CueHandler`. Its transitive imports (`NodeCommunications` → `AsyncCommsThread`, `NodesHub`) do not reach
`CueHandler` either. **There is no cycle today** — confirmed empirically by importing each module first in a
clean interpreter; both orders succeed (§11).

Two residues remain:

1. **Five vestigial lazy imports** that no longer break any cycle and are now pure misdirection —
   `CueHandler.py:847`, `CueHandler.py:861`, `run_cue.py:559`, `NodeEngine.py:134`, `NodeEngine.py:942`.
   `run_cue.py:65-67` carries a comment citing the `reveal_actionCue` ActionHandler lazy import as precedent,
   propagating the stale belief.
2. **Naming divergence.** The protocol is called `CueOrchestrator` in code and `CueHandlerProtocol` in both
   planning documents. **`CueHandlerProtocol` is the chosen name; the code is renamed in Step 4.**

### P6 — Test-isolation API bleeding into production
`clear_action_extensions()` (`ActionHandler.py:119`) and `set_emit_enabled()` (`:114`) exist purely to reset the
singleton between tests (`test_action_cue.py:68-73`, `:612`, `:622`, `:627`, `:638`). Test concerns exposed in
the production API. **All three of `set_result_sink`, `set_emit_enabled` and `clear_action_extensions` are
deleted** — see Step 6.

### P7 — `NodeEngine` accesses a protected method, and the sink shape is inverted
`NodeEngine._action_result_sink` (`NodeEngine.py:937`) calls `ACTION_HANDLER._default_result_sink(outcome)` at
`NodeEngine.py:945`, bypassing the public interface.

The protected access is a symptom. The cause is that installing a sink **replaces** the transport, so every
sink implementer is expected to call the transport back by hand. Forgetting that one line silently stops all
`action_cue_outcome` NNG traffic to the Controller — a failure with no error on the UI path. The single slot
also means the first controller module that wants outcomes must steal it from `NodeEngine`. §3.2 replaces the
shape rather than renaming the method.

### P8 — `_ALL_ACTIONS` is a misleading sentinel
`_ALL_ACTIONS: frozenset[str] = frozenset()` (`ActionHandler.py:47`) means "no filter / match all", not "the set
of all actions". Consumers: `register_action_hook` (`:140`), `unregister_action_hook` (`:152`); the wildcard
semantics are implemented by truthiness in `_filter_matches` (`:65-68`) and inline in `_wrap_for_action`
(`:191`). Non-obvious at every one of those sites.

### P9 — `_handle_fade_action` depends on a second hidden global (introduced by `29c28c1`)
`_handle_fade_action` calls `PLAYER_HANDLER.get_gradient_client()` (`ActionHandler.py:604`) with
`PLAYER_HANDLER` imported at module top level (`:24`). The handler receives `ch: CueOrchestrator` as its
first argument and then bypasses it to reach `GradientClient` through a parallel global, making the `ch`
injection pointless for this dependency. `CueHandler` already imports `PLAYER_HANDLER` itself
(`CueHandler.py:18`), so a forwarding accessor costs no new import there.

### P10 — Two unsynchronised sources of truth for the action set
`SUPPORTED_CUE_ACTIONS` (`ActionHandler.py:30-42`) and the keys of `_ACTION_HANDLERS` (`:775-787`) are
hand-maintained duplicates of the same list. `execute_action` gates on the frozenset (`:244`) and again on the
dict (`:284-285`), and the second branch — `"No handler registered for {action_type}"` — is **currently
unreachable**. Any future divergence is a silent behaviour change.

### P11 — Hook registration silently evicts prior registrations
`self._hooks[key] = fn` with `key = (phase, source, filter_key)` (`ActionHandler.py:140-143`). Two consumers
registering the same `(phase, source, filter)` — which the controller-integration Pattern A does — means the
second **deletes** the first with no error. `unregister_action_hook` (`:145-155`) has the mirror defect: it pops
by the same key, so one module's `detach()` removes another module's hook. Multiple simultaneous hardware
controllers are a confirmed requirement, so this is a correctness defect, not a theoretical one.

The current behaviour is pinned by `test_action_cue.py:566` (`test_duplicate_hook_registration_last_wins`),
which Step 7 must rewrite rather than preserve.

### P12 — `ch` may be `None` at dispatch, failing silently
`execute_action` passes `self._cue_handler` (Optional) straight into handlers (`:292-295`), and
`_ready_action_target` calls `ch.arm` unguarded (`:388`). Before binding this raises `AttributeError`, which the
blanket `except` at `:327` converts into a generic `"failed"` outcome with no indication of the real cause — a
silent-failure class the constitution forbids. Constructor DI removes the state by construction.

### P13 — Fade dispatch loses `end_value` records on partial failure
`_handle_fade_action` (`:630-664`) sends layer-by-layer, then records `end_value` for every entry in a second
loop. On a failure at layer *N* it returns early (`:652-657`), so the layers `0..N-1` that **did** receive the
fade never get recorded. Their next fade computes `start_value` from a stale pre-fade level — the exact defect
class that `2608ea8` and `afebe48` were written to eliminate.

The comment at `:626-629` states the intent as "dispatch ALL entries before mutating anything… state must
remain unchanged". That invariant is unachievable: the OSC sends are not atomic, so layers `0..N-1` *are*
already faded on the player. The engine-side record must mirror what was actually sent. Folded into §7 B2 as an
acceptance criterion.

### P14 — `_handle_stop` blocks the dispatch thread for 100 ms
`_handle_stop` calls `time.sleep(0.1)` (`ActionHandler.py:470`) so `loop_cue` can observe `_stop_requested`
before `disarm`. Harmless for a show-script action fired from a cue thread; **not** harmless once
`dispatch_action` (§3.5) lets a hardware button reach the same handler from a controller module's listener
thread. This is not scheduled for change in this migration — the sleep is load-bearing for the disarm race —
but it is a documented latency the controller contracts must publish. See
`controller-integration-contracts.md` Contract 2.

### P15 — Three of the nine supported actions are stubs that report `applied`

Not previously recorded in either planning document, and load-bearing for controller integration:

| Action | Actual behaviour | Source |
|---|---|---|
| `fade_in` | identical to `play`; no fade envelope | `ActionHandler.py:523-524` |
| `fade_out` | sets `_stop_requested` and bumps `_go_generation`, **but never calls `disarm()`** | `ActionHandler.py:549-557` |
| `go_to` | arms the target only; no seek / position navigation | `ActionHandler.py:567-568` |

All three return `"applied"`. `fade_out` additionally carries a **code-documented live defect**: its own comment
states it "has the same zombie-process bug as the old stop handler: bumps `_go_generation` but does not call
`disarm()`, so player processes are not cleaned up."

This is a §2 problem rather than a §7 boundary because `dispatch_action` (§3.5) makes all three reachable from a
hardware button, where today they are only reachable from a show script. A controller module maps a button to
`fade_out`, gets `applied`, lights its LED green — and leaks a player process each press. Contract 2 and
Integration Pattern B currently present the nine supported actions as uniform; they are not.

**Not scheduled here.** Implementing the fade envelope and the seek is its own feature. What this migration owes
is *disclosure*: the stub set must be published in `controller-integration-contracts.md` Contract 2 so no
controller module is written against a promise the engine does not keep. Whether `fade_out`'s missing `disarm()`
is fixed independently (it is a two-line change mirroring `_handle_stop`) is a **question for §13**.

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
```

```python
# CueHandler.py — owns the instance. NOTE: CueHandler has NO __init__ (§1.1);
# ownership is established in the one-shot branch of __new__, and adding an
# __init__ would rebuild the handler on every CueHandler() call, dropping all
# registered listeners and hooks.
class CueHandler:
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._armed_cues = []
            cls._instance._armed_cues_set = set()
            cls._instance._video_players = {}
            cls._instance._front_video_player = None
            cls._instance._lock = Lock()
            cls._instance.action_handler = ActionHandler(cls._instance)
        return cls._instance

    def get_gradient_client(self):
        """Forwarding accessor — PLAYER_HANDLER is already imported here."""
        return PLAYER_HANDLER.get_gradient_client()
```

**Why the constructor cannot take the sink.** `CUE_HANDLER = CueHandler()` is constructed at **module import
time** (`CueHandler.py:964`), so under this design `ActionHandler` is constructed at import time too — while
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

All 28 call sites (22 module-level, 6 in-class) call it directly. No reference to the `ActionHandler` class name
remains outside the class body.

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
register alongside it. **`_default_result_sink` keeps its current name** — the contracts document already
publishes that name as a prohibited access, and renaming it buys nothing.

```python
def add_outcome_listener(self, fn: Callable[[dict], None]) -> None: ...
def remove_outcome_listener(self, fn: Callable[[dict], None]) -> None: ...

def _emit_outcome(self, outcome: dict) -> None:      # stays private
    self._default_result_sink(outcome)                # NNG status — always
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
  `_matching_hooks` already uses at `:170-171`.

`NodeEngine` becomes a pure listener; `_action_result_sink` loses its first line and its lazy import:

```python
CUE_HANDLER.action_handler.add_outcome_listener(self._action_result_sink)
```

This eliminates P7 rather than renaming it, keeps
`controller-integration-contracts.md`'s prohibition on touching `_default_result_sink` intact, and lets N
controller modules observe outcomes without contending for a slot.

**Behaviour delta.** A custom sink can no longer suppress the default. In-tree production callers relying on
that: **zero** (the only `set_result_sink` caller is `NodeEngine.py:137`, and it calls the default back by hand).
Test callers (`test_action_cue.py:613`, `:621`, `:628`) are removed in Step 6.

### 3.3 Hook system — retained, reserved, and made multi-owner

The hook system has no production registrations today — grep confirms the only callers are the `CueHandler`
forwarder (`CueHandler.py:851-865`) and `test_action_cue.py`. It is retained as a **planned future feature**
whose concrete, current requirement is the hardware controller integration specified in
`controller-integration-contracts.md` — this satisfies Constitution IV, and that justification must be restated
whenever the hook system is reviewed.

Scope is narrowed by the §1 distinction:

- **Hooks** are for extensions that legitimately *participate* in an outcome: `cue_layer` show-script logic and
  `wrap_dispatch` interception. A hook that raises intentionally fails the action.
- **Controller feedback** (LED state, motor-fader position) uses **outcome listeners**, because the expected
  failure mode is an unplugged device, and an unplugged device must never turn an applied `play` into a
  `failed` outcome on the Controller UI.
- **`node_layer` is retained** as a registration layer for controller-owned participating hooks and for the
  existing cue-layer-then-node-layer resolution order (`_matching_hooks`, `:166-181`).

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
- `owner` defaults to `"default"`, preserving today's last-registration-wins **for a single owner**.
  `test_duplicate_hook_registration_last_wins` (`test_action_cue.py:566`) stays valid only for same-owner
  registrations and must be re-scoped, not deleted.
- Controller modules pass `owner=self.module_id` and call `unregister_all_hooks(self.module_id)` in `detach()`.
- **`CueHandler.register_action_hook` (`CueHandler.py:851`) hardcodes `source="cue_layer"` and exposes no
  `owner`.** It stays that way: it is the show-script forwarder, not a controller entry point. Controller
  modules register through `ActionHandlerProtocol` directly.

### 3.4 The action set is deliberately closed

`SUPPORTED_CUE_ACTIONS` is the engine's **stable vocabulary**, shared by the XSD schema (`script.xsd`
`ActionType`), the editor/frontend, and the cross-node protocol. It is **closed to runtime extension**: no
public `register_action()` exists, and none will. New actions ship as new entries in `_ACTION_HANDLERS` together
with their schema, tests and documentation.

**Single source of truth** (fixes P10): `SUPPORTED_CUE_ACTIONS` is *derived* from `_ACTION_HANDLERS`, and the
now-provably-unreachable "No handler registered" branch in `execute_action` (`:284-290`) is deleted. The set
stays closed; it simply stops being maintained twice.

**Verified vocabulary (2026-08-10).** `script.xsd` `ActionType` declares 14 values; `SUPPORTED_CUE_ACTIONS`
implements 9; the 5 remaining are exactly the not-yet-implemented list in the comment at `ActionHandler.py:27-29`:

| XSD `ActionType` (14) | Engine status |
|---|---|
| `play`, `pause`, `stop`, `enable`, `disable`, `fade_in`, `fade_out`, `fade_action`, `go_to` | implemented (9) |
| `load`, `unload`, `wait`, `pause_project`, `resume_project` | not yet implemented (5) |

The schema is **not in this repo** — it ships inside the `cuemsutils` package at
`cuemsutils/xml/schemas/script.xsd`. Step 3's XSD gate must resolve it via `importlib.resources`, not a
repo-relative path.

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
- `ActionHookContext.cue_handler` is currently typed `CueOrchestrator | None` (`:83`). After Step 5 the value is
  never `None`; narrowing the annotation to `CueHandlerProtocol` is permitted (readers are unaffected) but is
  not required.
- **Latency note (P14).** `dispatch_action("stop", …)` inherits `_handle_stop`'s 100 ms sleep. Controller
  modules must call it off their hardware-input thread or accept the stall; this is published in Contract 2.

---

## 4. Import Graph (target state)

```
CueHandler       imports  ActionHandler       (top-level — already true, CueHandler.py:20)
ActionHandler    DOES NOT import CueHandler   (CueHandlerProtocol — already true, 4d53856)
ActionHandler    DOES NOT import PLAYER_HANDLER  (GradientClient routed through ch — Step 4)
```

`CueHandlerProtocol` — corrected against the code, replacing the incorrect surface previously published here.
This is **one protocol shared by two consumers**: `ActionHandler`'s internal dispatch needs and the
controller-facing surface of `controller-integration-contracts.md` Contract 3. The union is therefore the
definition, and both documents publish the same list:

```python
class CueHandlerProtocol(Protocol):
    """Subset of CueHandler needed by action dispatch and controller modules."""

    # Declared, but NOT bound until CueHandler.set_nng_comms() runs (§1.2).
    # Read it with getattr(ch, "communications_thread", None) — never directly.
    communications_thread: "NodeCommunications"

    def arm(self, cue: Cue, init: bool = False) -> bool: ...
    def disarm(self, cue: Cue) -> bool: ...
    def go_from(self, start_cue: Cue, mtc: MtcListener,
                seed_ms: float | None = None) -> Thread | None: ...
    def get_armed_cue_by_id(self, cue_id: str) -> "Cue | None": ...
    def get_cue_by_id(self, cue_id: str) -> "Cue | None": ...       # NOT YET IMPLEMENTED
    def get_gradient_client(self) -> "GradientClient | None": ...   # added in Step 4
```

Existence check against `CueHandler` at `e210b26`: `arm` (`:284`), `disarm` (`:386`), `go_from` (`:517`),
`get_armed_cue_by_id` (`:951`), `communications_thread` (`:42`/`:64`) all exist. `get_cue_by_id` and
`get_gradient_client` **do not exist** — see §10.

**`go_from`, not `go`.** Handlers use `go_from` deliberately: a plain `go()` bails when the target is local to
another node, dropping this node's own cues on a cross-node loop-back. See the in-line rationale at
`ActionHandler.py:429-432` and `:534-536`, and `CueHandler.go_from`'s docstring (`:517-533`). Any document or
protocol publishing `go` for this purpose is wrong. Note that `go_from` **delegates to `self.go`** on its final
line (`CueHandler.py:555`) — relevant to §9.

`arm` and `disarm` return `bool`, not `None`.

**Protocol home module.** These protocols (`CueHandlerProtocol`, plus `ActionHandlerProtocol`,
`ControllerModuleProtocol`, `LiveControlRouterProtocol`, `FadePayloadBuilderProtocol` from the contracts
document) have no agreed home. **Undecided — see §12 Decision A**, which recommends a single
`src/cuemsengine/contracts.py` created at Step 4, with `TYPE_CHECKING`-only imports as a hard requirement and
the hook vocabulary (`HookPhase`, `RegistrationLayer`, `ActionHookContext`, `ActionParams`) migrating there at
Step 8. Tracked in §10.

---

## 5. Migration Path

Each step lists its TDD gate. Per Constitution I, Steps 3 onward require a failing test **confirmed failing**
before implementation. Steps 1–2 are pure moves with no behaviour change; the existing suite is their safety
net, and that exemption must not be extended further.

Baseline: `tests/test_action_cue.py` is **66 passed** at `e210b26` (verified 2026-08-10).

### Step 1 — Extract `_make_action_result` free function
Move `@staticmethod _action_result` (`:356-368`) out of the class. Update all 28 call sites in
`ActionHandler.py` (22 `ActionHandler._action_result`, 6 `self._action_result`).
**Gate:** existing suite green, unchanged. Fixes P1, P2.

### Step 2 — Rename `_ALL_ACTIONS` → `_MATCH_ALL`
Update `register_action_hook` (`:140`) and `unregister_action_hook` (`:152`); document the wildcard semantics at
`_filter_matches` (`:65-68`) and `_wrap_for_action` (`:191`).
**Gate:** existing suite green, unchanged. Fixes P8.

### Step 3 — Single source of truth for the action set
Derive `SUPPORTED_CUE_ACTIONS` from `_ACTION_HANDLERS`; delete the unreachable "No handler registered" branch
(`:284-290`).
**Gate (RED):** a test asserting `SUPPORTED_CUE_ACTIONS == frozenset(_ACTION_HANDLERS)`, plus a test that every
name in the XSD `ActionType` enum is either supported or on the documented not-yet-implemented list — reading
the schema from the installed `cuemsutils` package via `importlib.resources`, since it is not in this repo
(§3.4). Fixes P10.

### Step 4 — Protocol rename, correction, and `GradientClient` through `ch`
- Rename `CueOrchestrator` → `CueHandlerProtocol`; correct its surface per §4 (`go_from`, `bool` returns,
  `communications_thread`, `get_armed_cue_by_id`, `get_gradient_client`).
- Add `CueHandler.get_gradient_client()` forwarding accessor.
- Replace `PLAYER_HANDLER.get_gradient_client()` at `:604` with `ch.get_gradient_client()`; remove the
  `PLAYER_HANDLER` import at `:24`.
- **Leave `getattr(ch, "communications_thread", None)` at `:218` exactly as it is.** A previous revision of this
  plan scheduled its replacement with direct attribute access; that is wrong. The attribute is unbound until
  `set_nng_comms()` runs (§1.2) and direct access would raise `AttributeError` on every outcome emitted before
  comms start. Declaring it on the Protocol is a typing statement, not a runtime guarantee.

**Gate (RED):** a test asserting `ActionHandler.py` exposes no `PLAYER_HANDLER` attribute; a fade test whose
`GradientClient` is supplied by the stub cue handler rather than by patching `PLAYER_HANDLER`; a test that
`_default_result_sink` returns quietly when `ch` has no `communications_thread` attribute at all (not merely
`None`). Fixes P9.

### Step 5 — Constructor DI, singleton removal, lazy-import cleanup, test fixtures
**These cannot be split.** Removing `bind_cue_handler` breaks the `test_action_cue.py` fixture in the same
change, so the fixture rewrite lands with it.

- `ActionHandler.__init__(self, cue_handler)`; remove `bind_cue_handler()` (`:103-105`).
- `CueHandler.__new__` sets `cls._instance.action_handler = ActionHandler(cls._instance)` inside its
  `if cls._instance is None:` block (§1.1 — **do not add an `__init__`**); remove the aliased import at
  `CueHandler.py:20` and the module-level binding at `CueHandler.py:966`.
- Delete `ACTION_HANDLER = ActionHandler()` (`:789`).
- Update `CueHandler.execute_action` (lazy import `:847`), `CueHandler.register_action_hook` (lazy import
  `:861`), `run_cue.reveal_actionCue` (`:559`), `NodeEngine._setup_nng_command_callback` (`:134`) and
  `NodeEngine._action_result_sink` (`:942`) to use `self.action_handler` / `CUE_HANDLER.action_handler` —
  **deleting all five vestigial lazy imports**, and correcting the stale precedent comment at `run_cue.py:65-67`.
- Rewrite the `handler` fixture (`test_action_cue.py:50-73`). It builds its stub with
  `object.__new__(CueHandler)`, which **bypasses `__new__` entirely** — so it must now set
  `h.action_handler = ActionHandler(h)` explicitly. Drop `bind_cue_handler`, `clear_action_extensions` and
  `set_emit_enabled` usage.
- Re-point the three `patch("cuemsengine.cues.ActionHandler.ACTION_HANDLER")` sites (§9) at
  `CUE_HANDLER.action_handler`.

**Blast radius: 4 source files** (`ActionHandler.py`, `CueHandler.py`, `NodeEngine.py`, `run_cue.py`) **and 4
test files** (`test_action_cue.py`, `test_node_engine.py`, `test_reveal_mechanism.py`,
`test_fade_action_handler.py`). `test_chain_anchoring.py` is **not** affected — it exercises `_handle_play` and
`_ready_action_target` directly and never touches `ACTION_HANDLER`.

**Gate (RED):** a top-level import smoke test (`import cuemsengine.cues.ActionHandler` first, then
`cuemsengine.cues.CueHandler`, and the reverse) proving no cycle in either order — this passes today and must
keep passing; a test that two `ActionHandler` instances hold independent hook registries; a test that calling
`CueHandler()` a second time returns the same instance **with the same `action_handler` object** (guards the
`__init__` trap of §1.1). Fixes P3 (scoped), P4 (partly), P5 residue, P12.

### Step 6 — Outcome listeners
- Add `add_outcome_listener` / `remove_outcome_listener`; make `_default_result_sink` unconditional inside
  `_emit_outcome`.
- Move `NodeEngine` onto `add_outcome_listener(self._action_result_sink)` and delete the
  `_default_result_sink(outcome)` call at `NodeEngine.py:945`.
- Delete `set_result_sink()` (`:107`), `set_emit_enabled()` (`:114`) **and `clear_action_extensions()`
  (`:119`)** — all three are the test-isolation API of P6, and a fresh `ActionHandler` per fixture replaces
  all of them.
- Delete `test_action_cue.py::test_injectable_sink_records_outcome` (`:608`) and re-point
  `test_default_path_calls_send_operation_when_sink_unset` (`:624`) at the now-unconditional default.
- Rewrite `test_node_engine.py::TestActionResultSinkEnableDisable._sink` (`:242-245`): it patches
  `ACTION_HANDLER` purely to intercept the `_default_result_sink` call, which no longer happens.

**Gate (RED):** a test that the default NNG delivery still fires when a listener is registered; a test that a
raising listener neither propagates nor alters the outcome; a test that two listeners both receive every
outcome in registration order. Fixes P6, P7.

### Step 7 — Multi-owner hook registry
Add the `owner` key component, `unregister_all_hooks(owner)`, fan-out for before/after, and the `ValueError` on
duplicate `wrap_dispatch` per `(source, action_types)`. Re-scope
`test_action_cue.py::test_duplicate_hook_registration_last_wins` (`:566`) to same-owner registrations.
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
The stub (`:157-162`) has no consumer beyond `NodeEngine.py:136` and node-layer wiring is now explicit
(`add_outcome_listener`, and later `ControllerModule.attach`). Deleting it removes the last hollow
initialization phase.
**Gate:** existing suite green. Completes P4.

### Step 10 — (separate feature branch) `_FADE_BUILDERS` registry
§7 B2. Own spec, own branch, own tasks — not part of this refactor. Blocks the next fadeable cue type.

**Not in scope, deliberately:** P14 (`_handle_stop`'s 100 ms sleep) is documented, not changed. Removing it
requires a different disarm/`loop_cue` handshake and belongs to its own spec.

---

## 6. Invariants — What Must NOT Change

- The `_ACTION_HANDLERS` dict-based registry pattern. Adding an action means adding an entry; it is not a
  runtime extension point (§3.4).
- The `HookPhase` / `RegistrationLayer` vocabulary (`ActionHandler.py:44-45`), including `node_layer`.
  `RegistrationLayer` values are part of the controller-integration contract.
- `ActionHookContext` **field names** — stable API for integrators. Additive fields and type widening/narrowing
  are permitted (§3.5); renames and removals are not.
- `_ready_action_target` stays a module-level helper (patched as such by `test_chain_anchoring.py:157`).
- `motion_id` terminology (renamed from `fade_id` in `29c28c1`) is finalized; do not revert.
- The `go_from`-not-`go` choice in `_handle_play` / `_handle_fade_in`, and the `_local` guard that precedes it.
- The `{status, action_type, target_id, reason}` outcome key set, pinned by
  `test_action_cue.py:736::test_action_outcome_dict_keys_stable`.
- The `getattr` guard on `communications_thread` (§1.2).
- `_build_fade_payload` and its current shape — including the `duration <= 0` `ValueError` guard at `:719-725`
  — are frozen **until the next fadeable cue type is introduced**, at which point §7 B2 supersedes this entry.

---

## 7. Forward-Looking Architectural Boundaries

Assumed by the decision but not enforced by it. They must be explicitly respected when adding new modules;
without them, future integrators will place code in the wrong layer.

### B1 — Scripted vs Live Control

`ActionHandler` is the **discrete-event** pipeline: `execute_action` for show-script events at a timecode,
`dispatch_action` for hardware triggers. It is **not** a general command bus.

Real-time hardware controllers (MIDI CC faders, OSC control surfaces, USB HID encoders) generate **continuous
parameter streams** that must route through a separate live-control layer — the `route_audio_message`
(`CueHandler.py:871`) / `route_dmx_message` (`CueHandler.py:923`) pattern, dispatched from
`NodeEngine._handle_player_control_message` (`NodeEngine.py:158`). New controller modules add a `route_*` method
to `CueHandler` and a branch in `_handle_player_control_message`; they never feed continuous events into
`execute_action` or `dispatch_action`.

Routing a 127-step CC fader through the action pipeline would invoke the full hook pipeline on every tick — a
performance and coupling failure. P14's 100 ms sleep in `_handle_stop` makes the point concrete.

`controller-integration-contracts.md` Contract 4 proposes a single `CueHandler.route_control_event(namespace,
parameter, value)` front door that dispatches to the per-namespace methods. **It does not exist yet** and has no
step in this plan; it is a prerequisite for the first controller module, tracked in that document.

### B2 — `_build_fade_payload` Must Become a Registry Before the Next Media Type

`_build_fade_payload` selects OSC endpoint logic via `isinstance(target_cue, AudioCue)` (`:747`) /
`isinstance(target_cue, VideoCue)` (`:752`). Every new fadeable target type (EqCue, EffectCue, MidiDeviceCue,
LightingCue) extends that if-elif chain — an Open/Closed violation at the one seam §3.4 declares open.

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

**Note on the lookup:** the current code uses `isinstance`, the registry sketch uses `type(target_cue)` exact
match. That is a deliberate narrowing (subclasses of `AudioCue` would no longer resolve). **Undecided — see
§12 Decision B**, which recommends `functools.singledispatch` (the mechanism the five other cue registries
already use) plus an inexact-resolution warning, and which also recommends splitting this section into B2a
(fix P13 now) and B2b (the registry, when the next fadeable type arrives).

**Acceptance criteria for the B2 work — these are defects to fix, not behaviour to preserve:**

1. **P13, partial-dispatch record loss.** `end_value` must be recorded for **every entry whose OSC send
   succeeded**, including when a later entry fails. Record per-entry immediately after its own successful send;
   delete the "state must remain unchanged on failure" comment at `:626-629` — that invariant is unachievable
   because the sends are not atomic, and pursuing it is what causes the stale `start_value` on the next fade.
   **Gate (RED):** a multi-layer VideoCue fade where layer 2's send raises must leave layer 1's `end_value`
   recorded on `target._osc`.
2. **Payload-dict ownership.** `_handle_fade_action` currently does `entry.pop("motion_id")` in the dispatch
   loop (`:631`) and the record loop then re-reads the same dicts (`:664`). Contract 5 mandates `motion_id` as a
   returned key, so pop-vs-copy becomes a contract detail. The builder returns dicts it does not retain; the
   caller must not mutate them — read `entry["motion_id"]` without popping.
3. **Error surface.** `builder.build` raises `ValueError` for invalid target state; the caller converts it to a
   `failed` outcome, matching today's `except (ValueError, TypeError)` at `:621`.
4. **Preserve the duration guard.** The `duration <= 0` `ValueError` at `:719-725` must move into the shared
   pre-builder path, not be duplicated per builder — it is a FadeCue invariant, not a target-type concern.

---

## 8. Risk Assessment and Rollback

| Risk | Likelihood | Mitigation |
|------|-----------|-----------|
| Import-order regression during Step 5 | Medium | Top-level import smoke test in both orders (Step 5 gate); passes today, so any failure is caused by the step |
| `CueHandler.__init__` added by reflex, rebuilding the handler and dropping listeners | **Medium** | Called out in §1.1 and §3.1; Step 5 gate asserts identity of `action_handler` across two `CueHandler()` calls |
| `communications_thread` direct access reintroduced, `AttributeError` before comms start | Medium | Step 4 gate tests the attribute-absent path; §6 lists the getattr as an invariant |
| Steps 5+6 both touch `NodeEngine` outcome wiring | Medium | Land in order; Step 6's gate covers the default-delivery path explicitly |
| Test-suite global state between tests | High (current) → Low (after Step 5) | Fresh instance per fixture eliminates bleed |
| `run_cue.py` singledispatch referencing wrong handler | Low | Covered by `test_reveal_mechanism.py:69` and `test_fade_action_handler.py:803` |
| Fade tests patch `PLAYER_HANDLER.get_gradient_client` (14 sites in `test_fade_action_handler.py`) | Certain at Step 4 | Those tests already call `_ACTION_HANDLERS["fade_action"]` with a `Mock()` ch; the patch becomes `ch.get_gradient_client.return_value = mock_gc`. Same PR |
| Multi-owner hooks change resolution order | Low | Fan-out preserves cue_layer-then-node_layer; registration order within a layer is newly specified and tested |
| `dispatch_action` diverges from `execute_action` | Medium | Both routed through one `_dispatch`; parity tests are the Step 8 gate |

**Rollback.** Steps 1–4 and 7–9 are independently revertable single commits. Step 5 is the only wide-blast-radius
change (4 source files + 4 test files) and must be a single revertable commit — do not split it across a merge.
Step 6 depends on Step 5 and reverts cleanly on top of it.

**Deployment.** Per the project CLAUDE.md, a controller host runs both `cuems-controller-engine` and
`cuems-node-engine` from the same source tree. Any step landed on a live box requires **restarting both
services**, even though `ActionHandler` only executes in the node role — a stale node-engine process keeps
running the old dispatch path.

---

## 9. Test Impact Inventory

Verified against the tree at `e210b26`.

| File | Coupling | Breaks at |
|---|---|---|
| `tests/test_action_cue.py:50-73` | `handler` fixture uses `bind_cue_handler`, `clear_action_extensions`, `set_emit_enabled`; builds its stub with `object.__new__(CueHandler)`, bypassing `__new__` | Step 5 (rewrite lands with it), Step 6 |
| `tests/test_action_cue.py:566` | `test_duplicate_hook_registration_last_wins` pins P11's defect as behaviour | Step 7 (re-scope to same-owner) |
| `tests/test_action_cue.py:608-622` | `test_injectable_sink_records_outcome` — `set_result_sink` + `set_emit_enabled` | Step 6 (delete) |
| `tests/test_action_cue.py:624-639` | `test_default_path_calls_send_operation_when_sink_unset` — `set_result_sink(None)`, `set_emit_enabled` | Step 6 (re-point at unconditional default) |
| `tests/test_node_engine.py:242-245` | `_sink` helper patches `cuemsengine.cues.ActionHandler.ACTION_HANDLER` to intercept `_default_result_sink` | Step 5 (patch target gone), Step 6 (call gone) |
| `tests/test_reveal_mechanism.py:72` | patches `...ActionHandler.ACTION_HANDLER` for `reveal_actionCue` | Step 5 → `CUE_HANDLER.action_handler` |
| `tests/test_fade_action_handler.py:803` | patches `...ActionHandler.ACTION_HANDLER` for run/reveal dispatch | Step 5 → `CUE_HANDLER.action_handler` |
| `tests/test_fade_action_handler.py` — 14 sites (`:499`, `:569`, `:623`, `:639`, `:656`, `:675`, `:692`, `:708`, `:727`, `:751`, …) | `patch.object(PLAYER_HANDLER, "get_gradient_client", …)` | Step 4 (patch target moves to the mock `ch`) |
| `tests/test_fade_action_handler.py` — `_build_fade_payload` (11 sites) and `_ACTION_HANDLERS` (14 sites) module-level private imports | direct private-symbol imports | Step 10 (registry) |
| `tests/test_chain_anchoring.py:148-160` | imports the module and calls `AH._handle_play` / patches `AH._ready_action_target` | **Unaffected by Steps 1–9** — it never touches `ACTION_HANDLER`. Only §6's "`_ready_action_target` stays module-level" invariant protects it |

**Correction to a claim in the previous revision.** It stated that `test_action_cue.py` cases patching
`handler.go` were inert because `_handle_play` calls `go_from`. **That is false.** `go_from` ends with
`return self.go(cue, mtc, seed_ms + sigma_ms)` (`CueHandler.py:555`), so a `patch.object(handler, "go")` *is*
reached — via `go_from` — and the assertions are meaningful. `test_play_without_frozen_mtc_passes_none`
(`:132`) deliberately patches `go_from` instead, and its in-line comment explains exactly this. No fix is
needed; nothing here is a defect. The suite is green (66 passed).

---

## 10. Open Items

Each of these blocks the controller-integration feature, not this refactor.

- **`CueHandler.route_control_event`** (B1 / contracts Contract 4) — does not exist; no owner, no step.
- **`CueHandler.get_cue_by_id`** (contracts Contract 3) — does not exist. Only `get_armed_cue_by_id`
  (`CueHandler.py:951`) and `find_armed_cue` (`:108`) exist today.
- **Protocol home module.** `ActionHandlerProtocol`, `ControllerModuleProtocol`, `LiveControlRouterProtocol`,
  `FadePayloadBuilderProtocol` and the shared `CueHandlerProtocol` have no agreed location. **Decision brief:
  §12 A** — recommends `src/cuemsengine/contracts.py` at Step 4. Needs a call **before Step 4 starts**, not
  before the first controller module, because Step 4 already moves and renames `CueHandlerProtocol` and
  deciding late costs a second move.
- **Fade builder lookup key** (§7 B2 / Contract 5). **Decision brief: §12 B** — recommends `singledispatch`
  plus an inexact-resolution warning, and splitting B2 so that P13 is fixed now rather than gated behind a
  speculative registry. Needs a call before B2a is scheduled.
- **mypy in CI** — sub-question of §12 A. CI runs flake8 only, and `isinstance`-based protocol conformance was
  measured to be both order-dependent and blind to signature drift (§12 A.1). Without mypy, the protocols are
  convention enforced by review.
- **`NodeEngine` controller-module registry** and the `attach`/`detach` call sites. The contracts document's
  lifecycle diagram places `attach` inside `set_players()`; §11 shows it belongs **after**
  `_setup_nng_command_callback()` in `NodeEngine.start()` so the engine's own outcome listener registers first.
  Not scheduled — first task of the controller-integration feature.
- ~~`ControllerModuleProtocol.attach()` does not receive an `MtcListener`~~ — resolved: `attach()` takes `mtc`.
- ~~Controller-module lifecycle ambiguity~~ — resolved: `attach` once per process, `detach` only at shutdown,
  never on project load.

---

## 11. Validation Record (2026-08-10, commit `e210b26`)

How each class of claim in this document was checked, so a spec can be started from it without re-deriving.

| Claim class | Method | Result |
|---|---|---|
| All `file.py:N` references | Re-derived from the working tree with `grep -n` / `sed -n` | **Corrected.** `ActionHandler.py` refs were uniformly off by +1 (an import-block blank line removed in `e210b26`) and `_build_fade_payload` refs by −7; `CueHandler.py` refs by −12; `NodeEngine.py` sink refs by −40. All now match |
| No `ActionHandler` ↔ `CueHandler` import cycle (P5) | `python -c "import …ActionHandler; import …CueHandler"` and the reverse, in clean interpreters | Both orders import cleanly. Claim **confirmed** |
| `_action_result` call-site count | `grep -c` on both spellings | 22 class-qualified + 6 `self`-qualified = **28**. Prior "28 call sites in module-level functions" was imprecise; now split out |
| XSD `ActionType` vs `SUPPORTED_CUE_ACTIONS` | Read `cuemsutils/xml/schemas/script.xsd:235-252` | 14 enum values; 9 supported; 5 unimplemented, matching the source comment exactly. Step 3's gate is achievable. **New finding:** the schema lives in the `cuemsutils` package, not this repo |
| `CueHandler` construction shape | Read `CueHandler.py:34-53` | **New finding.** `__new__`-based singleton, **no `__init__`**. §3.1's original `def __init__` sketch was unimplementable and would have introduced a listener-dropping bug. Rewritten |
| `communications_thread` availability | Read `CueHandler.py:42`, `:64`; grepped `hasattr`/`getattr` guards across `src/` | **New finding.** Declared-only annotation, bound solely by `set_nng_comms()`. Step 4's instruction to drop the `getattr` was a latent `AttributeError`. Reversed, and added to §6 invariants |
| `go_from` → `go` delegation | Read `CueHandler.py:517-555` | **New finding.** `go_from` returns `self.go(...)`. §9's "inert patch / pre-existing defect" paragraph was wrong and is retracted |
| Protocol surface (§4 vs Contract 3) | Compared both documents against `CueHandler`'s actual methods | The two documents published different surfaces while claiming one definition. Reconciled to the union; existence of each member checked individually |
| `ActionHandler` reachability from `ControllerEngine` | `grep` for `ActionHandler`/`CueHandler` in `ControllerEngine.py` | No hits. Process-scope claim **confirmed** |
| Hook system has no production registrations | `grep` for `register_action_hook` across `src/` and `tests/` | Only `CueHandler.py:851-865` (forwarder) and `test_action_cue.py`. **Confirmed** |
| Test-suite baseline | `poetry run python -m pytest tests/test_action_cue.py -q` | **66 passed** |
| Test coupling inventory | `grep -n` for every patch target and private import | Two rows corrected: `test_fade_action_handler.py` ACTION_HANDLER patch is at `:803` (not `:719`); `test_chain_anchoring.py` does **not** break at Step 5 |
| `NodeEngine` startup order | Read `NodeEngine.start()` (`:97-108`) | `set_nng_comms` → `set_oscquery_comms` → `set_players` → `_setup_nng_command_callback`. **No project is loaded at any point in this sequence** — contradicts the contracts document's `attach()` docstring, corrected there |
| `_handle_stop` latency | Read `ActionHandler.py:455-475` | 100 ms `time.sleep` in the dispatch path. New problem **P14**, documented (not scheduled) and published in Contract 2 |

---

## 12. Decision Briefs for the Two Open Design Choices

Both items were left open by the 2026-08-10 validation because either answer is defensible and the choice
changes downstream work. Each brief below states the evidence gathered from the tree, the options, the
consequences, and a recommendation. **Neither is decided yet** — they need a call before the relevant step
starts.

---

### Decision A — Where the integration protocols live

**Question.** `CueHandlerProtocol`, `ActionHandlerProtocol`, `ControllerModuleProtocol`,
`LiveControlRouterProtocol` and (conditionally) `FadePayloadBuilderProtocol` need a home. Today only
`CueOrchestrator` exists, inside `ActionHandler.py`.

#### A.1 Evidence

**What the protocols must name.** `Cue` / `ActionCue` (cuemsutils), `MtcListener`, `NodeCommunications`,
`GradientClient`, `Thread`, plus the hook vocabulary `HookPhase`, `RegistrationLayer`, `ActionHookContext`,
`ActionParams`.

**Import cost of each, measured at `e210b26`:**

| Symbol | Module | Cost of a runtime import |
|---|---|---|
| `Cue`, `ActionCue` | `cuemsutils.cues` | already a hard dependency; leaf |
| `MtcListener` | `cuemsengine/tools/MtcListener.py` | `tools/__init__.py` is **empty**; module imports only `os`, `threading`, `typing`, `mido`, `cuemsutils`. Cheap, cycle-free |
| `NodeCommunications` | `cuemsengine/comms/NodeCommunications.py` | `comms/__init__.py` is **empty**; pulls `AsyncCommsThread` + `NodesHub`. Already imported top-level by `ActionHandler.py:22`. Cheap, cycle-free |
| `GradientClient` | `cuemsengine/players/GradientClient.py` | **`players/__init__.py` is not empty** — importing any submodule executes it, pulling `AudioPlayer`, `DmxPlayer`, `VideoPlayer`. It does **not** pull `PlayerHandler`, so this does not resurrect P9 — but it is a heavy subtree for a pure-interface module |

**The cycle that a naive `contracts.py` would create.** `ActionHandlerProtocol` names `ActionHookContext`,
`HookPhase`, `RegistrationLayer` and `ActionParams` — all defined in `ActionHandler.py`. If `ActionHandler.py`
imports `contracts` for `CueHandlerProtocol` *and* `contracts` imports `ActionHandler` for the hook vocabulary,
that is a new cycle — the exact class of problem `4d53856` was written to remove.

**Why `if TYPE_CHECKING:` fully resolves it.** `ActionHandler.py` already carries
`from __future__ import annotations` (`:10`), so every annotation is a string at runtime. Verified on this
interpreter (Python 3.11.9): `@runtime_checkable` + `isinstance()` checks **only member presence**, never
annotation types, so a protocol whose referenced types exist solely under `TYPE_CHECKING` is fully functional at
runtime. A `contracts.py` written this way has **zero runtime imports of engine modules**.

Residual caveat: `typing.get_type_hints()` on such a protocol raises `NameError`. Nothing in the repo calls it
(dataclasses store annotations as strings; there is no pydantic dependency), but a future API-doc generator
would trip on it.

**Measured limits of a conformance test — this is the finding that most changes the calculus.** Verified on
Python 3.11.9 with a protocol carrying one data member and one method:

| Candidate class | `isinstance(obj, Proto)` |
|---|---|
| attribute assigned + method present | `True` |
| attribute missing entirely | `False` |
| **attribute annotated but never assigned** | **`False`** |
| method present with a **wrong signature** | **`True`** |

The third row is `CueHandler.communications_thread` exactly (§1.2): annotation-only until `set_nng_comms()`
runs. So `isinstance(CUE_HANDLER, CueHandlerProtocol)` is **`False` at import time and `True` after comms
start** — an order-dependent assertion that fails in any plain unit test. The fourth row means signature drift
— the failure mode a conformance test is actually for — is **not detected at all**.

CI runs **flake8 only** (`.github/workflows/ci.yml:46`); there is no mypy. So "one module makes drift testable"
is a much weaker argument for co-location than it appears, and must not be the deciding factor. A useful test is
an explicit member-presence list, or adopting mypy — a separate decision with its own cost.

**`cuems-common` is not an option.** Checked: it ships `debian/`, `docs/`, `etc/`, `scripts/`, a `Makefile` —
**no Python packaging at all**. The only cross-repo Python home would be `cuemsutils`.

#### A.2 Options

| | Option | Consequence |
|---|---|---|
| **A1** | Single `src/cuemsengine/contracts.py` | One import path for integrators. Requires the `TYPE_CHECKING` discipline to be mandatory, not stylistic |
| **A2** | `src/cuemsengine/contracts/` package, one module per contract | Same, with room to grow. ~5 protocols totalling a few hundred lines does not justify a package today (YAGNI, Constitution) |
| **A3** | Keep split: `CueHandlerProtocol` stays in `ActionHandler.py`; controller protocols go to a future `controllers/` package | `ControllerModuleProtocol` and `LiveControlRouterProtocol` are **not** cue-layer concepts, and `LiveControlRouterProtocol` is implemented by `CueHandler` while describing a router — no package owns the set coherently. Also leaves `CueHandlerProtocol` in a module that is not about protocols |
| **A4** | Push to `cuemsutils` | Inverts the dependency: these protocols describe `CueHandler` / `ActionHandler` seams that `cuemsutils` knows nothing about. Only justified if a second repo consumes them, which none does |

**A non-cost, so nobody tries to fix it:** `cuemsengine/__init__.py` imports `ControllerEngine` and `NodeEngine`,
so `import cuemsengine.contracts` boots the whole engine. That is true of every in-package location, and
controller modules run *inside* the node-engine process — they import the engine regardless. Not a reason to
prefer A4.

#### A.3 Recommendation — A1, with two conditions

1. **`TYPE_CHECKING`-only imports are mandatory in `contracts.py`.** Not a style preference: it is the single
   mechanism that keeps the module free of the `ActionHandler` cycle and of the `players/__init__.py` subtree.
   Enforce it with a test asserting `contracts.py`'s runtime imports are confined to `typing`, `dataclasses`,
   `__future__` and `cuemsutils`.
2. **Move the hook vocabulary into `contracts.py` too** — `HookPhase`, `RegistrationLayer`, `ActionHookContext`
   and (when it lands) `ActionParams`. §6 already declares `ActionHookContext`'s field names and the
   `HookPhase`/`RegistrationLayer` values to be stable integrator API, so by this document's own definition they
   *are* contract surface, and co-locating them makes the dependency strictly one-way:
   `ActionHandler → contracts`, `CueHandler → contracts`, controller modules → `contracts`. Nothing imports
   back.

**Sequencing.** Create `contracts.py` at **Step 4**, holding `CueHandlerProtocol` only — that step already
renames and corrects it, so it costs one extra file move and avoids a second move later. Migrate the hook
vocabulary at **Step 8**, where `ActionHookContext` is edited anyway (`cue` widens, `params` is added) and
`ActionParams` is introduced.

**The one-time cost, and why now is when to pay it.** Moving `ActionHookContext` changes its import path, which
is an API break for hook integrators. There are **zero** production hook registrations today — verified by grep,
the only callers are the `CueHandler` forwarder and `test_action_cue.py`. The window closes the moment the first
controller module ships.

**Open sub-question for whoever decides:** whether to add mypy to CI. If yes, the protocols become genuinely
enforceable and A1 gets materially stronger. If no, accept that conformance is convention plus review, and do
not write an `isinstance`-based conformance test — it would be order-dependent and would not catch drift.

---

### Decision B — How `_FADE_BUILDERS` resolves a target type

**Question.** §7 B2's registry sketch uses `_FADE_BUILDERS.get(type(target_cue))` — an exact-type match. The
code it replaces uses `isinstance`. That is a silent narrowing, and it needs a deliberate call.

#### B.1 Evidence

**The cue hierarchy is entirely single-inheritance** (read from `cuemsutils.cues` at `e210b26`):

```
AudioCue  -> MediaCue -> Cue -> CuemsDict -> dict
VideoCue  -> MediaCue -> Cue -> CuemsDict -> dict
FadeCue   -> ActionCue -> Cue -> CuemsDict -> dict
ActionCue, CueList, DmxCue -> Cue -> CuemsDict -> dict
```

No diamond, so MRO resolution is unambiguous by construction and `singledispatch` cannot raise its
ambiguous-dispatch `RuntimeError` on these types.

**MRO-based type registries are already the house pattern.** `functools.singledispatch` backs **five** generic
functions in the cue layer — `arm_cue` (`arm_cue.py:14`), `run_cue` (`run_cue.py:16`), `reveal_cue`
(`run_cue.py:511`), a third generic at `run_cue.py:591`, and `loop_cue` (`loop_cue.py:28`) — carrying roughly
twenty registrations between them. An exact-`type()` registry would be the **only** type-keyed cue registry in
the package that does not resolve by MRO.

**The repo already depends on MRO inheritance being load-bearing.** `FadeCue` has no `run_cue` or `reveal_cue`
registration of its own; it resolves to the `ActionCue` branch purely through the MRO — and
`test_fade_action_handler.py:795` pins exactly that, with a docstring that says so. A maintainer adding a
fadeable cue type would reasonably expect the same behaviour from a fade registry.

**Behaviour verified empirically** with `singledispatch` and builders registered for `AudioCue` / `VideoCue`:

| Input | Result |
|---|---|
| `AudioCue()` | audio builder |
| `VideoCue()` | video builder |
| `EqCue(AudioCue)` — hypothetical future type | **audio builder, via MRO** |
| `ActionCue()` — not fadeable | base implementation → clean `ValueError` |
| `build.registry` | introspectable: `['object', 'AudioCue', 'VideoCue']` |

**Today the two options are behaviourally identical.** There is no subclass of `AudioCue` or `VideoCue` in
`cuemsutils`. The decision only bites on the first one — which is precisely the scenario §7 B2 exists for.

#### B.2 The real trade-off — where the failure surfaces

| | Exact `type()` | MRO (`isinstance` / `singledispatch`) |
|---|---|---|
| New fadeable subclass, registered | works | works |
| New fadeable subclass, **forgotten** | `ValueError: No fade builder for EqCue` — **loud, at first fade** | inherits the ancestor's builder — **silent**, emits e.g. `/volmaster` for an EQ cue |
| Subclass that legitimately wants inherited behaviour | must re-register explicitly | works with no ceremony |
| Consistency with `arm_cue` / `run_cue` / `reveal_cue` / `loop_cue` | **diverges** | matches |

Exact-type converts a *possible silent-wrong* into a *certain loud-fail*. That is usually the right trade — but
the loud failure lands at **reveal time**, i.e. mid-show on a cue that loaded and armed cleanly, which is the
worst moment for it. And it buys that at the cost of breaking the one dispatch convention the cue layer already
has.

#### B.3 Recommendation — `singledispatch` (MRO) plus an inexact-resolution warning

Take the house mechanism, and recover the loudness that exact-matching would have given, without the show-stop:

```python
@singledispatch
def _fade_builder(target_cue, fade_cue, start_mtc_ms, motion_id) -> list[dict]:
    raise ValueError(f"No fade builder for {type(target_cue).__name__}")

@_fade_builder.register
def _(target_cue: AudioCue, fade_cue, start_mtc_ms, motion_id) -> list[dict]: ...

@_fade_builder.register
def _(target_cue: VideoCue, fade_cue, start_mtc_ms, motion_id) -> list[dict]: ...


def _build_fade_payload(target_cue, fade_cue, start_mtc_ms, motion_id) -> list[dict]:
    # FadeCue.duration > 0 stays here — it is a FadeCue invariant, not a
    # target-type concern (§7 B2 criterion 4).
    ...
    if type(target_cue) not in _fade_builder.registry:
        Logger.warning(
            f"No fade builder registered for {type(target_cue).__name__}; "
            f"inheriting one via MRO — register an explicit builder"
        )
    return _fade_builder(target_cue, fade_cue, start_mtc_ms, motion_id)
```

This yields: consistency with the five existing cue registries; no mid-show hard failure for a subclass that
legitimately inherits; a loud audit trail the first time an unregistered type fades; and `_fade_builder.registry`
as a cheap test hook — assert that every fadeable type in `cuemsutils.cues` has an **exact** registration, so
the warning path is never reached in-tree.

**Consequence for Contract 5.** If `singledispatch` is chosen, `FadePayloadBuilderProtocol` **is not needed** —
registered functions replace builder objects, and the contract reduces to a documented function signature plus
the returned-dict key set. Contract 5 stays a `Protocol` class only if the dict-of-builder-objects shape (B2's
current sketch) is chosen instead. Whoever decides B must also update Contract 5 accordingly.

#### B.4 Separate recommendation — split B2, and fix P13 now

P13 (fade dispatch loses `end_value` records on partial failure, `ActionHandler.py:630-664`) is a **live defect
with a live consequence**: the next fade on an already-faded layer computes `start_value` from a stale pre-fade
level — the same class of bug `2608ea8` and `afebe48` were written to eliminate. It needs **no registry
whatsoever**; the fix is to record each entry immediately after its own successful send, inside the existing
dispatch loop.

The registry, by contrast, is justified only by "the next fadeable cue type", which does not exist. Under the
constitution's YAGNI rule that work should not start yet — but bundling P13 into it leaves a real defect in the
field until a speculative feature arrives.

**Recommend splitting §7 B2 into two independently shippable pieces:**

- **B2a — fix P13 (and criterion 2, the `entry.pop("motion_id")` mutation).** Own commit, own RED gate: a
  multi-layer `VideoCue` fade where layer 2's send raises must leave layer 1's `end_value` recorded on
  `target._osc`. No registry, no protocol, no new module. **Schedulable immediately, alongside Steps 1–9.**
- **B2b — the builder registry.** Own spec and branch, triggered by the first new fadeable cue type, carrying
  Decision B, criterion 3 (error surface) and criterion 4 (duration guard placement).

This also removes the awkwardness of a "Step 10" that is simultaneously out of scope and the gate for a live
bug fix.

---

## 13. Remaining Questions

Everything still unanswered after the 2026-08-10 validation and the §12 briefs, grouped by when the answer is
needed. §12 A and §12 B are excluded — they have full briefs and recommendations; these are the ones with no
recommendation yet, because each needs a call this document has no standing to make.

### Q1 — Does this become one spec or several? *(needed first)*

`specs/` currently holds `004-gradient-engine-phase6`, `005-gradient-osc-transport`,
`006-cuemsdeploy-async-refactor`, `007-cuemsdeploy-sync-fallback`. This work has no feature number, and the
material splits along at least three natural seams:

- Steps 1–9 — the `ActionHandler` refactor proper,
- B2a — the P13 fade-record fix (§12 B.4), independent of everything else,
- controller integration — Contracts 1–4, blocked on Steps 6–8.

They have different blockers and different reviewers. One spec covering all three would be gated on its slowest
part. **Recommend three, but the numbering and branch strategy are the maintainer's call.** Per the constitution
this also decides where the design notes live (`specs/NNN-feature/` vs the current `specs/planning/`).

### Q2 — Who owns the project script, and therefore `get_cue_by_id`? *(needed before Contract 3)*

Contracts Contract 3 lists `get_cue_by_id` as "NOT YET IMPLEMENTED — add alongside controller integration", as
though it were an additive method. It is not. Verified at `e210b26`:

- **`CueHandler` holds no script reference at all** — it knows only `_armed_cues`.
- The script lives on `NodeEngine` (`self.script`, e.g. `NodeEngine.py:962-968`).
- The lookup primitive exists in cuemsutils: `CuemsScript.find(uuid)` and `CueList.find(uuid)`.

So "any cue in the loaded project, armed or not" is not information `CueHandler` currently has. Three ways out,
each with a different cost:

| Option | Consequence |
|---|---|
| Give `CueHandler` a script reference | Widens the singleton's responsibility and adds a load/unload lifecycle it does not have today |
| Put `get_cue_by_id` on `NodeEngine`, drop it from `CueHandlerProtocol` | Splits the controller-facing surface across two objects — `attach()` would need a fourth handle |
| Pass the script (or a resolver callable) into the lookup | Keeps `CueHandler` stateless about projects; changes the protocol signature |

Until this is answered, Contract 3 publishes a method nobody can implement.

### Q3 — What value scale does `route_control_event` actually carry? *(needed before Contract 4)*

Contract 4 specifies "value: normalized float 0.0–1.0". The existing receivers **do not agree with each other**,
verified at `e210b26`:

| Receiver | Scale handling |
|---|---|
| `route_audio_message`, `cue` branch (`CueHandler.py:907-916`) | clamps to 0.0–1.0; comment: "UI already sends 0.0-1.0 via `sliderToFloat()`" |
| `route_audio_message`, `mixer` branch (`CueHandler.py:884-899`) | `float(value)`, **no clamp, no scaling** |
| `route_dmx_message` (`CueHandler.py:923-949`) | passes `value` through **raw**, no conversion |

A `route_control_event` that normalizes everything to 0.0–1.0 would therefore need the DMX branch to rescale, or
it breaks DMX. Decide once, in `route_control_event`, and state it: either the front door normalizes and each
`route_*` rescales, or the front door is scale-agnostic and the namespace defines the range.

**Resolved sub-question, for the record.** The dotted `parameter` → `path_parts` mapping *is* a clean
`split(".")`: `'mixer.0.master.volume'` → `['mixer', '0', 'master', 'volume']`, exactly
`route_audio_message`'s documented input. Two caveats worth carrying into the spec: the trailing `'volume'`
element is decorative (the audio routes build their OSC command from `path_parts[1]` / `path_parts[2]` only),
and the DMX convention differs — `route_dmx_message` searches for the literal `'mixer'` element and joins
everything after it.

### Q4 — How are controller modules discovered and configured? *(needed before Contract 1)*

Contract 1 defines `attach()` / `detach()` and §12/Lifecycle fixes *where* they are called. Nothing specifies
**which** modules get attached, or where that list comes from: a `network_map.xml` / `settings.xml` section, a
new config file, Python entry points, or a hardcoded registry. This also decides how a module's own settings
(MIDI port name, listen port, button map) reach it — `attach()` currently takes no configuration argument at
all. Note the project CLAUDE.md constraint that editing `network_map.xml` requires restarting both engines
*and* `cuems-editor`, which argues against putting module config there.

### Q5 — Is `fade_out`'s missing `disarm()` fixed now or with the fade envelope? *(needed before Step 8)*

P15. The in-code TODO defers it to "when implementing real fade behavior", which is unscheduled. The fix is a
two-line change mirroring `_handle_stop` (`ActionHandler.py:467-474`). The argument for doing it now is that
Step 8 exposes `fade_out` to hardware buttons, turning a rarely-scripted leak into a per-press one. The argument
against is that `fade_out`'s semantics change wholesale when the envelope lands, so a fix now may be thrown
away. **No recommendation** — it depends on whether the fade envelope is on the near roadmap, which this
document cannot see.

### Q6 — Does CI gain mypy? *(sub-question of §12 A, needed before Step 4)*

Restated here because it is a standalone call with its own cost. CI runs flake8 only
(`.github/workflows/ci.yml:46`). §12 A.1 measured that `isinstance`-based protocol conformance is both
order-dependent (an annotation-only attribute reads as non-conforming) and blind to signature drift. Without
mypy the protocols are convention enforced by review, and no conformance test should be written that implies
otherwise.

---

**Not open, recorded so they are not reopened:** the `_handle_stop` 100 ms sleep (P14 — documented, deliberately
unscheduled, published in Contract 2); action-dispatch serialisation (Contract 1 states the engine does not
serialise and modules must not assume it does); the closed action vocabulary (§3.4); `attach()` placement
(fixed in the contracts Lifecycle section); and `ActionHandler`'s process scope (node-engine only, verified).
