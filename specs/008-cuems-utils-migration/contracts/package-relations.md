# Contract — package relations and the upgrade order

## `debian/control` — `Package: cuems-engine`, `Depends:`

```
         cuems-utils (>= 0.1.0rc16),        # was (>= 0.1.0rc4) at :18
         cuems-utils (<< 0.1.1~),
         cuems-common (>= 1.3.0-23~),
```

with a comment in `cuems-common`'s style stating: the `cuems-utils` pair is the release gate (C7);
the `cuems-common` floor exists to inherit its `Breaks: cuems-nodeconf (<< 0.1.0-8)` — the engine
reads `node_role` and a pre-`0.1.0-8` nodeconf writes `<node_type>`. No `Breaks:` of the engine's
own (clarify).

## `pyproject.toml:48` (`>=0.1.0rc13` after the `rc_1` merge)

```
cuemsutils = ">=0.1.0rc16,<0.1.1"
```

`poetry.lock` (at rc14 after the merge) is **not** regenerated on this branch (clarify Q3, R7).

## Version — rc7, and the tag's coordination point (FR-019a/b/c)

**Single source: `src/cuemsengine/__init__.py` `__version__`.** Copies kept equal by
`tests/test_version_single_source.py`: `pyproject.toml:11` and the top `CHANGELOG.md` header.
`pyproject.toml` keeps a literal only because Poetry 2.4 refuses a dynamic version in package mode.

| File | After `rc_1` merge | After this feature |
|---|---|---|
| `src/cuemsengine/__init__.py:5` — **source** | `0.1.0rc2` | `0.1.0rc7` |
| `pyproject.toml:11` — copy | `0.1.0rc2` | `0.1.0rc7` |
| `CHANGELOG.md` top | `## v0.1.0rc2 — 2026-05-19` | `## v0.1.0rc7 — UNRELEASED`, then rc6 … rc3 (backfilled), then rc2 untouched |
| `debian/changelog` | `0.1.0rc2-3` (bookworm) | **unchanged** — versions are cut on `debian/bookworm` when `rc_1` is merged in (M15) |

`xml-refactor-merge-candidate` is cut on the commit that carries the rc7 bump, once every consumer
flow has landed (D27). `UNRELEASED` is replaced by a date only at release. No `debian/NEWS`.

## `CHANGELOG.md` — rc3–rc6 backfill (FR-019c)

| Entry | Header date | Content from |
|---|---|---|
| `## v0.1.0rc6 — 2026-09-28` | `7f6e475` | `git log --no-merges fc8d2bb..956a0f3` (31) + bookworm `0.1.0rc6-1` changelog entry |
| `## v0.1.0rc5 — 2026-08-14` | `8b57710` | `2abf26d..fc8d2bb` (5) + `0.1.0rc5-1` |
| `## v0.1.0rc4 — 2026-08-03` | `15d50b6` | `v0.1.0rc2..2abf26d` (100) + `0.1.0rc4-1` |
| `## v0.1.0rc3 — 2026-04-16` | `30af517` | bookworm's `0.1.0rc3-1`/`-2` changelog entries (`git show 7f6e475:debian/changelog`, lines 105–132) and the first-parent packaging commits up to `30af517` — content derived there, not assumed; one line: *cut from the packaging line before the `v0.1.0rc2` tag (2026-05-19)* |

Style: the rc2 entry's — summary paragraph, `### Added` / `### Changed` / `### Fixed` (or
`Removed`) with `####` topic groups, ClickUp ids kept where the commits carry them.

## `CHANGELOG.md` — the `v0.1.0rc7 — UNRELEASED` entry

Opening summary paragraph, then `### Added` / `### Changed` / `### Removed` sections for Groups 1–7
— `### Changed` MUST include FR-014's `fade_out` → `stop` behaviour change — plus an
**`### Upgrade notes`** section that states, in this order:
1. **Upgrade every node host before the controller.**
2. Why: the controller's library converts show scripts to version 2 and deploys them to nodes
   **at show load**; a node on an older library cannot read them. Nodes upgraded first read
   version-1 documents fine.
3. The documents the deploy ships and their schema versions: `script.xml` **2**,
   `mappings.xml` 1, `settings.xml` 1.
4. **G1 (FR-019d)**: `cuems-utils` 012 and its node re-mint (uuid4 convergence) go out in the
   **same** upgrade as rc7 engines, and the re-mint never runs under an older engine — rc7 requires
   012 (`coerce_identity`), and no pre-rc7 engine has been run against 012 or a re-minted map.
   *(Amended 2026-10-01: the original reason, pre-rc7 `cluster_status` unable to sort `Uuid` node
   ids, no longer holds once 012 orders `Uuid`.)*

## `cuems-relations` hand-off (`handoff-relations-release-order.md`, this directory)

Draft text for a release-procedure section in `../cuems-relations`, carrying items 1–3 above plus
the FR-023a note on `Plans/phase2-engine-late-binding.md` R3. **Not committed from this feature.**
