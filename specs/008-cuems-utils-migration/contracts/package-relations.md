# Contract — package relations and the upgrade order

## `debian/control` — `Package: cuems-engine`, `Depends:`

```
         cuems-utils (>= 0.1.0rc16),
         cuems-utils (<< 0.1.1~),
         cuems-common (>= 1.3.0-23~),
```

with a comment in `cuems-common`'s style stating: the `cuems-utils` pair is the release gate (C7);
the `cuems-common` floor exists to inherit its `Breaks: cuems-nodeconf (<< 0.1.0-8)` — the engine
reads `node_role` and a pre-`0.1.0-8` nodeconf writes `<node_type>`. No `Breaks:` of the engine's
own (clarify).

## `pyproject.toml:41`

```
cuemsutils = ">=0.1.0rc16,<0.1.1"
```

`poetry.lock` is **not** regenerated on this branch (clarify Q3, R7).

## Version bump — the tag's coordination point (FR-019a)

**Single source: `src/cuemsengine/__init__.py` `__version__`** — the value a human edits. The
other three are copies, kept equal by `tests/test_version_single_source.py` (FR-019b).
`pyproject.toml` keeps a literal only because Poetry 2.4 refuses a dynamic version in package mode.

| File | Before | After |
|---|---|---|
| `src/cuemsengine/__init__.py:5` `__version__` — **source** | `0.1.0rc2` | `0.1.0rc3` |
| `pyproject.toml` `version` (`:7`) — copy | `0.1.0rc2` | `0.1.0rc3` |
| `CHANGELOG.md` | top entry `## v0.1.0rc2 — 2026-05-19` | new top entry `## v0.1.0rc3 — UNRELEASED` |
| `debian/changelog` | top `0.1.0rc2-3` (bookworm) | new top `cuems-engine (0.1.0rc3-1) UNRELEASED; urgency=medium` |

`xml-refactor-merge-candidate` is cut on the commit that carries this bump, once every consumer flow
has landed (D27). `UNRELEASED` is replaced by a date and distribution only at release. No
`debian/NEWS` file.

## `CHANGELOG.md` — the `v0.1.0rc3 — UNRELEASED` entry

Opening summary paragraph, then the file's existing `### Added` / `### Changed` / `### Removed`
sections for Groups 1–6, plus an **`### Upgrade notes`** section that states, in this order:

1. **Upgrade every node host before the controller.**
2. Why: the controller's library converts show scripts to version 2 and deploys them to nodes
   **at show load**; a node on an older library cannot read them. Nodes upgraded first read
   version-1 documents fine.
3. The documents the deploy ships and their schema versions: `script.xml` **2**,
   `mappings.xml` 1, `settings.xml` 1.

## `cuems-relations` hand-off (`handoff-relations-release-order.md`, this directory)

Draft text for a release-procedure section in `../cuems-relations`, carrying items 1–3 above plus
the FR-023a note on `Plans/phase2-engine-late-binding.md` R3. **Not committed from this feature.**
