# Python Version Migration Plan
# cuems-engine: 3.11 → 3.13

**Date:** 2026-06-15
**Branch context:** `format/standarization`
**Scope:** Analysis and roadmap for migrating the required Python version,
dual-distribution Debian packaging, and long-term support horizon.

---

## 1. Current State

| Item | Value |
|---|---|
| Runtime Python | 3.11.9 (pyenv, `.python-version`) |
| `pyproject.toml` constraint | `python = "^3.11"` |
| `[tool.black] target-version` | `["py310"]` ← already inconsistent |
| Debian target | Bookworm (12), system Python 3.11 |
| `debian/rules` | ~30 hardcoded `python3.11` path references |
| `debian/changelog` | tagged `bookworm` |
| CI workflows | all three hardcode `python-version: "3.11"` |

---

## 2. Why Not 3.12

Python 3.12 is a gap version with no clean deployment alignment:

- **Bookworm (12, current stable):** system Python is 3.11 → 3.12 venv requires a custom Python build at package build time.
- **Trixie (13, released 2026-06-10):** system Python is 3.13 → `python3-systemd` already requires `python3 (>= 3.13~)` on Trixie; a 3.12 venv cannot access system packages.

The `dh-virtualenv` build creates the venv from the system Python. A 3.12 venv fits neither deployment target without extra toolchain work, while providing marginal benefit over jumping directly to 3.13.

`python-rtmidi 1.5.8` *does* have `cp312` wheels (Linux x86_64 and aarch64), so the dependency side is clear for 3.12 — but the deployment side is not.

---

## 3. Target: Python 3.13

### 3.1 Dependency Compatibility Matrix

| Package | Type | 3.13 Status | Notes |
|---|---|---|---|
| `python-rtmidi 1.5.8` | C extension | **No cp313 wheel** — build from source | `requires_python >= 3.8`; sdist available. Must be tested. Last release Nov 2023. |
| `JACK-Client 0.5.5` | CFFI / pure | ✅ Clean | `requires_python >= 3.7` |
| `mido 1.3.3` | Pure Python | ✅ Clean | `requires_python ~= 3.7` |
| `python-osc 1.9.3` | Pure Python | ✅ (verify) | Pinned; latest is `1.10.2`. Unpin and upgrade. |
| `slurp-graph 0.1.0` | Pure Python | ✅ Clean | `requires_python >= 3.12` — explicitly supports 3.13. |
| `python3-systemd` (apt) | System pkg | ✅ Aligns | Trixie package requires `python3 (>= 3.13~)` — perfect match. |
| `python3-pyossia` (apt) | System pkg | ✅ Aligns | Tied to system Python; aligns on Trixie. |
| `cuemsutils 0.1.0rc4` | Internal | ⚠️ Unknown | rc4 not published on PyPI (latest public: 0.0.9). Must be built/published for 3.13 before any CI can succeed. **Organizational blocker, independent of Python version.** |

### 3.2 First Step: Validate `python-rtmidi` Source Build

Before committing to 3.13, verify that `python-rtmidi` builds from source against the 3.13 C API:

```sh
pyenv install 3.13.x
pyenv local 3.13.x
pip install python-rtmidi --no-binary :all:
```

If this fails, options are:
- Open an upstream issue / PR on `SpotlightKid/python-rtmidi`.
- Patch the C extension locally (it wraps the RtMidi C++ library; 3.13 C API changes are well-documented).
- Pin to a future `python-rtmidi >= 1.5.9` that adds cp313 wheels, once released.

### 3.3 Required File Changes

