<!--
SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Quickstart: running and verifying 009

The commands an implementer or reviewer runs. They are listed in execution order, and each step
names the evidence file it writes. The repository root is `cuems-engine/`; the sibling checkouts sit
beside it under `/disk/Projects/StageLab/`. Naming follows 008: `evidence/failing-first-<id>.txt`
holds the red output captured **before** each fix.

## 0. Environment

```bash
export PYENV_VERSION=3.11.9
PY=.venv-016/bin/python          # cuemsutils 0.1.1 editable from ../cuems-utils
POETRY=.venv-016/bin/poetry      # 2.4.1, the version CI pins
export PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring   # local only (research R1)
```

`libmtcmaster.so.0` is absent on the dev host, so the suite needs the same `core/libmtc.py` stub in
**both** arms (WO §6.1). Record the stub, and the cuems-utils commit in use, in
`evidence/environment.md`.

## 1. Re-measure (start, and again before hand-off) → `evidence/remeasure-{start,handoff}.md`

```bash
git fetch --all --tags
for r in origin/debian/bookworm origin/rc_1; do
  echo "$r $(git rev-parse --short $r) behind=$(git rev-list --count HEAD..$r)"; done
for h in 35cbe78 d50ee4b 5a1811c 3c11c60; do
  git merge-base --is-ancestor $h origin/rc_1 && echo "$h on rc_1" || echo "$h not on rc_1"; done
# stray-head sweep (WO §4.1 method) → evidence/stray-head-sweep.md, one verdict per row
for r in $(git for-each-ref --format='%(refname:short)' refs/remotes/origin refs/tags); do
  n=$(git rev-list --no-merges --count "$r" ^HEAD ^origin/debian/bookworm 2>/dev/null); [ "$n" != 0 ] && echo "$r $n"; done
```

## 2. Baseline (arm A) and the merge (arm B) → `evidence/suite-arm-{A,B}.txt`

```bash
$PY -m pytest tests -m "not integration" -n auto -p no:cacheprovider -q > evidence/suite-arm-A.txt
$PY -m pytest tests -m "integration and not slow" -q >> evidence/suite-arm-A.txt

git merge --no-ff --no-commit origin/debian/bookworm     # resolve per spec FR-004; never -X ours/theirs
git commit -S                                            # resolutions only
# … same two pytest passes → evidence/suite-arm-B.txt; expect exactly the 10 of spec M5
git merge --no-ff -S origin/rc_1                         # ancestry; version sites → ours
git merge --no-ff -S 35cbe78 && git merge --no-ff -S d50ee4b
```

## 3. Hotfix line (FR-008) → `evidence/hotfix-rc5-equivalence.md`

```bash
git cherry -v HEAD v0.1.0rc5-6            # every "+" line must map to an rc_1 commit in the table
git show v0.1.0rc5-6:debian/changelog     # copy the rc5-2…rc5-6 entries verbatim (dpkg order)
git merge -S -s ours v0.1.0rc5-6 -m "…cites evidence/hotfix-rc5-equivalence.md"
```

## 4. Each adaptation (TDD) → `evidence/failing-first-<A-n|R-n>.txt`

```bash
$PY -m pytest <node-id> -q 2>&1 | tee evidence/failing-first-A-1.txt   # must be red
# minimal fix → green → commit -S "fix(009/A-1): …"
```

## 5. Identity audit (FR-017, SC-005) → `evidence/identity-audit-009.md`

Re-run 008's method (`specs/008-cuems-utils-migration/evidence/identity-audit.md`) over the merged
`src/`, at minimum:

```bash
git grep -nE 'str\((self\.)?[a-z_]*\.?(id|uuid|cue_id|sender)\b|sorted\(|\.split\(' -- src/
git grep -n 'import.*\bUuid\b' -- src/          # must be empty
```

## 6. Changelog (FR-030…FR-033) → `evidence/changelog-check.txt`

```bash
$PY -m pytest tests/contract/test_changelog_complete.py -q -rs   # must RUN (no "missing refs" skip)
dpkg-parsechangelog -l debian/changelog -S Version              # 0.1.1-1
```

## 7. Packaging → `evidence/relation-verdicts-009.txt`, `evidence/bookworm-build.md`

```bash
../cuems-utils/specs/016-coordinated-minor-bump/tools/verdicts.sh   # engine rows: 27/27
../cuems-utils/specs/016-coordinated-minor-bump/tools/bookworm-build.sh   # both debs; do not publish
dpkg -I <engine>.deb | grep Version; dpkg -I <mock>.deb | grep -E 'Depends|Conflicts'
dpkg -c <engine>.deb | grep CACHEDIR || echo "no CACHEDIR.TAG"
```

## 8. Cleanup checks (SC-009) → `evidence/test-layout-moves.md`, `evidence/cleanup-check.txt`

```bash
$PY -m pytest --collect-only -q > /tmp/before.txt     # before each cleanup commit
# … move …
$PY -m pytest --collect-only -q > /tmp/after.txt      # diff = path prefix + listed retirements only
git grep -nE "dev/test_xml_files|test_json_files|pytest_cuems_plugin|CuemsEngine_old" -- . ':!specs'
git grep -nE "(^|[^/])scripts/link-dev\.sh" -- . ':!specs'     # stale path; dev/scripts/… is fine
ls tests/test_*.py 2>/dev/null                        # nothing
unshare -n $PY -m pytest tests/unit tests/contract -n auto -q   # no network
```

## 9. The gate (SC-010) → `evidence/ci-gate.md`

Needs `gh` or the web UI. `gh` is not installed on the planning host.

```bash
gh workflow run ci.yml --ref 009-release-line-reconciliation -f cuemsutils_ref=xml-refactor-merge-candidate
gh run watch && gh run view --log   # copy URL, SHA, cuemsutils ref+commit, counts, xfail list
```

## 10. Hand-off

1. Rewrite `../.xml-refactor-tag-messages/cuems-engine.txt` (FR-058).
2. Write the upstream reports and sibling notes (`upstream-reports/`).
3. Final task: `git grep -n release-line-reconciliation-0.1.1 -- . ':!specs/009-*'` must be empty,
   then `git rm specs/planning/release-line-reconciliation-0.1.1.md` (FR-060).
4. The `--no-ff` merge into `feat/xml-refactor` and the tag re-cut are the maintainer's.
