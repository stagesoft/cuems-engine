# Not performed — 008-cuems-utils-migration

Every verification item that could not be performed on this dev box, with the reason (SC-009).

| Item | Reason | Date |
|---|---|---|
| US3 scenario 2 — `dpkg -i cuems-engine` refused against `cuems-utils` 0.1.1 | No packaging sandbox on this dev box (no sbuild/pbuilder/schroot), and installing the `.deb` on the host would replace the editable setup. **Partial, performed**: the relation arithmetic with `dpkg --compare-versions` — `0.1.0rc15` fails `>= 0.1.0rc16`; `0.1.0rc16`, `0.1.0rc17` pass both bounds; `0.1.1~rc1`, `0.1.1` fail `<< 0.1.1~`. `debian/control` parses with dpkg's `Dpkg::Control::Info` | 2026-09-29 |
| US3 scenario 3 — refusal against `cuems-nodeconf` < 0.1.0-8 through the `cuems-common (>= 1.3.0-23~)` floor | Same (no sandbox). **Partial**: `1.3.0-22` fails `>= 1.3.0-23~`, `1.3.0-23` passes; the `Breaks: cuems-nodeconf (<< 0.1.0-8)` it inherits is in `../cuems-common/debian/control:57` | 2026-09-29 |
| SC-005 re-lock (`poetry lock` against published rc16) | rc16 unpublished — PyPI latest `0.1.0rc14` (`pip index versions cuemsutils --pre`, 2026-09-29). See `ci-red-by-construction.md` | 2026-09-29 |
| US4 scenario 2 — old-library node + new-library controller: deploy and load a show; expect the node to refuse the version-2 `script.xml` | No two-host rig on this dev box (one editable engine against one editable `../cuems-utils`). The expected refusal is the library's own (*newer than this library's current version*), pinned engine-side by `tests/test_read_script.py::test_a_script_newer_than_the_library_is_refused` | 2026-09-29 |
