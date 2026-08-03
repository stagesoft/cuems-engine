# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
"""CueHandler.arm() must not propagate a failure to its caller (869ed9wf7 B3).

get_free_port() can now raise ValueError when the port pool is exhausted or
nothing probes bindable — deliberately, so a known-bad port is never handed
out. But _arm_ahead() runs on the GO daemon thread (CueHandler.py:502 and the
post_go == "go_at_end" branch at :707), and it has no except of its own. An
uncaught raise there would kill a *playing* cue's thread before loop_cue(),
skipping its generation-tracked cleanup — far worse than one broken cue.

So arm() logs loudly, leaves the cue unloaded and returns False. go()'s
fallback re-arm then retries it, and raises where an operator can see it if
that fails too.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from cuemsutils.cues import AudioCue

from cuemsengine.cues.CueHandler import CUE_HANDLER


def _armable_cue() -> AudioCue:
    cue = AudioCue()
    cue.enabled = True
    cue.loaded = False
    cue._local = True
    cue._loading = None
    cue._target_object = None
    cue._osc = MagicMock()
    return cue


def test_arm_returns_false_when_port_allocation_fails(caplog):
    """A port failure marks the cue unloaded instead of unwinding the caller."""
    cue = _armable_cue()

    with patch(
        "cuemsengine.cues.CueHandler.arm_cue",
        side_effect=ValueError("No bindable free port found"),
    ):
        result = CUE_HANDLER.arm(cue, init=True)

    assert result is False
    assert cue.loaded is False
    assert "Failed to arm" in caplog.text
    CUE_HANDLER.disarm(cue)


def test_arm_failure_clears_the_loading_sentinel():
    """The finally block must still run, or concurrent arms deadlock on the
    Event that is never set."""
    cue = _armable_cue()

    with patch(
        "cuemsengine.cues.CueHandler.arm_cue",
        side_effect=ValueError("No bindable free port found"),
    ):
        CUE_HANDLER.arm(cue, init=True)

    assert cue._loading is None, "loading sentinel leaked — next arm would hang"
    CUE_HANDLER.disarm(cue)


def test_arm_failure_does_not_arm_the_chain():
    """A cue that failed to arm must not drag its post_go target in with it."""
    cue = _armable_cue()
    target = _armable_cue()
    cue.post_go = "go"
    cue._target_object = target

    with patch(
        "cuemsengine.cues.CueHandler.arm_cue",
        side_effect=ValueError("No bindable free port found"),
    ):
        CUE_HANDLER.arm(cue, init=True)

    assert target.loaded is False
    CUE_HANDLER.disarm(cue)
    CUE_HANDLER.disarm(target)


def test_arm_ahead_survives_a_failing_cue():
    """The actual B3 scenario: _arm_ahead on the GO thread must return
    normally, not raise, when a lookahead cue cannot get a port."""
    first = _armable_cue()
    second = _armable_cue()
    first._target_object = second

    with patch(
        "cuemsengine.cues.CueHandler.arm_cue",
        side_effect=ValueError("No bindable free port found"),
    ):
        CUE_HANDLER._arm_ahead(first)  # must not raise

    assert second.loaded is False
    CUE_HANDLER.disarm(first)
    CUE_HANDLER.disarm(second)


def test_arm_still_succeeds_normally():
    """Guard against the except swallowing a healthy arm."""
    cue = _armable_cue()

    with patch("cuemsengine.cues.CueHandler.arm_cue"):
        result = CUE_HANDLER.arm(cue, init=True)

    assert result is True
    assert cue.loaded is True
    CUE_HANDLER.disarm(cue)
