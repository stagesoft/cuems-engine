# Hand-off to `cuems-relations`: release order for cuems-engine 0.1.0rc7

*Draft for hand-off, not committed to cuems-relations from this feature.*

Source: cuems-engine feature `008-cuems-utils-migration` (branch `feat/xml-refactor`). Proposed as a
release-procedure section in `../cuems-relations`, plus two notes for owners elsewhere.

## Proposed section — "Upgrading to cuems-engine 0.1.0rc7 (cuems-utils 0.1.0rc16)"

1. **Upgrade every node host before the controller.**
2. **Why.** At show load the controller's library converts the show's `script.xml` to schema
   version 2 and deploys it to the nodes. A node still on an older `cuems-utils` cannot read a
   version-2 script, and no package manager sits between the controller's deploy and the node's
   read to stop it. Nodes upgraded first read version-1 documents fine, so node-first is safe in
   both directions.
3. **What the deploy ships, and at which schema version** (`CuemsDeploy._project_files`):

   | Document | Schema | Version |
   |---|---|---|
   | `/projects/<project>/script.xml` | `script` | **2** |
   | `/projects/<project>/mappings.xml` | `project_mappings` | 1 |
   | `/projects/<project>/settings.xml` | `project_settings` | 1 |

   A future bump of `project_mappings` or `project_settings` past 1 puts that document under this
   same node-first rule (constraint C11); whoever makes the bump updates this table and the engine's
   `CHANGELOG.md` upgrade notes.
4. **Release order with `cuems-utils` 012 (G1).** 012's node re-mint (every node converging on a
   uuid4 identity) goes out **in the same upgrade as rc7 engines, and never runs under an older
   engine.** A re-minted map hands the engine `Uuid` node ids; a pre-rc7 engine sorts them in
   `cluster_status` and crashes (`TypeError: '<' not supported between instances of 'Uuid'`).
   `cuems-utils` 012's migration guide is asked to say the same (upstream note UR-8).

Package relations that enforce part of this (`cuems-engine`'s `debian/control`):
`cuems-utils (>= 0.1.0rc16)`, `cuems-utils (<< 0.1.1~)`, `cuems-common (>= 1.3.0-23~)` (the last to
inherit `Breaks: cuems-nodeconf (<< 0.1.0-8)` — the engine reads `<node_role>`). They gate what is
installed on one host; they cannot gate the cross-host order above, which is why it is written down.

## Notes

### FR-023a — `Plans/phase2-engine-late-binding.md:198-204` (R3, split-brain)

R3's decision not to add a dialer-side split-brain guard rests on *"the map's single-`NodeType.master`
invariant already guards (`find_hosts` raises on >1 controller)"*. That guard never ran:
`BaseEngine.find_hosts` had **no caller** in any checkout under `/disk/Projects/StageLab` (re-swept
2026-09-28: code hits zero, documentation only), and against the current library it could not even
start (`AttributeError: 'CuemsNetworkMapType' object has no attribute 'get_nodes_by_adoption'`,
captured in the engine's `evidence/failing-first-site3-4-find-hosts.txt`). rc7 deletes it.

After rc7 the premise is **partly** true: a map with more than one `node_role=controller` node is now
**detected and logged** — one error listing every controller as `uuid=… ip=…`, then the first
controller in map order is used (`BaseEngine._controller_ip_from_map`, FR-005a) — but it is **not
refused**. R3's owner should decide whether logging suffices or a refusal is wanted.

### FR-023 — nodeconf readiness probe (for whoever fixes `cuems-nodeconf`)

cuems-engine `cf5c4ad` (2026-09-04) made `nodelist_modify` refuse instantly when
`/tmp/nodeconf.ipc` does not exist, instead of burning the 15 s IPC timeout. Socket **existence** is
not readiness: the socket appears before nodeconf can serve an adopt, so the probe can report
nodeconf available while an adopt would still fail or stall. The fix belongs in `cuems-nodeconf`
(a readiness signal the engine can check). This feature added no new caller of the probe.
