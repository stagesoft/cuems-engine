<!--
SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Inputs to the coordinated version bump: pyossia, the native-library forks, and engine CI

**Measured 2026-10-15** on `cuems-engine` `feat/xml-refactor` and `libossia` `cuems`. **Status:
partly executed.** The pyossia naming fix and the engine's dev/CI setup are done and pushed (§2, §3).
The rest are findings for the coordinated-bump spec to absorb (§4–§6). Section references like
"pre-spec §4" point at
[`cuems-utils/specs/planning/coordinated-release-version-bump.md`](../../../cuems-utils/specs/planning/coordinated-release-version-bump.md).

**What this adds to the pre-spec.** The pre-spec covers the seven CUEMS repositories. It doesn't
mention the three **native forks** that the engine loads or that CI installs: `stagesoft/libossia`
(pyossia), `stagesoft/libmtcmaster` and `stagesoft/rtpmidid`. pyossia had the same version collision
the pre-spec found in four repositories, and it has been resolved. The other two have smaller
naming and relation gaps (§4.4).

---

## 1. Summary

| # | Finding | State |
|---|---|---|
| 1 | `python3-pyossia 2.0.0-rc6+124+cuems2` was **published twice with different contents**: the same collision as pre-spec §1 | ✅ resolved by releasing `cuems3` (§2) |
| 2 | Before cuems3, pyossia's wheel version and deb version came from two unrelated sources, and every build reported `pyossia.__version__ == "0+unknown"` | ✅ fixed in libossia: one version source (§2.3) |
| 3 | pyossia was **not a Poetry dependency**. CI used it from the system `.deb` through `system-site-packages`; dev venvs held a hand-built wheel | ✅ pinned release wheel in the dev group (§3) |
| 4 | Engine CI ran on `ubuntu-22.04` with deadsnakes Python and `dpkg --force-depends` workarounds | ✅ moved to a `debian:bookworm` container (§3) |
| 5 | **No published `cuemsutils` can run `feat/xml-refactor`**. PyPI rc16 gives 527 import errors, which confirms pre-spec §2 with CI evidence | ⛔ blocks engine CI until it gets `cuemsutils` from the re-cut tag (§4.1, §4.3) |
| 6 | The engine's `poetry.lock` was out of date for 16 days, hidden by a CI venv cache keyed on the lock file | ✅ relocked. ⚠ pattern applies to every Poetry repo (§4.2) |
| 7 | Version edges missing from pre-spec §4: `python3-pyossia`, an **undeclared** runtime dependency on `libmtcmaster`, and an rtpmidid package whose version doesn't match its tag | open (§4.4) |

## 2. libossia / pyossia: collision found and resolved

### 2.1 The collision

Two changelogs in `libossia` (`cuems` branch) both claimed `cuems2`:

| File | `cuems1` | `cuems2` |
|---|---|---|
| `src/ossia-python/debian/changelog` (Ion, read by `dpkg-buildpackage`) | bundle support | bundle fixes (2025-11-04) |
| `src/ossia-python/changelog` (stray copy, Adrià) | bundle support | `Node.remove_child` (2025-12-04) |

- The GitHub release titled `v2.0.0rc6+cuems2` points at the plain git tag `v2.0.0rc6` (`e4c3c2fbd`). Its `.deb` **has** `remove_child`.
- cuems-engine `dd60f76` requires `cuems3` because "cuems2 has no Node.remove_child". That's true of Ion's `cuems2`.
- So hosts can hold either binary under one version, and apt never replaces one with the other. The `requires_node_removal` skip in `tests/test_ossia.py` exists because of this.

### 2.2 The resolution: `2.0.0-rc6+124+cuems3`, released 2026-10-15

