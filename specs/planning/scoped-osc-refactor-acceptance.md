<!--
SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
SPDX-License-Identifier: GPL-3.0-or-later
-->

# T064 — On-Hardware Acceptance Verification (node-002)

**Issued by**: gradient-motion-engine spec 007-osc-input-transport  
**Spec ref**: SC-001 (primary user-facing success criterion)  
**Target**: node-002 production node  
**Context version**: gradient-motion-engine v0.3.0 (branch `feat/osc-input-transport`)  
**Date**: 2026-05-13

---

## Background

Phase H of gradient-motion-engine replaces the NNG bus-client inbound transport
with a local UDP OSC listener. The Phase E integration failure on node-002 was
the original motivation for this rewrite: the daemon never received `start_fade`
commands from the NodeEngine because NNG bus0 does not auto-relay between dialers
in a star topology.

The fix is architectural: the NodeEngine now dispatches commands to the daemon
directly over localhost UDP OSC (port 7100) instead of via the NNG bus. The C++
daemon is passive — it only listens and evaluates; it does not dial anything.

This document describes the full prerequisite chain and the acceptance procedure
for declaring Phase H complete on real hardware.

---

## Prerequisites

All three of the following must be in place on node-002 before running this
procedure. They can be installed in any order but all must be active at the same
time.

### 1. gradient-motion-engine v0.3.0 deb installed

Install the rebuilt `.deb` from branch `feat/osc-input-transport`:

```bash
sudo dpkg -i cuems-gradient-motiond_0.3.0-1_amd64.deb
sudo systemctl daemon-reload
```

Verify:

```bash
gradient-motiond --version
# Expected: gradient-motiond 0.3.0

ldd /usr/bin/gradient-motiond | grep -i nng
# Expected: (no output) — spec SC-004

ss -ulnp | grep 7100   # after starting the service
# Expected: daemon bound on 0.0.0.0:7100
```

> **Note on bind address**: liblo 0.32 binds to `0.0.0.0` rather than
> `127.0.0.1` due to a known API limitation. In production, nftables rules
> (from `cuems-common`) restrict the port to loopback-only traffic. Confirm
> the nftables rule is loaded if this is a security concern.

### 2. cuems-common systemd unit updated (T060)

The unit must have been updated per
[`specs/planning/T060-cuems-common-systemd-unit.md`](T060-cuems-common-systemd-unit.md):

```bash
systemctl cat cuems-gradient-motiond | grep -E "nng|avahi|osc-port"
# Must show:  --osc-port $CUEMS_GRADIENT_OSC_PORT  (or --osc-port 7100)
# Must NOT show:  --nng-url
# Must NOT show:  Wants=avahi-daemon
```

### 3. cuems-engine branch `feat/gradient-osc-transport` installed

The NodeEngine must have the companion changes that dispatch over OSC instead of
NNG. Key changes in that branch:

- New `GradientPlayer.py` modeled on `VideoPlayer.py` / `DmxPlayer.py`
- `_handle_fade_action` rewired to dispatch via `GradientPlayer`
- NNG send paths removed from `NodeCommunications`
- cancel-on-STOP and cancel-on-LOAD moved to the NodeEngine (sends
  `/gradient/cancel_all` or `/gradient/cancel_motion` to the daemon)

Verify the correct branch is running:

```bash
sudo systemctl status cuems-node-engine
# Check the active unit/commit hash or package version matches feat/gradient-osc-transport
```

---

## Acceptance Procedure

### Step 1 — Restart all three services

```bash
sudo systemctl restart cuems-controller-engine cuems-node-engine cuems-gradient-motiond
```

Wait ~3 s for services to settle, then tail the daemon journal in a second
terminal:

```bash
journalctl -fu cuems-gradient-motiond
```

**Expected startup log** (with `--log-level info`):

```
gradient-motiond starting
  MIDI port : Midi Through Port-0
  OSC port  : 7100
  Node name : node-002
  Log level : info
  Conf path : /etc/cuems
OscServer bound: UDP 0.0.0.0:7100 (node_name filter active, restrict to lo via nftables)
GradientEngine initialized: OSC port=7100 node=node-002
gradient-motiond running — waiting for signal
```

**No acceptable output** should contain:
- Any reference to `controller.local`
- Any reference to `nng` or `tcp://`
- Any Avahi error or timeout

### Step 2 — Load the fade-test project

In the CUEMS editor UI, open:

```
/opt/cuems_library/projects/fade-test/
```

This is the project used during Phase E: one AudioCue + one FadeCue, configured
as:

| Field | Value |
|---|---|
| Target value | 0 (fade to silence) |
| Duration | 5 000 ms |
| Curve | linear |
| Target | AudioCue on node-002 |

### Step 3 — Press GO

Press GO in the editor. Listen to the audio output.

**Expected behaviour**:

1. Audio fades **smoothly** to silence over 5 seconds. No audible bounce-back
   or jump to full volume at the end.
