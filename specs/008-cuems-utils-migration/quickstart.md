# Quickstart — verifying 008-cuems-utils-migration

Run from the repository root. **Do not run `poetry install` or `poetry lock`** during this feature:
the lock pins rc14 (after the `rc_1` merge) and would replace the editable `../cuems-utils` (FR-017a). Record the
environment (`evidence/baseline-environment.md`'s table) with every captured run.

```bash
export SPECIFY_FEATURE=008-cuems-utils-migration   # spec-kit scripts reject the branch name
E=specs/008-cuems-utils-migration/evidence
```

## 0. Environment sanity

```bash
poetry run python -c "import cuemsutils; print(cuemsutils.__version__, cuemsutils.__file__)"
# expect: 0.1.0rc16 /disk/Projects/StageLab/cuems-utils/src/cuemsutils/__init__.py
```

## 1. Fixture sequence (FR-002) — no engine change in steps 1–2

```bash
# step 1: network_map fixture -> node_role, with the owning tool
poetry run python ../cuems-common/usr/bin/cuems-migrate-network-map dev/test_xml_files/network_map.xml
#   (positional path, converts in place — argparse at :206-208; run under the venv, not system python3)
poetry run pytest -q -p no:cacheprovider > $E/step1-network-map-converted.txt 2>&1
# expect red; every failure attributed in $E/step1-attribution.md to one of:
#   FR-003 sites 1-2 (controller not found on a map that has one)
#   FR-007 (script load: version-1 document rejected)            <- M9
#   step 2's settings fixture

# step 2: settings fixture -> version 2
poetry run python -m cuemsutils.xml.convert_documents dev/test_xml_files/settings.xml
poetry run pytest -q -p no:cacheprovider > $E/step2-settings-converted.txt 2>&1
# gate: every remaining failure is a named failing-first test. Anything else blocks implement.
```

Record each tool's exact invocation and output in the step file.

## 2. Exit criteria

| SC | Command | Pass |
|---|---|---|
| 001 | `grep -rn 'node_type\|NodeType\.' src/` | no output. Exempt, by name, reason "not shipped": `dev/network_map.xml`, `dev/CuemsEngine_old.py` |
| 002 | `ls $E/*failing-first*` | one file per site, each naming the value it failed on |
| 003 | `grep -rnE 'cuemsutils\.(xml\|config)' src/` and `poetry run pytest tests/test_public_surface.py` | no output; green |
| 004 | `grep -rn 'get_nodes_by_adoption\|_adopted_uuids_from_network_map\|find_hosts' src/ tests/ \| grep -v tests/test_public_surface.py` | no output (the guard's ban list names them by design) |
| 005 | `sed -n 41p pyproject.toml; grep -n 'cuems-utils\|cuems-common' debian/control` | ranges as in `contracts/package-relations.md`; lock re-lock recorded **not performed** until rc16 publishes |
| 006 | `poetry run pytest -q -p no:cacheprovider > $E/final-suite.txt` | green; counts recorded beside the post-merge baseline (28 F / 7 E / 831 P) with retirements from `$E/test-retirements.md` |
| 007 | load + GO a v1 and a v2 `script.xml` (below) | both recorded |
| 008 | `sed -n '1,/^## v0.1.0rc2/p' CHANGELOG.md`; `poetry run pytest tests/test_version_single_source.py`; `ls specs/008-cuems-utils-migration/handoff-relations-release-order.md` | `v0.1.0rc7 — UNRELEASED` on top with upgrade notes, then rc6…rc3, then rc2 untouched; `__version__` `0.1.0rc7`; drift test green; `git diff 27b27f5 -- debian/changelog` empty; hand-off exists |
| 009 | `$E/not-performed.md` | every hardware/cluster item listed, performed or **not performed** |
| 010 | `poetry run pytest -q -rw -p no:cacheprovider 2>&1 \| grep -iE 'deprecat.*cuemsutils\|cuemsutils.*deprecat'` | no output (other libraries' deprecations are out of scope) |
| 011 | `grep -rn 'CTimecode(cue.media.duration)' src/` | no output |
| 012 | `poetry run pytest tests/test_ids.py tests/test_cluster_identity.py tests/test_identity_sweep.py`; `$E/identity-audit.md`; research R14's uuid-literal scan | green; every audit hit resolved or justified; all literals uuid4 except FR-027's named cases |

## 3. SC-007 — v1 and v2 show load

```bash
cp -r dev/test_xml_files/projects/complex_test dev/test_xml_files/projects/complex_test_v2
poetry run python -m cuemsutils.xml.convert_documents dev/test_xml_files/projects/complex_test_v2/script.xml
```

Then the project-load tests parametrized over both projects; on a rig, load each from the editor
and GO the first cue, or record **not performed**.

## 4. Cluster items (usually not performable on a dev box)

- US4 scenario 2: old-library node + new-library controller, deploy + load → expect node refusal.
- US3 scenario 2/3: `dpkg -i` against `cuems-utils` 0.1.1 / nodeconf < 0.1.0-8 → expect refusal.

Each either performed with output captured, or listed in `$E/not-performed.md` with the reason.
