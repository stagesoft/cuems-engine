<!--
SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
SPDX-License-Identifier: GPL-3.0-or-later
-->

# UR-8 — prompt for `cuems-utils` feature 012's clarification pass

**From**: `cuems-engine` feature 008 (`specs/008-cuems-utils-migration/`, spec FR-019d, FR-027,
FR-029, M19–M21), 2026-09-29. **Measured against** `cuems-utils` `feat/xml-refactor` @ `996617f`
and `cuems-engine` `feat/xml-refactor` @ `27b27f5` (+ docs). Re-measure before relying on a line
number — both trees move.

**Use**: paste the block below into a fresh agent session in `../cuems-utils`, at the point where
feature 012 (uuid4 convergence) runs `/speckit.specify` or `/speckit.clarify`. It adds four
questions to 012's clarification pass and one statement to its migration guide. It does **not**
ask 012 to change anything in `cuems-engine`.

---

```
You are working in cuems-utils on feature 012 — uuid4 convergence — at or after its
/speckit.specify step. A consumer, cuems-engine, has measured how 012 lands on it and asks for
four decisions to be taken in 012's clarification pass, plus one line in 012's migration guide.
Treat everything below as input to /speckit.clarify, not as decisions already made. Do not
reopen the settled ones: §9's decisions 1–4 (uuid4 everywhere, minting through
cuemsutils.tools.Uuid, re-mint by the upgrade machinery, no frontend endpoint), D1–D36, Q14.
Do not edit cuems-engine from here.

READ FIRST (in this repository):
  specs/planning/etc-cuems-first-install.md                 §9 and §10 — the convergence and
                                                            the re-mint procedure
  specs/planning/etc-cuems-first-install-execution.md       "Feature 012" — scope and the
                                                            2026-09-29 readiness re-measure
  src/cuemsutils/tools/Uuid.py                              the Uuid class
  src/cuemsutils/xml/adapters.py:112-142                    _UuidAdapter.decode — lenient
  src/cuemsutils/tools/identity_check.py                    SENTINEL, NOT PROVISIONED
  src/cuemsutils/xml/schemas/settings.xsd:66                <uuid> is cms:NonEmptyString

WHAT THE CONSUMER MEASURED (cuems-engine, 2026-09-29):

  M-a  The library hands the engine two types for one kind of value. A node uuid in
       network_map.xml decodes to Uuid when it is a uuid4 and stays the raw str otherwise
       (_UuidAdapter's leniency); the node's OWN uuid comes from settings.xml, typed
       NonEmptyString, so ConfigManager.node_conf["uuid"] and ConfigManager.node_uuid are
       always str. After 012 narrows network_map's UuidType, every map uuid is a Uuid and the
       own uuid is still a str.
  M-b  Uuid equals and hashes like its str, but defines no ordering, no slicing, no len, no
       split: sorted() over Uuids raises TypeError. cuems-engine's cluster_status reply —
       a contract relayed to cuems-editor — returns sorted(adopted); today's field (uuid1/uuid5,
       so all str) never hits it, a re-minted cluster always will. The engine's rc7 fixes this
       (ids converted with str() at every egress), but ONLY rc7 has the fix.
  M-c  The engine mirrors _UuidAdapter.decode (uuid4 -> Uuid, anything else stays str, empty ->
       None) in its own helper, because the decoder lives in cuemsutils.xml, which consumers
       may not import (Q14). Mirroring library leniency in a consumer is the kind of copy
       FR-030a-i warns about.
  M-d  On a node whose settings.xml carries the NOT PROVISIONED sentinel (the nil uuid, feature
       011), ConfigManager(load_all=True) raises "Node with uuid 00000000-… not found".
       ConfigManager(load_all=False).node_uuid reads it without raising, so the engine's rc7
       checks it against cuemsutils.tools.identity_check.SENTINEL before the full load and says
       "NOT PROVISIONED — run cuems-init-node". identity_check declares no __all__, so whether
       SENTINEL is public surface is unstated.
  M-e  The engine derives a project's node set from output_name[:36]. A stale pre-re-mint
       prefix — §10.2's trap, schema-valid because output_name is a NameStringType — therefore
       shows up in cuems-engine's cluster_warning broadcast as a "missing" node. That is an
       operator-visible detector of an incomplete re-mint that §10.6 does not yet list.

THE FOUR QUESTIONS FOR /speckit.clarify:

  Q1  Does 012 type settings.xml's Settings/node/uuid so the library delivers it as Uuid?
      It cannot simply reuse the narrowed UuidType: the nil uuid must stay valid there as
      011's NOT PROVISIONED sentinel. Options to weigh:
        (a) a settings-specific type, uuid4 OR the nil sentinel, decoded through the same
            adapter — uuid4 -> Uuid, sentinel -> its str (or a named constant); 
        (b) keep NonEmptyString (status quo) — consumers keep converting the own uuid
            themselves;
        (c) something else the spec finds.
      Consequence to state either way: ConfigManager.node_uuid's return type. If it becomes
      Uuid, run a consumer census first — cuems-engine sends node_uuid as an OSC "s" argument
      (NodeEngine.py:443 -> GradientClient.py:51) and slices it nowhere after rc7, but the other
      readers (cuems-editor, cuems-nodeconf, cuems-power-bridge, cuems-common tools) are
      unmeasured. A Uuid where a str was is FR-030a-ii's silent class if anything slices,
      sorts or concatenates it.

  Q2  Does 012 publish an id-coercion helper — the public face of _UuidAdapter.decode
      (uuid4 -> Uuid, other non-empty str unchanged, empty -> None) — in cuemsutils.tools?
      If yes, cuems-engine deletes its mirror (M-c) in a follow-up. If no, record why, so the
      mirror is a known, accepted copy rather than drift waiting to happen.

  Q3  Does Uuid gain a total ordering (e.g. __lt__ on the str form, with functools.total_ordering)?
      That removes M-b's TypeError for every consumer at once. Weigh against keeping Uuid
      deliberately minimal; cuems-engine's rc7 sorts with key=str either way, so this is for
      the consumers that have not been fixed.

  Q4  Is cuemsutils.tools.identity_check.SENTINEL public surface (M-d)? If yes, say so — an
      __all__ in identity_check, or a re-export somewhere stable. If no, name the public
      constant a consumer should compare against.

ONE STATEMENT FOR 012's MIGRATION GUIDE (not a question — decided on the consumer side,
cuems-engine FR-019d, and agreed for the coordinated release):

  The node re-mint ships in the SAME upgrade as cuems-engine 0.1.0rc7 and never runs under an
  older engine. A re-minted network_map.xml hands the engine Uuid node ids; pre-rc7
  cluster_status cannot sort them (M-b). Stop order in §10.4 is unchanged; add the engine
  version to its precondition list.

  Optionally, add M-e to §10.6's verification steps: after a re-mint, load each project on the
  controller and check cuems-engine's cluster_warning — a non-empty "missing" list naming an
  old uuid is a script the re-mint's reach did not cover.

OUT OF SCOPE for this prompt: the re-mint's reach into the project library, --check (010
T035–T037), script_file_name discovery, §10.7's hardware confirmation — 012's own work, already
in its brief. cuems-engine's hardcoded "script.xml" (BaseEngine.py:505) is recorded separately
as NOTE-012-script-filename for that reach question.

Record each answer in 012's spec Clarifications with the consequence for consumers, and file
the consumer census (Q1) as a task if Q1 changes node_uuid's type.
```
