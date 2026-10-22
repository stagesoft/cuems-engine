<!--
SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Hotfix line rc5-2…rc5-6: equivalence to `rc_1` (T023, FR-008)

`v0.1.0rc5-6` (`56dc89e`, tip `69e91e4`) is on neither `debian/bookworm` nor `rc_1`. This records that every
one of its code commits is already in HEAD through an `rc_1` commit, so the `-s ours` merge of T026 records
ancestry and loses nothing. Measured on `781e4bb` (HEAD after #22/#23).

## Code commits → their `rc_1` commit (all ancestors of HEAD)

| Hotfix commit | What | `rc_1` commit | Same change? |
|---|---|---|---|
| `951503d` | resolve GO_mtc from the controller's shipped anchor (869f79ecc) | `7b35ccf` | same subject |
| `7bccee8` | undo a PreArm thread's arms after a STOP | `8803dfe` | same subject |
| `cf5421f` | one arm in flight per cue id; a waiter arms the cue itself | `f391675` | same subject |
| `68b09a0` | publish or abandon: an arm whose epoch moved is never published | `4fc6d08` | same subject |
| `5509d87` | PreArm and ReArm threads never disarm; they carry the spawner's epoch | `0f7fb17` | same subject |
| `6eb827f` | a GO that cannot arm its cue skips it and advances the pointer | `2e96b1c` | same subject |
| `092d99f` | the skip line tells a slow arm from a failed one; dead `reset_armed_cues()` dropped | `ecafa23` | **different subject**: `ecafa23` is "code-review findings on the publish-or-abandon change". Checked by content: `NodeEngine.go_script` has `was_in_flight = CUE_HANDLER.describe_arm_in_flight(...)`, `_skip_unarmed_cue(..., was_in_flight)` and the text "the arm it waited on did not deliver the cue in time"; `CueHandler.reset_armed_cues` no longer exists |
| `2d8facc` | say whether a GO waited for an arm in progress or fell back (869fbyjzx) | `58869e6` | same subject |
| `24e8054` | docs(audio): known limit and plan B of the ready gate | `ee3b060` | same subject |
| `929fdc0` | an orphan sweep never aborts its caller (869evtdf7) | `674aefb` | same subject |
| `47b06b5` | sweep only own-user processes of the known binaries | `32dae0d` | same subject |

## Test commits marked `+` by `git cherry`

| Hotfix commit | `rc_1` commit |
|---|---|
| `bde95ed` test: an arm belongs to the STOP/load epoch (red) | `0ea216a` |
| `2eacdb9` test: no background thread disarms after the fact (red) | `e3e9b34` |
| `b9136aa` test: a GO that cannot arm its cue skips it (red) | `f5cf3fd` |
| `98dfe9f` test: the skip line must tell a slow arm from a failed one (red) | no commit with that subject; the test `test_an_arm_that_finished_just_too_late_is_not_reported_as_failed` is in `tests/test_node_engine.py:1111` (its `rc_1` home is the code-review commit `ecafa23`'s tree) |

## Changelog and release commits marked `+`

`f623efe`, `4cf0527`, `9a02a19` (rc5-2), `d7e9832` (rc5-3), `98e69dc` (rc5-4), `9e94da2` (rc5-5), `632b9ca`
(rc5-6) and the release commit `69e91e4`. They carry no code. Their text is the five `debian/changelog` entries
`0.1.0rc5-2 … 0.1.0rc5-6`, copied verbatim by T025. These are the only things in the hotfix line that were
**not** already present.

## `git cherry -v HEAD v0.1.0rc5-6`, verbatim

```
- 1331f3fa97ddf985f61d6b4bb611538b2e28818b test(engine): go_script must ship its own GO instant, not the raw value (red)
- 8dc6d241836ee4fdcd02f630e93b9d97a9ab706a fix(cues): controller ships the GO anchor inside the GO command (869f79ecc)
- 40e8d8988d38a1c99b29a5383331b407abbca52e test(engine): node resolves the GO anchor from the controller, not raw MTC (red)
+ 951503d2998f1092e8913e9178696f6ade445f30 fix(cues): resolve GO_mtc from the controller's shipped anchor (869f79ecc)
- 96250a86cddad8b7f4d210e17b24e3c8a1fff15e test(players): connect_player_to_outputs must log its success path (red)
- d9018a43845771667500a919f44ccce3952696f8 feat(players): log JACK port-registration elapsed time on success (869f79ecc)
- a5a6f91f21357c66891c1c6825282d5623b91e96 test(cues): _arm_ahead must treat non-local cues as transparent (red)
- 9b42a15435d30d69b1eb955b3d9706969bf4bb03 fix(cues): _arm_ahead skips non-local cues, returns what it newly armed (869f79ecc)
- 5b8b8d20f0e59844c92bf631400c6f43f489893a test(cues): _arm_ahead needs a cooperative abort and a per-type carve-out (red)
- 07779c48f260f7de76a82e399cc16c9882fb4cf5 fix(cues): _arm_ahead gains should_continue and skip_arming_types (869f79ecc)
- 3c7a922e42872e5932703256417f12af72a58855 test(engine): setnextcue's lookahead must run off the command lock (red)
- 0371eb206678e2ea43465dfcb8e0c066256f6460 fix(cues): setnextcue's lookahead runs on a PreArm background thread (869f79ecc)
- e3204a3e552ac27cc96c5c4a868c560bcb265bac test(engine): a dead controller MTC must not become every node's GO anchor (red)
- c7816d56b9123b0c6b2233a3ad39313a0976fc2a fix(engine): only a live controller MTC reading becomes the GO anchor (869f79ecc)
- ab3541c7698c320818cdbc0705478b73aea03e38 test(cues): the audio carve-out must reach arm()'s own recursion (red)
- 6e70b538dd3e317c9d3f1be6d38845cd79ff524f fix(cues): the audio carve-out reaches arm()'s own recursion (869f79ecc)
- 6e9068f9110437a947701558f83267c818bd5e21 test(cues): the PreArm walk must govern arm()'s recursion too (red)
- d35cd1fcf56fc2c6bf74bec710b0b5409883512b fix(cues): the PreArm walk governs arm()'s own recursion (869f79ecc)
- f0653e6087db894e82a8a1e52a7a2693994c66e3 test(engine): PreArm must pre-arm audio too (red)
- 037cc8c5a9230b54b95dd652227a09c6dd012047 fix(cues): PreArm pre-arms audio like any other local cue (869f79ecc)
- 7de2e0e62a755d346f0688c2cbee9dba349b3f99 test(engine): a GO that advances a node's pointer with nothing local must pre-arm its next segment (red)
- 354c7eced7f406390390e420dceff0596d961a13 fix(engine): pre-arm a node's next segment when a GO advances its pointer with nothing local
+ f623efe97e99850df8b33e72c1b68cc667ba3ae6 changelog: 0.1.0rc5-2 -- rc5 hotfix: 869f79ecc backport + node pre-arm on pointer advance
- 2980722d4ef4e5803aa6462bf44c75130cf4c852 test(engine): the advance pre-arm must arm off run_command's _command_lock (red)
- a0d2f7d6dda8664ff44b8f238cf049f461a9c7eb fix(engine): arm the advance pre-arm target on the PreArm thread, not under _command_lock
- 8e2b8094b96554a516e5cbb5a2cb59624a7e40c2 style(tests): black test_controller_commands.py (869f79ecc backport)
+ 4cf05271afb47b287ea8e0c839743fb77d9124f0 changelog: 0.1.0rc5-2 -- advance pre-arm arms off _command_lock
- 12ef47a634f6563549ab882081c5d14392fd9959 test(engine): a STOP during an advance pre-arm must undo what it armed (red)
+ 7bccee8e4857cf1f600a69334ecfd7d4f72b9681 fix(engine): undo a PreArm thread's arms after a STOP, and guard the target's recursion
+ 9a02a1931c7bdcfb2dcbb177dce9cbf5372c2655 changelog: 0.1.0rc5-2 -- PreArm undoes its arms after a STOP
- 5b20546eb1a8a4fbe51d9f24790cc858994e858e test(engine): one arm in flight per cue id, and a waiter that arms the cue itself (red)
+ cf5421f7af93a6e51859b16f7227441e0d6e6241 fix(engine): one arm in flight per cue id; a waiter arms the cue itself if the arm it waited on failed
+ bde95ed902d988d13adc7ac0a9b31a8c0c3b4eb2 test(engine): an arm belongs to the STOP/load epoch of its request -- publish or abandon (red)
+ 68b09a0d3a2e18bc24f6827b62761c944ca86007 fix(engine): publish or abandon -- an arm whose STOP/load epoch moved is never published
+ 2eacdb937f43693d0e5995ef5a49d617d6f76b24 test(engine): no background thread disarms after the fact; spawners capture the arm epoch (red)
+ 5509d87170461df891d040b33c8f5d01393496d2 fix(engine): PreArm and ReArm threads never disarm; they carry the epoch their spawner captured
- 1b6fd1faae7933dc387e73f4a17310701991bfbe test(engine): the JACK port wait must end when the player process is dead (red)
- 83a3be88642a0bce08ca3117c64dcae4f1d16f29 fix(engine): stop waiting for the JACK ports of a player whose process has exited
+ b9136aa7d313b7c060dc7d880803664e7d577c27 test(engine): a GO that cannot arm its cue skips it, advances the pointer and says so (red)
+ 6eb827f676442438343345673a71d724c532bd2d fix(engine): a GO that cannot arm its cue skips it, advances the pointer and logs it
+ 98dfe9fff63ac532af74dc6cf09048938fd64477 test(engine): the skip line must tell a slow arm from a failed one (red)
+ 092d99fb387b8c6208e5c4dbd2d6a8475a875a49 fix(engine): the skip line tells a slow arm from a failed one; drop the dead reset_armed_cues()
+ d7e98320e64e633360606cf831fe16be57250ac3 changelog: 0.1.0rc5-3 -- publish or abandon; supersedes rc5-2
- b81f3dbf70cbe26343542981a164370af18ee554 fix(video): only enable videocomposer wraparound for cues that repeat (869fa89uh)
+ 98e69dc615bdae687956b43b04fa1039c8c71e06 changelog: 0.1.0rc5-4 -- play-once video cues no longer wrap to frame 0 (869fa89uh)
- 289069b2f66d2094a0d12825a5eefceb105e9831 test(audio): wire a player only once it reports RUNNING; check and repair its wiring at GO edge by edge; honest arm-wait log lines (869fbyjzx) (red)
- 11ca816541fd34dad0e236e98c158c8253bf5a5c fix(audio): wire an audio player only once it reports RUNNING (869fbyjzx)
- fa062652434d1e9925a8320503f5e8871d2c1deb fix(audio): check and repair a player's wiring at GO edge by edge (869fbyjzx, 869fcvz85)
+ 2d8facc09c05933d9c6f91c0ce74d9636f2ed915 fix(arm): say whether a GO waited for an arm in progress or fell back (869fbyjzx)
- c80abb2b4d41dbf914031a14286c01c251350e38 docs: audio wiring waits for the player's RUNNING line and repairs edge by edge at GO (869fbyjzx)
+ 24e8054c0b4d5eb1f2930119493ba1b690c3fe97 docs(audio): state the known limit and plan B of the ready gate (869fbyjzx)
+ 9e94da2f684431cc19238665cdd412815f7d6f08 changelog: 0.1.0rc5-5 -- audio wiring waits for the player's RUNNING line; edge-by-edge GO repair (869fbyjzx, 869fcvz85)
- e2df7e2bd9f28abc304c8097b3177f9babe9eeb9 fix(audio): review fixes for the ready gate (869fbyjzx)
- d7d59401a14f6724b82d3f3a39abe1acfc7dd725 style: black (869fbyjzx)
- 1e755b66db54eef623f5ca1ef67045576c4793e2 test(orphan-kill): sweeps never abort a load and match only own players (869evtdf7) (red)
+ 929fdc0342c9633b39fdb9ca75f1b2532df2d71c fix(orphan-kill): an orphan sweep never aborts its caller (869evtdf7)
+ 47b06b5155dad2f686b6bcdf46b0b078ad5ca005 fix(orphan-kill): sweep only own-user processes of the known binaries (869evtdf7)
- 68866b7089f40b9ece348fbd471b9b80a8863bd0 fix(comms): log the command callback traceback (869evtdf7)
- 97ab855744791972bcc745b0976d0812c85483e1 fix(load): the zombie JACK client cleanup never aborts a load (869evtdf7)
- 92221371711265a55340d2a7005c1684c21f418b docs(orphan-kill): sweeps never abort a load and depend on the binary name (869evtdf7)
+ 632b9ca879429867a00a73d4da91311806ff4a25 changelog: 0.1.0rc5-6 -- orphan sweeps never abort a project load (869evtdf7)
+ 69e91e45f60edfabaf7d63ece026fd720c69f9e9 release: cuems-engine 0.1.0rc5-6 (with 0.1.0rc5-5)
```

Every `-` line is patch-equivalent to a commit in HEAD. Every `+` line is accounted for above:
23 in all: 11 code commits mapped to `rc_1`, 4 tests mapped (3) or located by name (1), 8 changelog/release
commits that T025 absorbs as text. **No `+` commit lacks an equivalent**, so FR-008 allows the `-s ours` merge.
