<!--
SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Bookworm build of both debs (T056, T057, FR-034)

`../cuems-utils/specs/016-coordinated-minor-bump/tools/bookworm-build.sh`, unchanged, arguments only
(`UTILS=` a clean scratch clone of `../cuems-utils` checked out at the candidate tag commit `4b336cd`, because the
sibling's working tree is dirty and the script refuses a dirty one; `OUT=`, `WORK=` in the scratch directory).
Raw script output: `bookworm-build-raw.txt`. Nothing was published.

Built at engine commit `3ada95d` (the tree after T055; the script reads tracked files and reports a dirty flag, none
was set). The first attempt exited 1 inside the chroot step with no error in `mmdebstrap.log`; a repeat of the same
command succeeded in 86 s, and a bare `mmdebstrap` smoke run was fine. It is recorded here rather than explained.

| Check | Result |
|---|---|
| Chroot | Debian 12 bookworm, python3 3.11.2, dh-virtualenv 1.2.2-1.3, debhelper 13.11.4 |
| Passes | `pass1 OK`, `build OK` |
| `cuems-engine_0.1.1-1_all.deb` | `dpkg-deb -I`: `Version: 0.1.1-1`; `Depends: cuems-utils (>= 0.1.1), cuems-utils (<< 0.1.2~), cuems-common (>= 1.3.1~), python3 (>= 3.11), python3-pyossia (>= 2.0.0-rc6+124+cuems3), libmtcmaster (>= 0.0.2-0), python3-systemd (>= 235), python3-packaging` |
| `cuems-engine-mock_0.1.1-1_all.deb` | `Version: 0.1.1-1`; `Depends: cuems-engine (>= 0.1.1)`; `Conflicts: cuems-audioplayer, cuems-dmxplayer` |
| Venv interpreter | `pyvenv.cfg: home = /usr/bin` (read from the venv before `override_dh_fixperms` deletes it) |
| rtmidi vendored | `./usr/lib/cuems/lib/python3.11/site-packages/rtmidi/__init__.py` present in the engine deb |
| `cffi-gen-src` | `dpkg -c … \| grep -c cffi-gen-src` → 0 |
| CACHEDIR.TAG | `dpkg -c <cuems-engine deb> \| grep CACHEDIR \|\| echo absent` → **absent**; also absent from the mock deb |

## T057: CACHEDIR.TAG

`/usr/lib/cuems/CACHEDIR.TAG` is **absent** in both debs. **Nothing to strip; no test or `debian/rules` change** (FR-034,
accepted default Q2). X-3 in the cuems-utils report records this result.