| Item | Value |
|---|---|
| Commits on `libossia` `cuems` | `92bf23fd2` version from changelog · `784083e63` release cuems3 · `83d5eb770` untrack dpkg output · `ef78ca309` release tool |
| Tag | `v2.0.0-rc6+124+cuems3` → `ef78ca309` (signed) |
| Release | <https://github.com/stagesoft/libossia/releases/tag/v2.0.0-rc6%2B124%2Bcuems3> |
| `.deb` | `python3-pyossia_2.0.0-rc6+124+cuems3_amd64.deb`, sha256 `f46e62b00c8cd216…` |
| Wheel | `pyossia-2.0.0rc6+124.cuems.3-cp311-cp311-linux_x86_64.whl`, sha256 `d7b3118ccf25dba5088eb2341ceb27b35971ce67a12def736522630a1bd7d76f` |
| Contents beyond the published cuems2 | native OSC `#bundle` sending in `osc_protocol` (`86964e24c`) · null-parent crash fix in `remove_child` (`3d96d30cb`) |
| Built on | Debian 12, gcc 12.2, Python 3.11.2. Needs GLIBC ≥ 2.34 and GLIBCXX ≥ 3.4.29, so it also loads on Debian 13 and Ubuntu 22.04 (both checked) |

The release files are byte-identical to the local build from `ef78ca309`.

### 2.3 The version scheme (documented in libossia `src/ossia-python/README.md`)

- **One version source:** the top entry of `src/ossia-python/debian/changelog`. `dpkg-buildpackage` reads it. `setup.py` maps it to a Python version and writes it into the built `pyossia/_version.py`. The stray changelog was deleted.
- **Tag = `v<debian version>`**, and the GitHub release uses the same name.
- **Build both artifacts on Debian 12 from the tag:** `tools/build-pyossia-release.sh` runs in a `debian:bookworm` container. It refuses to run with uncommitted changes, so artifacts always match a commit.
- **Next stable is `v2.0.1-cuems`** (maintainer decision), followed by `2.0.1-cuemsN`. It isn't `2.0.0`: dpkg reads `2.0.0-rc6+124+cuemsN` as upstream `2.0.0` with revision `rc6+124+cuemsN`, and that revision sorts above any numeric one, so a plain `2.0.0-1` would install as a downgrade.

| Debian | Wheel (PEP 440) | Tag |
|---|---|---|
| `2.0.0-rc6+124+cuemsN` | `2.0.0rc6+124.cuems.N` | `v2.0.0-rc6+124+cuemsN` |
| `2.0.1-cuems` | `2.0.1+cuems` | `v2.0.1-cuems` |
| `2.0.1-cuemsN` | `2.0.1+cuems.N` | `v2.0.1-cuemsN` |

⚠ **Why the number is split off (`cuems.N`):** Python compares a mixed letters-and-digits segment
as text, so `+cuems10` would sort **below** `+cuems9`. Splitting it off fixes that. Debian ordering
doesn't have this problem. Every ordering above was checked with `dpkg --compare-versions` and
`packaging.version.Version`.

### 2.4 How libossia fits the coordinated set

libossia's version follows upstream ossia, not the CUEMS release train. The spec needs to decide
whether it is a **member** of the coordinated landing (does `v2.0.1-cuems` ship at
`xml-refactor-merge-candidate`?) or an **independent input** whose released version the CUEMS
packages pin. Either way, it has two version edges (§4.4) that the relation matrix must list.

## 3. Engine changes already on `feat/xml-refactor`

| Commit | Change |
|---|---|
| `fc9e9af` | pyossia pinned in the **dev group** of `pyproject.toml` to the cuems3 wheel (URL + hash in `poetry.lock`, linux/x86_64 only). Runtime still uses the `.deb` (`debian/control:30`); **bump both together**. Relock (also moves `cuemsutils` rc14 → rc16, §4.2). README prerequisites and test commands fixed. `tests/test_ossia.py` skip comment updated. `CLAUDE.md` paragraph |
| `729f8b6` | CI `test` job runs in **`container: debian:bookworm`** on `ubuntu-latest`. No deadsnakes; isolated venv (no `system-site-packages`); `librtpmidid0` installed by apt; `libmtcmaster` still `--force-depends` (§4.4); Poetry pinned `2.4.1` via pipx; badge via `pipx run`; adds `iproute2`/`procps` (the engine shells out to `ss`/`pgrep`) and `git`/`rsync`; new venv cache key. The lint job stays on `ubuntu-latest` |

**On the dev box after checkout:**

