<!--
SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
-->

# Unattended playback: ending or looping a show without an operator

Two recipes for museums, installations and kiosks, where nobody presses STOP.
Both are authored in the project; the engine never decides on its own that a
show is over.

## Why the engine does not stop by itself

When the last cue of the chain ends, the engine keeps `running = yes`,
`armed = yes`, the cues at `100` and timecode running. A GO in that state logs
`No more cues. Press STOP to restart.` and plays nothing. This is **by design**
(Ion, 2026-10-15): a live show is not over when the chain is. Cues the operator
fires by hand (`/gocue`, setnextcue + GO) must stay armed, and the operator
decides when it is over. The `running` flag means *show in progress*, not *a cue
is playing*. If it dropped by itself, a cue fired after the chain ended would be
playing while load, unload and shutdown were all allowed again, which the
"never auto-stop a running project" rule forbids.

So an unattended show says in its own script how it ends, with one of the two
recipes below.

## Recipe 1: play once, then return to armed (the `stop_project` cue)

Use when a visitor's button (power-bridge `/go`, a Shelly input, a Stream Deck)
starts the show and the next press must start it again from the top.

1. In the editor add an **Action** cue after the last media cue and pick
   **Project actions → Stop project** (`stop_project`). It has no target; the
   editor shows a fixed line explaining that it stops the whole project, like
   the STOP button, and that it is **not** the cue action *Stop*.
2. Place it as the **Auto follow** (`post_go = go_at_end`) target of the last
   media cue, with `prewait 0`. It then fires exactly when that media ends,
   on every node, through the follow relay.
3. Leave nothing after it that should play in the same run: the engine breaks
   the chain at the stop cue, and the editor warns ("Cues after this one will
   not play in this run") when a cue follows it.

What happens: every node reveals the cue and reports it to the controller; the
controller runs the operator STOP: `running no`, every cue back to `0`, the
nodes blackout, unload and re-arm, `armed yes`. The next GO starts from the top.
The journal shows, once per stop, on the controller:

```
stop_project cue <uuid> ("<name>") from node <uuid>: stopping the show
STOP command processed - timecode stopped; nodes will re-arm
```

and on each node `stop_project cue <uuid>: notified the controller (run N)`.
Copies from the other nodes are dropped at INFO (`not part of the current run`);
that is expected. A WARNING `no STOP received from the controller in 3 s` means
the controller never acted; the show keeps running, exactly as before.

Notes for integrators:

- **Alternative placement:** inside an Auto continue chain (`post_go = go`) with
  a `prewait` equal to the time from the chain trigger to the wanted stop. The
  stop cue then shows as *playing* from the trigger, for its whole prewait.
- **An "end show" button:** fire the stop cue by hand (`POST /gocue <uuid>` on
  the power-bridge, or setnextcue + GO). It stops the show at the cue's own
  start, so give it `prewait 0`.
- **Rehearsal:** disable the stop cue. Disabled cues are transparent to the
  chain, so the show then ends as it always did, holding `running = yes` until
  someone presses STOP.
- **The re-arm window:** between the stop and `armed yes` the power-bridge
  answers `/go` with `409 not_armed`, like after an operator STOP. A kiosk
  button pressed in that second is ignored; press again.
- **Persistent auto-load:** with `auto_load_persistent=true` the power-bridge
  (from the release that carries this fix) re-drives its project only when the
  engine's load is **empty**. Older bridges read the re-arm window as "reload"
  and, with `auto_play=true`, replayed the show on their own.
- **Versions:** every box of the cluster needs cuems-utils ≥ 0.1.0rc17 (the
  schema value) and the engine release that carries the feature. An older
  utils rejects the whole project at load, visibly ("Load stalled" on the
  controller after 120 s if a node is on the old schema). A utils downgrade
  strands such a project until the stop cue is removed from `cue_script.xml`.

## Recipe 2: loop forever (the `play` loop-back)

Use for an attract loop that runs until a technician presses STOP.

1. Make the last media cue an **Auto follow** (`post_go = go_at_end`) of an
   **Action** cue with **Cue actions → Play** aimed at the **first** cue of the
   show.
2. GO once. At the end of the last cue the play action re-enters the chain
   from the top (`CueHandler.go_from`), on every node, each re-entering its own
   local segment. `running` stays `yes` throughout; the cues cycle `1 → 100 → 1`.
3. An operator STOP ends it and re-arms.

Needs the engine release with the cross-node follow relay (0.1.0rc6-3 or later)
when the first or last cue lives on another node. This recipe predates the
stop cue and is in use in the field; it needs no new software.

## Choosing

| Want | Recipe |
|---|---|
| Visitor button starts it; it must end and wait for the next press | 1, `stop_project` |
| It runs all day until staff stop it | 2, `play` loop-back |
| Operator decides when the show is over (a live show) | neither: the default behaviour |