2. The daemon journal shows the accepted command and per-tick OSC sends:

   ```
   OscServer: accepted /gradient/start_fade motion_id=<id>
   GradientEngine: CANCEL_ALL        ← (only if STOP was pressed)
   ```

   Approximately 100 `/volmaster` OSC ticks should be emitted on the output
   side during a 5 s fade at the default MTC resolution.

3. No reference to `controller.local` anywhere in the daemon log during the
   fade.

4. If STOP is pressed mid-fade, the journal shows:

   ```
   OscServer: accepted /gradient/cancel_all motion_id=
   GradientEngine: CANCEL_ALL
   ```

   And the audio stops cleanly — no continuation of the fade.

### Step 4 — Capture the journal

Capture 100 lines of journal from the daemon covering the fade:

```bash
journalctl -u cuems-gradient-motiond -n 100 --no-pager > /tmp/node002_t064_journal.txt
cat /tmp/node002_t064_journal.txt
```

Attach the output to the PR or paste it in the merge commit message for
traceability. This is the audit trail for **SC-001**.

### Step 5 (optional) — Avahi resilience

```bash
sudo systemctl stop avahi-daemon
sudo systemctl restart cuems-gradient-motiond
journalctl -u cuems-gradient-motiond -n 30
```

Daemon must start cleanly. Re-run the fade-test GO — fade must still work.
This validates **FR-007 / FR-013 / SC-003**.

Restart Avahi when done:

```bash
sudo systemctl start avahi-daemon
```

---

## Pass / Fail Criteria

| Check | Pass condition |
|---|---|
| SC-001 | Audio fades smoothly to silence over 5 s, no bounce |
| SC-001 | Daemon journal shows accepted `start_fade` and ~100 output ticks |
| SC-001 | No `controller.local` in daemon log |
| SC-003 | Daemon starts with Avahi stopped; fade still works |
| SC-004 | `ldd /usr/bin/gradient-motiond \| grep -i nng` returns nothing |
| FR-013 | Unit file has no `Wants=avahi-daemon.service` |

If any check fails, Phase H is **not** complete. File a bug with the journal
output attached.

---

## Development Notes

- **Why `0.0.0.0` and not `127.0.0.1`**: liblo 0.32 does not support binding
  to a specific interface via `lo_server_thread_new_with_proto`; it always
  listens on all interfaces. The loopback restriction is enforced at the OS
  level by nftables rules shipped in `cuems-common`. If those rules are not
  loaded, the daemon is technically reachable from the LAN on port 7100 —
  verify nftables is active before declaring the deployment production-ready.

- **MTC source on node-002**: The fade is time-locked to MIDI Time Code. The
  `gradient-motiond` daemon does not emit ticks itself — it waits for the
  `cuems-node-engine` to drive MTC via the `mtcreceiver` submodule. If MTC
  is not flowing (no `aplaymidi` or hardware MTC), `GradientEngine::onTick()`
  is never called and the fade will be accepted but never progress. Confirm
  that MTC is flowing before testing (check `journalctl -u cuems-node-engine`
  for MTC tick log lines).

- **`--node-name` on node-002**: The daemon's `node_name` filter drops all
  incoming OSC messages whose `node_name` field does not match
  `--node-name`. The NodeEngine must dispatch with the same name. If the
  node is named `node-002` in the CUEMS project, both the daemon's
  `--node-name node-002` and the NodeEngine's `gradient_node_name` config
  must agree.

- **Port 7100 default**: Both the daemon and the NodeEngine's
  `GradientPlayer.py` must target the same port. The default is 7100 on
  both sides. If the unit file sets `CUEMS_GRADIENT_OSC_PORT` to something
  else, ensure `GradientPlayer.py` reads and uses the same value.

- **`kOscFailureThreshold = 5`**: If the NodeEngine dispatches a fade whose
  callback address (the `osc_host:osc_port:osc_path` triplet in the
  `start_fade` message) is not reachable, the daemon retries up to 5 ticks
  then removes the fade and emits a `MotionError`. This is the designed
  behaviour — it prevents silent runaway fades. Check the daemon journal for
  `osc_send_failed` messages if the fade disappears unexpectedly.

---

## Related Spec Artifacts (gradient-motion-engine)

| Artifact | Location |
|---|---|
| Spec SC-001, FR-007, FR-013 | `specs/007-osc-input-transport/spec.md` |
| Full quickstart (§5) | `specs/007-osc-input-transport/quickstart.md` |
| Wire contract | `specs/007-osc-input-transport/contracts/gradient_osc.md` |
| cuems-common unit task | `specs/planning/T060-cuems-common-systemd-unit.md` |
| Dev-host smoke result (reference) | `dev/deploy_tests/results/s007_t034_smoke.txt` |
| Avahi resilience result (reference) | `dev/deploy_tests/results/s007_t065_avahi_resilience.txt` |
