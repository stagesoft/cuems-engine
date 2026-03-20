# Quickstart: Validate Action Cue Handler Plan

## 1) Preconditions

- Feature branch checked out: `002-action-cue-handler`
- Poetry environment installed and dependencies available (`poetry install`)
- A test project/script with actionable cue targets available

## 2) Run focused automated checks

```bash
poetry run pytest -q tests/test_core_baseengine.py tests/test_project_go.py
```

Then run the full suite for regression confidence:

```bash
poetry run pytest -q
```

## 3) Validate cue-level action behavior

1. Load a project with at least one actionable target cue.
2. Trigger action cues for `play`, `stop`, `enable`, `disable`, `fade-in`,
   `fade-out`, and `go-to`.
3. Confirm target cue state changes are applied.
4. Confirm unrelated cues do not change state.

## 4) Validate invalid-action safety

1. Trigger an unknown `action_type`.
2. Trigger a known cue-level action with missing/invalid target.
3. Verify command is rejected safely.
4. Verify runtime remains stable and logs contain actionable reason.

## 5) Performance verification

- During normal action traffic, sample command-to-state reflection latency.
- Pass condition: >=95% of sampled actions reflected within 1 second.