| File | Change |
|---|---|
| `.python-version` | `3.11.9` → `3.13.x` |
| `pyproject.toml` — `python` | `^3.11` → `^3.13` |
| `pyproject.toml` — `[tool.black] target-version` | `["py310"]` → `["py313"]` |
| `pyproject.toml` — classifiers | Add `Programming Language :: Python :: 3.13` |
| `pyproject.toml` — `python-osc` | Unpin from `1.9.3`; use `>=1.9.3` or upgrade to `1.10.2` |
| `debian/control` | `python3 (>= 3.11)` → `python3 (>= 3.13)` |
| `debian/rules` | Parameterize all `python3.11` path references (see §4.1) |
| `.github/workflows/ci.yml` | `python-version: "3.11"` ×2 → `"3.13"` |
| `.github/workflows/pypi-publish.yml` | `"3.11"` → `"3.13"` |
| `.github/workflows/gh-pages.yml` | `"3.11"` → `"3.13"` |
| `poetry.lock` | Regenerate: `poetry lock` |

---

## 4. Dual-Distribution Strategy (Bookworm + Trixie)

Bookworm enters LTS on 2026-06-10 (today) with support until 2028-06-30. Maintaining `.deb` packages for both distributions from a single codebase and single branch is fully achievable via GitHub Actions.

### 4.1 Parameterize `debian/rules` (prerequisite for everything)

Add at the top of `debian/rules`:

```makefile
PYVER := $(shell python3 -c "import sys; print('{}.{}'.format(sys.version_info.major, sys.version_info.minor))")
```

Replace every occurrence of `python3.11` in that file with `python$(PYVER)`.

When `dpkg-buildpackage` runs inside a Bookworm container (system Python 3.11) it produces `python3.11` paths. Inside a Trixie container (Python 3.13) it produces `python3.13` paths. Zero branch divergence required.

### 4.2 Matrix Docker Builds in GitHub Actions

```yaml
jobs:
  build-deb:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        distro: [bookworm, trixie]
        include:
          - distro: bookworm
            python_constraint: "^3.11"
          - distro: trixie
            python_constraint: "^3.13"
    container:
      image: debian:${{ matrix.distro }}
    steps:
      - uses: actions/checkout@v4

      - name: Install build dependencies
        run: |
          apt-get update -qq
          apt-get install -y --no-install-recommends \
            debhelper dh-virtualenv devscripts \
            python3-all python3-dev python3-pip \
            libjack-jackd2-dev python3-systemd python3-pyossia

      - name: Set changelog distribution
        run: dch --local ~${{ matrix.distro }} --distribution ${{ matrix.distro }} "CI build"

      - name: Build package
        run: dpkg-buildpackage -us -uc -b

      - name: Upload artifact
        uses: actions/upload-artifact@v4
        with:
          name: deb-${{ matrix.distro }}
          path: ../*.deb
```

Each matrix leg is independent: the container's system Python determines which `python3.x` paths appear in the installed package.

**Note on `pyproject.toml`:** If the Bookworm build requires `python = "^3.11"` and the Trixie build requires `^3.13`, and both are built from the same commit, the constraint must be broad enough to cover both (e.g. `>=3.11`). Alternatively, maintain the Bookworm build on a long-lived `stable/bookworm` branch with its own narrower constraint. The simpler option is `>=3.11,<3.14` in `pyproject.toml` for the dual-support window, then tighten to `^3.13` once Bookworm support is dropped.

### 4.3 GitHub Pages apt Repository (reprepro)

Host a signed Debian repository on GitHub Pages so users can use `apt install cuems-engine`.

**`apt/conf/distributions`:**
```
Codename: bookworm
Components: main
Architectures: amd64 arm64
SignWith: <gpg-key-id>

Codename: trixie
Components: main
Architectures: amd64 arm64
SignWith: <gpg-key-id>
```

**Release workflow step:**
```yaml
- name: Add to apt repository
  run: reprepro -b apt includedeb ${{ matrix.distro }} path/to/*.deb

- name: Deploy to GitHub Pages
  uses: JamesIves/github-pages-deploy-action@v4
  with:
    folder: apt
    target-folder: apt
    clean: false
```

**End-user install:**
```sh
curl -fsSL https://stagesoft.github.io/cuems-engine/apt/cuems.gpg \
  | sudo tee /etc/apt/keyrings/cuems.gpg > /dev/null
echo "deb [signed-by=/etc/apt/keyrings/cuems.gpg] \
  https://stagesoft.github.io/cuems-engine/apt bookworm main" \
  | sudo tee /etc/apt/sources.list.d/cuems.list
sudo apt update && sudo apt install cuems-engine
```

