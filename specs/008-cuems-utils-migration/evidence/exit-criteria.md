# Exit criteria — quickstart §2 (T062)

Run 2026-09-29 on engine `56dbf9b`+polish worktree, cuems-utils `2a88a7c`.

| SC | Check | Result |
|---|---|---|
| 001 | `grep -rn 'node_type\|NodeType\.' src/` | **PASS** — no output. Exempt by name, reason "not shipped" (FR-021): `dev/network_map.xml`, `dev/CuemsEngine_old.py` |
| 002 | `ls $E/*failing-first*` | **PASS** — 14 files, each naming the value it failed on. Sites 1–2: `failing-first-site1-2-controller-lookup.txt` (T011); sites 3–4: `failing-first-site3-4-find-hosts.txt` (T018, M8 held) |
| 003 | `grep -rnE 'cuemsutils\.(xml\|config)' src/`; `tests/test_public_surface.py` | **PASS** — no output; 4 passed |
| 004 | `grep -rn 'get_nodes_by_adoption\|_adopted_uuids_from_network_map\|find_hosts' src/ tests/ \| grep -v tests/test_public_surface.py` | **PASS** — no output |
| 005 | `pyproject.toml:50`; `debian/control:26-28` | **PASS** for the ranges (`cuemsutils = ">=0.1.0rc16,<0.1.1"`; `cuems-utils (>= 0.1.0rc16)`, `(<< 0.1.1~)`, `cuems-common (>= 1.3.0-23~)`). The re-lock is **not performed** — rc16 unpublished (`ci-red-by-construction.md`, `not-performed.md`). (quickstart's `sed -n 41p` line number is stale: the pin is at :50.) |
| 006 | `final-suite.txt` | **PASS** — 939 passed, 0 failed, 0 errors (baseline 28 F / 7 E / 831 P); every removed test id accounted for in `test-retirements.md` |
| 007 | load + GO a v1 and a v2 `script.xml` | **In-suite PASS** — `test_project_load.py::test_complex_project_load_on_controller[script-v1\|script-v2]`, `test_read_script.py`. **On a rig: not performed** (`not-performed.md`) |
| 008 | CHANGELOG top; drift test; `git diff 27b27f5 -- debian/changelog`; hand-off | **PASS** — `## v0.1.0rc7 — UNRELEASED` with `### Upgrade notes`, then rc6, rc5, rc4, rc3, then rc2 untouched; `__version__` `0.1.0rc7`; drift test 2 passed; debian/changelog diff empty; `handoff-relations-release-order.md` present |
| 009 | `not-performed.md` | **PASS** — every hardware/cluster/packaging item listed, performed-in-part or not performed with its reason |
| 010 | cuemsutils deprecation warnings in the suite | **PASS** — none (`final-suite.txt` run with `-rw`: 0 warnings of any kind) |
| 011 | `grep -rn 'CTimecode(cue.media.duration)' src/` | **PASS** — no output |
| 012 | `tests/test_ids.py tests/test_cluster_identity.py tests/test_identity_sweep.py`; `identity-audit.md`; uuid-literal scan | **PASS** — 30 passed (incl. G5 stale-prefix and G2 sentinel cases); every audit hit resolved or justified; literals: `identity-test-literals.txt` (all uuid4 except FR-028's named cases; unloaded fixtures out of scope) |