- `poetry install` replaces any hand-built pyossia with the pinned wheel.
- If the venv uses an editable `../cuems-utils` (required on this branch, §4.1), run `poetry install --only dev` instead. A full `poetry install` would replace that editable install with PyPI rc16.
- Check with `poetry run python -c "import pyossia; print(pyossia.__version__)"`, which should print `2.0.0rc6+124.cuems.3`.

**Test evidence (2026-10-15):**

| Where | Unit | Integration (fast) | Notes |
|---|---|---|---|
| Dev box, editable cuems-utils | 885 passed | 32 passed | coverage 66% (floor 45). lint green |
| Dev box, full suite with no marker filters | 922 passed, **1 failed** | | `test_project_go_from_controller`, a known issue (`integration-slow-tests-investigation.md`). It fails the same way with the old pyossia, so the wheel isn't the cause |
| Local replay of the CI job in `debian:bookworm`, PyPI `cuemsutils` | **527 errors** | | §4.1 |
| Same replay, `cuemsutils` from the `../cuems-utils` checkout | 885 passed | 32 passed | coverage 66%. Badge step works |

The real GitHub workflow has **not** run. It only triggers on `main`/`rc_1` and PRs to them. To run
it by hand: `gh workflow run ci.yml --ref feat/xml-refactor`.

## 4. Findings for the coordinated-bump spec

### 4.1 The `cuemsutils` floor is broken, confirmed from the consumer side

This confirms pre-spec §2 with an actual install. A clean `poetry install` of `feat/xml-refactor`
resolves `cuemsutils 0.1.0rc16` from PyPI, and **526 of 527** test modules then fail at import:
`No module named 'cuemsutils.tools.identity_check'` and `cannot import name 'coerce_identity'`. Those
names arrived in cuems-utils `c683bed` (feature 012, 2026-09-30). The `v0.1.0rc16` tag doesn't
contain them.

One more measurement for pre-spec §1: `../cuems-utils` `feat/xml-refactor` declares `__version__ =
"0.1.0rc16"` but `git describe` gives `v0.1.0rc14-263-gb83d5c2`. **The `v0.1.0rc16` tag isn't
even an ancestor** of that branch. It's the same shape as pyossia's `cuems2`: one number, two
codebases.

### 4.2 Lock files can go out of date unnoticed, and the CI cache hides it

- `pyproject.toml` raised the floor to `cuemsutils >=0.1.0rc16` in `d6ac254` (2026-09-29), but `poetry.lock` stayed on rc14 until `fc9e9af`. `poetry check --lock` failed on the committed tree.
- CI didn't notice because the venv cache is keyed on `hashFiles('**/poetry.lock')`. The lock didn't change, so the cache kept hitting and `poetry install` was skipped.
- **For the spec:** the bump edits `pyproject.toml` bounds in four repositories (pre-spec §4.1). Each must regenerate its lock in the **same commit**, and each Poetry repo's CI should run `poetry check --lock` before the cache step. Not added to engine CI yet.

### 4.3 Rule 5 needs a way for engine CI to get `cuemsutils` without PyPI

Pre-spec rule 5 says validation runs on the re-cut tags and "nothing waits for `0.1.1` on PyPI".
Engine CI resolves `cuemsutils` from PyPI only, so on this branch it stays red until the library
is published. Two ways to make CI validation work under rule 5:

| Option | How | Trade-off |
|---|---|---|
| A. Install from the tag in CI | After `poetry install`: `poetry run pip install "cuemsutils @ git+https://github.com/stagesoft/cuems-utils@<re-cut tag>"` | One line, uses the re-cut tag exactly. The lock no longer describes the CI env |
| B. Wheel from the tag | Build the wheel from the cuems-utils tag (or download it as a release asset), then use `PIP_FIND_LINKS` | Same mechanism as the pre-spec §11.1 packaging demonstrations. Needs somewhere to host the wheel |

Publishing `0.1.1` to PyPI then lets CI return to the plain lock. Nothing in the engine is
blocked otherwise.

### 4.4 Version edges missing from pre-spec §4

