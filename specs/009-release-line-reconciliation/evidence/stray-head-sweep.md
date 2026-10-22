<!--
SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Stray-head sweep (T004)

Method: quickstart §1 loop over `refs/remotes/origin` and `refs/tags`, `git rev-list --count HEAD..<ref>`,
2026-10-22 @ `aa0ffe6`. A ref with unabsorbed commits gets exactly one verdict.

| Ref | Tip | Unabsorbed | Reachable from bookworm / rc_1 | Verdict | Reason |
|---|---|---|---|---|---|
| `origin/fix/node-output-maps-ignore-inputs` | `35cbe78` | 82 | no / no | **merge-by-sha** | #22, FR-006 (T020) |
| `origin/fix/mock-players-jack-ready` | `d50ee4b` | 82 | no / no | **merge-by-sha** | #23, FR-006 (T022) |
| `origin/feat/mock-nodeconf` | `5a1811c` | 85 | no / no | **sequenced-after-nodeconf** | #24, FR-007; structure in C5 (T065) |
| `origin/debian/mock-nodeconf-dropin` | `3c11c60` | 120 | no / no | **sequenced-after-nodeconf** | #24 drop-in, FR-007 |
| `v0.1.0rc5-6` (and `rc5-2`, `rc5-3`) | `56dc89e` | 83 | no / no | **ancestry-only** | hotfix line, code equivalent on rc_1; FR-008 (T023, T026) |
| `origin/hotfix/rc5-2-prearm`, `rc5-4-video-loop-wrap`, `rc5-5-audio-ready-gate`, `rc5-6-orphan-kill` | | 64–83 | no / no | **ancestry-only** | ancestors of `v0.1.0rc5-6`; covered by its `-s ours` merge |
| `origin/integ/rc6-3-node-adoption` | `363b92a` | 107 | no / no | **excluded** | integration scratch branch; its content is the reviewed rc6-3 line (FR-009) |
| `origin/gh-pages` | `84185ab` | 29 | no / no | **excluded** | published coverage badge, not source (FR-009) |
| `archive/*` (12 refs), `origin/2ppo`, `origin/docker`, `origin/engine-server`, `origin/nodeconf`, `origin/server`, `origin/osc_no_bool` | | 1–15 | no / no | **excluded** | retired experiments, tagged `archive/` (FR-009) |
| `origin/debian/bookworm` (`3108b4f`) | | 128 | yes / no | merged in T008 | the release line |
| `origin/rc_1` (`06f733a`) | | 90 | no / yes | merged in T018 | ancestry (FR-004 last row) |
| `origin/release/0.1.0rc6-2…rc6-6`, `origin/feat/stop-project-actioncue`, `origin/fix/*` (868–869 ids), `pre-*-merge`, `v0.1.0rc6-1…rc6-6` | | | **yes / —** | **verified ancestors of bookworm** | absorbed by T008 |
| `origin/fix/debian-cffi-gen-src`, `origin/fix/debian-rules-isolated-build-venv` | `dd723a0`, `83f3ff0` | 23, 20 | yes / no | verified ancestors of bookworm | #14, #15 |
| `origin/dependabot/*`, `origin/chore/*`, others behind HEAD | | 0 | | n/a | nothing unabsorbed |

New since the spec: `origin/release/0.1.0rc6-6`, `pre-release-0.1.0rc6-6-merge`, `v0.1.0rc6-6`,
`origin/fix/869fh8kef-node-unload` (`af27553`) — all ancestors of bookworm `3108b4f` and (the fix branch)
of rc_1. No new stray head.

## Hand-off update (T069)

Re-run at hand-off: the same 22 refs have unabsorbed commits and the verdicts above stand. `origin/fix/node-output-maps-ignore-inputs`,
`origin/fix/mock-players-jack-ready`, `v0.1.0rc5-2/-3/-6`, `origin/hotfix/rc5-*`, `origin/debian/bookworm`, `origin/rc_1`,
`origin/release/*`, `origin/fix/*` and the `pre-*-merge` / `v0.1.0rc6-*` tags are now ancestors of HEAD. See `remeasure-handoff.md`.
