<!--
SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
SPDX-License-Identifier: GPL-3.0-or-later
-->

# UR-4 — `Uuid` equals and hashes like `str` but cannot be ordered

**From** cuems-engine feature 008, 2026-09-29, cuems-utils @ `2a88a7c`.

**Observed.** `cuemsutils.tools.Uuid.Uuid` defines `__eq__`/`__hash__` compatible with its string but
no `__lt__` (no `functools.total_ordering`). The typed node map decodes every uuid4 node id as a
`Uuid`, so any `sorted()` over node ids raises.

**Reproduction.**
```python
from cuemsutils.tools.Uuid import Uuid
sorted([Uuid("3f2b8c1e-5d4a-4b6e-9c7f-1a2b3c4d5e6f"), Uuid("9a8b7c6d-1e2f-4a3b-8c4d-5e6f7a8b9c0d")])
# TypeError: '<' not supported between instances of 'Uuid' and 'Uuid'
```

**Expected.** A total ordering consistent with the string form.

**Impact here.** Pre-rc7 engines crash in `cluster_status` (`sorted(adopted)`) and in the load-time
cluster resolution on any map the current library loads (captured:
`evidence/failing-first-fr009a-cluster-status.txt`, `failing-first-fr026-cluster-identity.txt`).

**Workaround taken.** rc7 sorts with `key=id_str` and renders ids as text at every egress
(`cuemsengine/tools/ids.py`, `ControllerEngine._sorted_ids`). The report stands for consumers
without that fix.

**Status upstream.** cuems-utils 012's draft spec (untracked, 2026-09-29) plans this as FR-029 /
assumption 5 ("sortability is provided by giving the identity type an ordering").
