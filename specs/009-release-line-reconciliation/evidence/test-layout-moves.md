<!--
SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Test layout moves (T100–T102, contract C2)

Classification by the rule in `tests/README.md`: **integration** if the test binds or connects a real socket, starts a real
subprocess or player, touches JACK/ALSA or relies on a `sleep` ≥ 0.5 s; **contract** if it asserts a repository or packaging
invariant; everything else **unit**. Every candidate unit file was screened with a grep for `pynng`, `socket`,
`SimpleUDPClient`, `subprocess`, `jack`, `OssiaServer(`, `ThreadingOSCUDPServer`, `Popen` and `sleep(≥0.5)`; the hits were
checked and are listed in the "signal" column.

| File | Directory | Signal |
|---|---|---|
| `test_action_cue` | unit | no real socket, subprocess, JACK or sleep ≥ 0.5 s (screened by grep) |
| `test_arm_inventory` | unit | no real socket, subprocess, JACK or sleep ≥ 0.5 s (screened by grep) |
| `test_arm_publish_gate` | unit | no real socket, subprocess, JACK or sleep ≥ 0.5 s (screened by grep) |
| `test_arm_resilience` | unit | no real socket, subprocess, JACK or sleep ≥ 0.5 s (screened by grep) |
| `test_arm_video_cue_opacity_deploy` | unit | no real socket, subprocess, JACK or sleep ≥ 0.5 s (screened by grep) |
| `test_arm_wait_messages` | unit | no real socket, subprocess, JACK or sleep ≥ 0.5 s (screened by grep) |
| `test_chain_anchoring` | unit | no real socket, subprocess, JACK or sleep ≥ 0.5 s (screened by grep) |
| `test_chain_epoch` | unit | no real socket, subprocess, JACK or sleep ≥ 0.5 s (screened by grep) |
| `test_cluster_identity` | unit | no real socket, subprocess, JACK or sleep ≥ 0.5 s (screened by grep) |
| `test_cluster_status_contract` | unit | no real socket, subprocess, JACK or sleep ≥ 0.5 s (screened by grep) |
| `test_cluster_warning` | unit | no real socket, subprocess, JACK or sleep ≥ 0.5 s (screened by grep) |
| `test_config_ports` | unit | no real socket, subprocess, JACK or sleep ≥ 0.5 s (screened by grep) |
| `test_controller_commands` | unit | no real socket, subprocess, JACK or sleep ≥ 0.5 s (screened by grep) |
| `test_controller_cue_names` | unit | no real socket, subprocess, JACK or sleep ≥ 0.5 s (screened by grep) |
| `test_controller_gating` | unit | no real socket, subprocess, JACK or sleep ≥ 0.5 s (screened by grep) |
| `test_controller_stop_project` | unit | no real socket, subprocess, JACK or sleep ≥ 0.5 s (screened by grep) |
| `test_core_baseengine_controller_ip` | unit | `socket.gethostbyname` patched |
| `test_core_baseengine_status` | unit | no real socket, subprocess, JACK or sleep ≥ 0.5 s (screened by grep) |
| `test_cross_node_follow_controller` | unit | no real socket, subprocess, JACK or sleep ≥ 0.5 s (screened by grep) |
| `test_cross_node_follow_hook` | unit | no real socket, subprocess, JACK or sleep ≥ 0.5 s (screened by grep) |
| `test_cross_node_follow_owner` | unit | no real socket, subprocess, JACK or sleep ≥ 0.5 s (screened by grep) |
| `test_cross_node_follow_receiver` | unit | no real socket, subprocess, JACK or sleep ≥ 0.5 s (screened by grep) |
| `test_cue_media_dimensions` | unit | `subprocess.run` (ffprobe) patched |
| `test_cuems_deploy` | unit | asyncio subprocess mocked (`create_subprocess_exec` patched) |
| `test_cues_dmx` | unit | no real socket, subprocess, JACK or sleep ≥ 0.5 s (screened by grep) |
| `test_dead_videoplayer_removed` | unit | no real socket, subprocess, JACK or sleep ≥ 0.5 s (screened by grep) |
| `test_disarm_video_layers` | unit | no real socket, subprocess, JACK or sleep ≥ 0.5 s (screened by grep) |
| `test_dispatch_reorder` | unit | no real socket, subprocess, JACK or sleep ≥ 0.5 s (screened by grep) |
| `test_display_conf` | unit | no real socket, subprocess, JACK or sleep ≥ 0.5 s (screened by grep) |
| `test_effective_duration` | unit | no real socket, subprocess, JACK or sleep ≥ 0.5 s (screened by grep) |
| `test_enable_rejoin` | unit | no real socket, subprocess, JACK or sleep ≥ 0.5 s (screened by grep) |
| `test_fade_action_handler` | unit | no real socket, subprocess, JACK or sleep ≥ 0.5 s (screened by grep) |
| `test_identity_sweep` | unit | no real socket, subprocess, JACK or sleep ≥ 0.5 s (screened by grep) |
| `test_ids` | unit | no real socket, subprocess, JACK or sleep ≥ 0.5 s (screened by grep) |
| `test_loop_fade_cue` | unit | no real socket, subprocess, JACK or sleep ≥ 0.5 s (screened by grep) |
| `test_loop_rebase` | unit | no real socket, subprocess, JACK or sleep ≥ 0.5 s (screened by grep) |
| `test_loop_video_wraparound` | unit | no real socket, subprocess, JACK or sleep ≥ 0.5 s (screened by grep) |
| `test_media_duration` | unit | no real socket, subprocess, JACK or sleep ≥ 0.5 s (screened by grep) |
| `test_mock_players_jack_ready` | unit | no real socket, subprocess, JACK or sleep ≥ 0.5 s (screened by grep) |
| `test_mtclistener` | unit | no real socket, subprocess, JACK or sleep ≥ 0.5 s (screened by grep) |
| `test_node_comms_mixer` | unit | no real socket, subprocess, JACK or sleep ≥ 0.5 s (screened by grep) |
| `test_node_comms_ping` | unit | no real socket, subprocess, JACK or sleep ≥ 0.5 s (screened by grep) |
| `test_node_engine` | unit | no real socket, subprocess, JACK or sleep ≥ 0.5 s (screened by grep) |
| `test_node_engine_gradient` | unit | no real socket, subprocess, JACK or sleep ≥ 0.5 s (screened by grep) |
| `test_node_engine_load_orphan_eperm` | unit | `subprocess.run` patched |
| `test_node_output_maps` | unit | no real socket, subprocess, JACK or sleep ≥ 0.5 s (screened by grep) |
| `test_node_stop_project` | unit | no real socket, subprocess, JACK or sleep ≥ 0.5 s (screened by grep) |
| `test_node_unload_project` | unit | no real socket, subprocess, JACK or sleep ≥ 0.5 s (screened by grep) |
| `test_nodeengine_helpers` | unit | no real socket, subprocess, JACK or sleep ≥ 0.5 s (screened by grep) |
| `test_nodelist_modify` | unit | no real socket, subprocess, JACK or sleep ≥ 0.5 s (screened by grep) |
| `test_own_media_sizes` | unit | no real socket, subprocess, JACK or sleep ≥ 0.5 s (screened by grep) |
| `test_player_handler_gradient` | unit | no real socket, subprocess, JACK or sleep ≥ 0.5 s (screened by grep) |
| `test_player_handler_mixer_orphan` | unit | `subprocess.run` patched |
| `test_player_handler_orphan_kill` | unit | `subprocess.run` patched |
| `test_player_handler_port_wait_abort` | unit | no real socket, subprocess, JACK or sleep ≥ 0.5 s (screened by grep) |
| `test_players_audiomixer` | unit | `call_subprocess` patched |
| `test_players_dmxplayer` | unit | `call_subprocess` patched |
| `test_players_jackconnectionmanager` | unit | `jack.Client` patched in every test |
| `test_port_handler` | unit | binds real UDP sockets to probe the allocator; kept as unit (accepted default Q10), except the concurrency case |
| `test_read_script` | unit | no real socket, subprocess, JACK or sleep ≥ 0.5 s (screened by grep) |
| `test_reveal_mechanism` | unit | no real socket, subprocess, JACK or sleep ≥ 0.5 s (screened by grep) |
| `test_stop_propagation` | unit | no real socket, subprocess, JACK or sleep ≥ 0.5 s (screened by grep) |
| `test_video_placement_failure` | unit | no real socket, subprocess, JACK or sleep ≥ 0.5 s (screened by grep) |
| `test_video_routing` | unit | no real socket, subprocess, JACK or sleep ≥ 0.5 s (screened by grep) |
| `test_video_unrouted_output` | unit | no real socket, subprocess, JACK or sleep ≥ 0.5 s (screened by grep) |
| `test_comms_nodehub` | integration | real NNG hub/bus sockets |
| `test_core_baseengine` | integration | real BaseEngine with real ports (was marked integration) |
| `test_cpu_usage` | integration | starts real engines and samples CPU (was marked integration) |
| `test_cuems_deploy_integration` | integration | real deploy against a process boundary (was marked integration) |
| `test_gradient_client` | integration | binds a real UDP socket for the gradient transport |
| `test_ossia` | integration | real pyossia/OSCQuery devices and UDP sockets |
| `test_ossia_bundle_support` | integration | real pyossia OSC bundle transport |
| `test_ossia_oscquery` | integration | real OSCQuery server and clients in subprocesses and threads (moved from testdev_ossia_oscquery.py) |
| `test_port_handler_concurrency` | integration | real threads drawing real bindable ports (split from test_port_handler.py, accepted default Q10) |
| `test_project_go` | integration | real engines and GO (was marked integration) |
| `test_project_load` | integration | real engines and the load pipeline (was marked integration) |
| `test_pyossia_osc` | integration | real pyossia OSC over UDP |
| `test_pythonosc` | integration | real python-osc UDP client/server |
| `test_changelog_complete` | contract | asserts debian/changelog and CHANGELOG.md cover every released build |
| `test_default_mappings_valid` | contract | asserts the XML fixtures stay loadable by the library |
| `test_layout` | contract | asserts this layout |
| `test_lock_is_current` | contract | asserts poetry.lock is current (strict xfail until publication) |
| `test_public_surface` | contract | asserts the package's public surface |
| `test_stop_project_xsd` | contract | X-1: the library carries the stop_project value |
| `test_version` | contract | asserts version strings |
| `test_version_single_source` | contract | asserts one version source across files |

Count: 65 unit, 13 integration, 8 contract.

## Collected ids before and after (T102)

`collect-before.txt` (1487 ids) and `collect-after.txt`; outcomes in `outcome-before.txt` / `outcome-after.txt`
(`-m "not slow"`, `--dist loadfile`, libmtc stub). With the `tests/{unit,integration,contract}/` prefix stripped:

- **Same ids**, apart from:
  - `+3` `test_ossia_oscquery.py::*`: the three passing cases moved out of the uncollected `testdev_ossia_oscquery.py` (T086);
  - `+6` `test_layout.py::*`: the new layout test (T089);
  - `test_port_handler.py::test_concurrent_draws_are_distinct` → `test_port_handler_concurrency.py::test_concurrent_draws_are_distinct` (the Q10 split).
- **Outcomes**: every id present in both runs has the same outcome (`PASSED`, or `XFAIL` for the lock test); the added ids all pass.
