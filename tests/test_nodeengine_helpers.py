# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>
"""Unit tests for NodeEngine module-level helpers.

Covers _append_output_latency_flag across all combinations of
(args, output_latency_ms) that can arise from /etc/cuems/settings.xml:

  - args: non-empty string (audioplayer's `-w -1`), empty string,
    None (empty <args/> element decoded by xmlschema)
  - output_latency_ms: int (explicit override), 'auto', None (absent key)

Also exercises the full spawn-argv construction path used by
AudioPlayer / DmxPlayer to guarantee the flag lands at the right
position in the subprocess argv — closing the "audioplayer not
observed live" gap from the 2026-04-23 Phase-5 manual test.
"""

import sys
from unittest.mock import Mock

# Mirror the import shim used by sibling tests
sys.modules.setdefault("cuemsutils.tools.Osc_nodes_hub", Mock())

from cuemsengine.NodeEngine import _append_output_latency_flag


class TestAppendOutputLatencyFlag:
    """_append_output_latency_flag: args string × output_latency_ms value."""

    def test_audioplayer_shape_int(self):
        """audioplayer: args='-w -1', int value → both concatenated."""
        result = _append_output_latency_flag("-w -1", {"output_latency_ms": 42})
        assert result == "-w -1 --output-latency-ms 42"

    def test_dmxplayer_shape_empty_args_int(self):
        """
        dmxplayer: <args></args> decodes to None + int → no literal 'None'.
        """
        result = _append_output_latency_flag(None, {"output_latency_ms": 35})
        assert result == "--output-latency-ms 35"
        assert "None" not in result

    def test_empty_string_args_int(self):
        """Empty-string args behaves like None."""
        result = _append_output_latency_flag("", {"output_latency_ms": 42})
        assert result == "--output-latency-ms 42"

    def test_auto_suppresses_flag(self):
        """'auto' → don't emit the flag; args returned unchanged."""
        result = _append_output_latency_flag("-w -1", {"output_latency_ms": "auto"})
        assert result == "-w -1"
        assert "--output-latency-ms" not in result

    def test_absent_key_suppresses_flag(self):
        """Missing key → don't emit the flag."""
        result = _append_output_latency_flag("-w -1", {})
        assert result == "-w -1"

    def test_none_args_auto(self):
        """None args + 'auto' → empty string, no flag."""
        assert _append_output_latency_flag(None, {"output_latency_ms": "auto"}) == ""

    def test_none_args_absent(self):
        """None args + absent key → empty string."""
        assert _append_output_latency_flag(None, {}) == ""


class TestSubprocessArgvComposition:
    """End-to-end check: the helper's output survives the AudioPlayer/
    DmxPlayer run() loop that splits args on whitespace into argv.

    Mirrors DmxPlayer.run() and AudioPlayer.run() — both do:
        if self.args:
            for arg in self.args.split():
                process_call_list.append(arg)
    """

    @staticmethod
    def _build_argv(path, args, extras):
        """Replicates the shape of DmxPlayer.run() argv construction."""
        call_list = [path]
        if args:
            for arg in args.split():
                call_list.append(arg)
        call_list.extend(extras)
        return call_list

    def test_audioplayer_argv_with_int_override(self):
        """Full audio spawn argv should include --output-latency-ms 42."""
        args = _append_output_latency_flag("-w -1", {"output_latency_ms": 42})
        argv = self._build_argv("/usr/bin/cuems-audioplayer", args, [])
        assert argv == [
            "/usr/bin/cuems-audioplayer",
            "-w",
            "-1",
            "--output-latency-ms",
            "42",
        ]

    def test_audioplayer_argv_with_auto(self):
        """With 'auto', audio spawn argv has no latency flag."""
        args = _append_output_latency_flag("-w -1", {"output_latency_ms": "auto"})
        argv = self._build_argv("/usr/bin/cuems-audioplayer", args, [])
        assert argv == ["/usr/bin/cuems-audioplayer", "-w", "-1"]
        assert "--output-latency-ms" not in argv

    def test_dmxplayer_argv_with_int_empty_args(self):
        """dmx spawn argv with empty <args/> + int must not carry 'None'."""
        args = _append_output_latency_flag(None, {"output_latency_ms": 35})
        argv = self._build_argv(
            "/usr/bin/cuems-dmxplayer",
            args,
            ["--port", "9000", "--uuid", "abc"],
        )
        assert "None" not in argv
        assert "--output-latency-ms" in argv
        assert argv[argv.index("--output-latency-ms") + 1] == "35"

    def test_dmxplayer_argv_with_absent_key(self):
        """
        dmx with absent output_latency_ms → binary's 35 ms default applies.
        """
        args = _append_output_latency_flag(None, {})
        argv = self._build_argv(
            "/usr/bin/cuems-dmxplayer",
            args,
            ["--port", "9000", "--uuid", "abc"],
        )
        assert argv == [
            "/usr/bin/cuems-dmxplayer",
            "--port",
            "9000",
            "--uuid",
            "abc",
        ]
