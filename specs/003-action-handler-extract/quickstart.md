# Quickstart: Validate Action Handler Extraction Plan

## Preconditions

- Branch: `003-action-handler-extract`
- Poetry env: `poetry install`
- Optional: read `contracts/action-handler-extensibility.md`

## 1) Automated checks

```bash
poetry run pytest -q tests/test_action_cue.py
```

After implementation, also run:

```bash
poetry run pytest -q
```

## 2) Regression: supported actions

Trigger each supported cue-level action (same list as feature `002-action-cue-handler`)
and confirm target cue state matches the pre-refactor baseline.

## 3) Dual registration

1. From test or dev harness, register a `before_dispatch` hook via the API exposed on
   `CueHandler`.
2. Register an `after_dispatch` hook via the same registry through a `NodeEngine` startup
   path (or test double).
3. Fire one action; confirm both hooks ran in documented order.

## 4) Result sink

1. Run with default `NodeCommunications` — confirm controller receives outcome traffic (or
   logged send) consistent with today.
2. Inject a fake sink — confirm outcomes are delivered to the fake without requiring live
   NNG.

## 5) Performance spot-check

Under light action load, confirm no noticeable delay vs baseline (or run timing helper
if added to tests).
