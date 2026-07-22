# `test_project_go_from_controller` — open issues

`tests/test_project_go.py::test_project_go_from_controller` is marked
`@pytest.mark.slow` (real NNG comms + real MTC sender/listener pair,
controller + node in one process). It is excluded from CI entirely — see
"CI status" below — because of the two unresolved issues documented here.

## A. Native `nng` panic on interpreter shutdown

Every run of `test_project_go_from_controller` — pass or fail, alone or in
a larger session — ends the Python process with a native crash during
`Py_FinalizeEx`, not a clean exit:

```
panic: pthread_mutex_lock: Invalid argument
This message is indicative of a BUG.
Report this at https://github.com/nanomsg/nng/issues
.../pynng/_nng.abi3.so(nni_panic+0xec)
.../pynng/_nng.abi3.so(nni_aio_fini+0x21)
.../pynng/_nng.abi3.so(nni_aio_free+0x17)
...
Task was destroyed but it is pending!
task: <Task pending name='Task-2' coro=<ControllerCommunications.editor_listener() ...>>
```

pytest itself reports `1 passed`; the OS-level exit code is SIGABRT/SIGFPE
(134/136), which any shell or CI step that checks `$?` sees as a failure.
Reproduces 100% of the time, standalone included — not an ordering effect.
Likely an NNG socket / asyncio event-loop teardown-ordering issue (an
in-flight `arecv_msg()` coroutine and a pending `editor_listener()` task
still referencing a socket that's being torn down when the interpreter GCs
it at exit). Candidate fix surface: explicit, ordered `nng_hub` /
`event_loop` close in `AsyncCommsThread`/`engine_cleanup`'s teardown before
process exit — not attempted yet, since it touches the same shutdown path
the real services use.

## B. Flaky GO-sequence timing

Independent of (A) and of `test_cpu_usage.py` ordering (verified by running
`test_project_go.py` alone, repeatedly, with nothing else in the session):
about 1 in 3 runs fails

```
AssertionError: Node engine is not running
assert '' == 'yes'
```

on the post-GO assertion (`node_engine.get_status("running") == "yes"`),
after the load phase already succeeded. This is a timing race somewhere in
the real GO path (`controller_engine.go_script()` → NNG dispatch → node
picks it up and flips its `running` status) — the test's fixed `sleep(1)`
after `go_script()` isn't always enough. Needs either a poll-with-deadline
in place of the fixed sleep (same pattern already used for the load-status
wait a few lines up) or a deeper look at what makes the GO path slower than
the load path. Not attempted yet.

## CI status

`test_project_go.py` and `test_cpu_usage.py` (CPU/memory threshold
assertions, separately unreliable on shared runners) are the only two
`@pytest.mark.slow`-marked tests, and both are excluded from CI —
`.github/workflows/ci.yml` only runs `-m "integration and not slow"`.
There is no CI step for the `slow` bucket at all right now, since with both
files excluded it would have zero tests to run. Run them manually/locally:

```bash
poetry run pytest -m slow tests/test_cpu_usage.py
poetry run pytest -m slow tests/test_project_go.py
```

If either follow-up above gets fixed, the natural next step is adding a
slow CI step scoped to just that file.