Trixie users substitute `bookworm` with `trixie`.

**GPG signing is mandatory** for a usable apt repository. Store the private key as a GitHub Actions secret; publish the public key in the Pages site.

**Watch out for:** `dh-virtualenv` version differences between Bookworm and Trixie may produce subtle behaviour differences. Test both matrix legs independently before publishing to the apt repository.

---

## 5. Long-term Maintainability Notes

### Threading and GIL

The engine uses threads extensively across 20+ source files (Player, NodesHub,
MtcListener, AsyncCommsThread, CueHandler, BaseEngine, etc.). Python 3.13
introduced the experimental free-threaded mode (PEP 703, `python3.13t` binary —
optional GIL removal). Real-time audio/MIDI engines are precisely the workload
that benefits. No action needed now, but being on 3.13 keeps this path open
without a mid-lifecycle version jump.

### `cuemsutils` Publishing Gap

The installed dev version is `0.1.0rc4` but the latest published version on PyPI
is `0.0.9`. Any CI environment or fresh deployment that cannot reach the internal
build will fall back to an incompatible version. Resolving this (publish the rc
to PyPI or a private index) is a prerequisite for any Python version migration,
because `poetry lock` regeneration will fail or produce incorrect results.

### Python 3.13 vs Trixie LTS EOL Mismatch

- Python 3.13 upstream EOL: **October 2029**
- Trixie LTS EOL: **June 2030**

There is an ~8-month window where Trixie is still LTS-supported but upstream
CPython 3.13 has dropped security patches. Debian's LTS team will backport CVEs
independently during this period — standard Debian practice — but direct
comparison against `python.org` advisories becomes unreliable after October 2029.

---

## 6. Support Horizon and Next Migration Trigger

| Milestone | Date |
|---|---|
| Trixie released (stable) | 2026-06-10 ← now |
| Bookworm enters LTS | 2026-06-10 ← now |
| Drop Bookworm support (LTS expires) | 2028-06-30 |
| Forky (Debian 14) expected stable | ~2028 |
| **Next Python version migration** (3.13 → ~3.15/3.16) | **Plan 2027, execute 2028** |
| Python 3.13 upstream EOL | 2029-10 |
| Trixie LTS fully EOL | 2030-06-30 |

Forky is currently in testing. Based on the ~2-year Debian cadence and Python's
October annual releases, Forky will likely ship Python **3.15** (freeze ~mid-2027)
or **3.16** (if delayed to early 2028). Begin ecosystem readiness checks for
that version in 2027 — particularly for any native extensions (`python-rtmidi`
successor, JACK bindings) and for whatever system Python is frozen into Forky.

---

## 7. Ordered Action List

1. **Publish `cuemsutils 0.1.0rc4` to PyPI** (or internal index). Unblocks all subsequent steps.
2. **Test `python-rtmidi` source build on 3.13** (`pip install python-rtmidi --no-binary :all:` under pyenv 3.13). Document result.
3. **Parameterize `debian/rules`** — replace all `python3.11` literals with `python$(PYVER)`.
4. **Broaden `pyproject.toml` Python constraint** to `>=3.11,<3.14` for the dual-distribution window.
5. **Update `[tool.black] target-version`** from `["py310"]` to `["py311"]` now, `["py313"]` once Trixie-only.
6. **Unpin `python-osc`** from `1.9.3`; upgrade to `1.10.2`.
7. **Add matrix Docker build workflow** to `.github/workflows/` targeting both Bookworm and Trixie.
8. **Set up GPG key** and `reprepro`-based apt repository structure on `gh-pages`.
9. **Wire release workflow** to build both `.deb` packages and publish to the apt repository.
10. **After Bookworm LTS drops (2028-06-30):** tighten constraint to `^3.13`, remove Bookworm matrix leg, update all CI to single `python-version: "3.13"`.
