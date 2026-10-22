<!--
SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
SPDX-License-Identifier: GPL-3.0-or-later
-->

# debian/rules audit after the merge (T055)

Merged tree at `781e4bb`-descendant HEAD. Every item the merge had to preserve, quoted from the file. **No merge defect found.**

| Item | Where | Quoted |
|---|---|---|
| #14 isolated build venv | `debian/rules:15-16` | `export PIP_IGNORE_INSTALLED=1` · `export PYTHONNOUSERSITE=1` |
| #14 rtmidi vendoring check | `debian/rules:29-32` | `test -f debian/cuems-engine/usr/lib/cuems/lib/python3.11/site-packages/rtmidi/__init__.py \|\| { echo "ERROR: python-rtmidi was not vendored into the venv"; exit 1; }` |
| #15 `cffi-gen-src` strip | `debian/rules:68` | `find debian/cuems-engine/usr/lib/cuems/bin -name "cffi-gen-src" -delete` |
| #16 renamed mock wrappers | `debian/rules:38-43` | `install -m 755 debian/mock-scripts/cuems-audioplayer … /usr/bin/cuems-audioplayer` · `install -m 755 debian/mock-scripts/cuems-dmxplayer … /usr/bin/cuems-dmxplayer` |
| #16 mock `Conflicts:` and description | `debian/control:58-61` | `Conflicts: cuems-audioplayer, cuems-dmxplayer` · `Mock replacement binaries for cuems-audioplayer, jack-volume, cuems-dmxplayer and videocomposer.` |
| #16 postinst path text | `debian/cuems-engine-mock.postinst:54` | `Mock wrappers installed to /usr/bin/: cuems-audioplayer, jack-volume, cuems-dmxplayer` |
| #17 SPDX header | `debian/control:1-3`, `debian/rules:2-4` | `# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL` · `# SPDX-License-Identifier: GPL-3.0-or-later` · `# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>` |
| 016's venv `home = /usr/bin` | not a line of `rules` | The engine's `rules` deletes the venv's `pyvenv.cfg` from the package (`debian/rules` `override_dh_fixperms`: `rm -f debian/cuems-engine/usr/lib/cuems/pyvenv.cfg`; cuems-utils owns `/usr/lib/cuems`). The interpreter check is therefore made on the venv `dh_virtualenv` creates, before that deletion, by `tools/bookworm-build.sh`: see `bookworm-build.md` (T056) |

Also confirmed: `Depends` keep the 016 values (`cuems-utils (>= 0.1.1)`, `(<< 0.1.2~)`, `cuems-common (>= 1.3.1~)`,
`libmtcmaster (>= 0.0.2-0)`; mock: `cuems-engine (>= 0.1.1)`), and `grep -nE "0\.1\.0rc17|>= 1\.0\.0\)|0\.1\.0rc2\)" debian/control` is empty.
