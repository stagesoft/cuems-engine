# Quickstart: Async Cue Execution Test Suite

**Branch**: `001-async-cue-tests` | **Date**: 2026-02-26

## Prerequisites

- Python 3.11+
- Dev dependencies installed: `pip install -e ".[dev]"`

## Run the Test Suite

```bash
# All unit tests (should complete in ≤ 30s)
pytest -m unit tests/async_cue/

# Specific user story
pytest -m unit -k "single_cue_lifecycle" tests/async_cue/
pytest -m unit -k "concurrent_cues" tests/async_cue/
pytest -m unit -k "post_go" tests/async_cue/
pytest -m unit -k "mtc_loop" tests/async_cue/
pytest -m unit -k "error_cleanup" tests/async_cue/

# With coverage
pytest -m unit --cov=src/cuemsengine/cues --cov-report=term-missing tests/async_cue/

# Stress tests only
pytest -m unit -k "stress" tests/async_cue/
```

## File Layout

```
tests/
├── async_cue/                    # New test package
│   ├── __init__.py
│   ├── conftest.py               # Async-specific fixtures
│   ├── test_single_lifecycle.py  # US1: single cue lifecycle
│   ├── test_concurrent.py        # US2: concurrent execution
│   ├── test_post_go.py           # US3: post-go chaining
│   ├── test_mtc_loop.py          # US4: MTC sync in loop
│   ├── test_error_cleanup.py     # US5: error handling
│   ├── test_loop_identity.py     # FR-011/012/014: event loop checks
│   ├── test_wait_for_cue.py      # FR-013: missing method
│   └── test_edge_cases.py        # Edge cases from spec
├── async_helpers/                # Reusable test components
│   ├── __init__.py
│   ├── factories.py              # MockCueFactory
│   ├── loops.py                  # EventLoopFixture
│   ├── mtc.py                    # MockMtcListener
│   ├── osc.py                    # MockOscClient
│   ├── players.py                # MockPlayerHandler
│   └── assertions.py             # LifecycleAssertions
```

## Verification

After implementation, confirm:

1. `pytest -m unit tests/async_cue/` — all pass, ≤ 30s
2. `pytest --cov=src/cuemsengine/cues --cov-report=term-missing tests/async_cue/` — ≥ 80% branch coverage
3. No new dependencies added to `pyproject.toml`
