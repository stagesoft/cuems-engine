# Evidence — 008-cuems-utils-migration

Every captured run records the library commit (`git -C ../cuems-utils rev-parse HEAD`) beside the
suite output (G6). **The comparison baseline is `baseline-suite-postmerge.txt`** (28 F / 7 E / 831 P).

| File | What it records |
|---|---|
| `baseline-environment.md` | environment table for the baselines (FR-001) |
| `baseline-suite.txt` | pre-merge suite record (before `rc_1` was merged) — historical only |
| `baseline-suite-postmerge.txt` | **the comparison baseline**: 28 failed / 7 errors / 831 passed |
| `step0-environment.md` | T002 — environment check before any change |
| `step1-network-map-converted.txt`, `step1-attribution.md` | T004/T005 — suite after converting the `network_map.xml` fixture; every failure attributed |
| `step2-settings-converted.txt` | T006 — suite after converting the `settings.xml` fixture |
| `failing-first-*.txt` | a test seen red for its stated reason before its implementation |
| `identity-*.txt`, `identity-audit.md` | Group 7 — test uuid literals, identity sweep, audit |
| `fixture-*.txt` | provenance of fixtures added by this feature |
| `us*-*.txt` | per-user-story characterization and green runs |
| `test-retirements.md` | every test deleted or rewritten away, with the reason |
| `not-performed.md` | every item not performed on this dev box, with the reason |
| `ci-red-by-construction.md` | why CI stays red until `cuemsutils` rc16 publishes |
| `exit-criteria.md` | SC-001…SC-012 pass/fail |
| `final-suite.txt` | the final full suite, compared to the post-merge baseline |
