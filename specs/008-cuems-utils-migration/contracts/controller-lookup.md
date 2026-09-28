# Contract — controller-IP fallback from the node map

`BaseEngine._controller_ip_from_map() -> str` — the fallback `set_controller_ip` uses when
`controller.local` does not resolve to a usable address (`BaseEngine.py:354`).

| Map state | Returns / raises | Log |
|---|---|---|
| no `cm` or empty map | `AttributeError("No network map found")` (unchanged) | — |
| empty `node_list` | `ValueError("No nodes found in network map")` (unchanged) | — |
| no node with `node_role == NodeRole.controller` | `ValueError("No controller node found in network map")` (unchanged) | — |
| exactly one controller, `ip` set | its `ip` | — |
| one controller, no `ip` | `ValueError("Controller node in network map has no <ip>")` (unchanged) | — |
| **>1 controller** | the **first** controller's `ip`, in map order | **error**, one entry, listing every controller as `uuid=… ip=…` (FR-005a) |

A map still in the retired vocabulary never reaches this method: the library refuses it at load
(`SchemaError`, *"still carries the retired `<node_type>` element"*). The negative test for "no
controller" MUST therefore use a **current-vocabulary** map with only `node_role=node` entries —
not a pre-007 map, which would now fail for a different reason (00-runnable-flow.md §7).