| Edge | Site | Today | Note |
|---|---|---|---|
| engine → `python3-pyossia` | `cuems-engine/debian/control:30` | `>= 2.0.0-rc6+124+cuems3` | **Now satisfiable** (released 2026-10-15). It admits both `2.0.0-rc6+124+cuemsN` and `2.0.1-cuems*` |
| engine dev → pyossia wheel | `cuems-engine/pyproject.toml:84` | cuems3 URL | Must move with the edge above |
| engine → `libmtcmaster` | **none** | — | ⚠ `src/cuemsengine/core/libmtc.py:8` loads `libmtcmaster.so.0`, imported by `ControllerEngine.py:19`. No package declares it (checked `cuems-engine` and `cuems-common` `debian/control`). An **undeclared runtime dependency** |
| `libmtcmaster` → `cuems-utils` | `libmtcmaster_0.0.2-0` control | `Depends: … cuems-utils` (unversioned) | A C library depending on the Python library package. Unversioned, so not broken by `0.1.1`, but it stops apt from installing libmtcmaster anywhere without `cuems-utils` (CI uses `--force-depends` because of it). Probably a mistake; worth asking the libmtcmaster maintainers |
| rtpmidid fork naming | release tag `v26.06-1stagelab1` | package version `26.01~1~g7f552` | ⚠ tag and package version disagree (`26.06` vs `26.01`). Same problem as pyossia's before cuems3. Also unverified: whether the engine needs `librtpmidid0` at all, since its source only refers to rtpmidid's ALSA port name |

### 4.5 Engine self-version drift is still there

Pre-spec §3.1 still holds as of `729f8b6`: `debian/changelog:1` says `0.1.0rc2-3`, while
`pyproject.toml:11` and `src/cuemsengine/__init__.py:5` say `0.1.0rc7`. `cuems-engine-mock` still
pins `cuems-engine (>= 0.1.0rc2)` at `debian/control:49`.

### 4.6 Command-line tools the engine runs, which `debian/control` doesn't declare

The engine calls `ss` (`iproute2`, `PortHandler`) and `pgrep` (`procps`, `PlayerHandler`). Neither
appears in `debian/control`. Both are `Priority: important` and present on any standard Debian
install, which is why this only showed up in the slim container. Low risk, but the spec should
decide whether to declare them.

## 5. Rules worth applying across the ecosystem

These are what fixed pyossia, stated generally enough for the spec to apply to every repository:

1. **One version source per repository.** Every other version string is derived from it: the
   wheel, `__version__`, the tag. pyossia, the engine (§4.5) and cuems-utils (§4.1) each showed what
   happens with two.
2. **Never publish a different binary under an existing version.** apt and pip treat equal
   versions as the same package. Any change to shipped code gets a new changelog entry first.
3. **Tag = `v<package version>`, and the release name = the tag.** pyossia's `cuems2` release
   pointed at a plain `v2.0.0rc6` tag, and the rtpmidid tag names a version its package doesn't
   carry.
4. **Build release artifacts on Debian 12 from the tag**, so nothing links against a newer glibc
   or libstdc++ than production has.
5. **Forks carry a visible suffix** (`cuemsN`, `stagelabN`) in both the Debian and the Python
   version.
6. **Check every new version's ordering with both tools**: `dpkg --compare-versions` and
   `packaging.version.Version`. The `cuems10` < `cuems9` trap (§2.3) only shows up in the second.

## 6. Open items

1. **Ask Ion whether a `cuems3` deb was ever built.** `86964e24c` says "Related to pyossia cuems3
   package", but no changelog entry existed until 2026-10-15. If a deb was built and installed
   anywhere, it's a second binary under the released version.
2. **Is libossia a member of the coordinated landing** (`v2.0.1-cuems` there) or an independent
   input? (§2.4)
3. **Engine CI under rule 5**: option A or B (§4.3), and `poetry check --lock` in every Poetry
   repo's CI (§4.2).
4. **Declare `libmtcmaster`** in `cuems-engine/debian/control`, and get the libmtcmaster maintainers
   to drop the `cuems-utils` dependency (§4.4).
5. **rtpmidid**: fix its tag/version mismatch, and confirm whether the engine needs `librtpmidid0`
   (§4.4).
6. **pyossia wheel puts its `.so` in `purelib`.** pip installs it fine, but `auditwheel` refuses it.
   Fix in libossia `setup.py` if a manylinux wheel is ever needed.
7. **Declare `iproute2` and `procps`** or leave them implicit (§4.6).
