# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
"""The rig-row test knobs are inert without CUEMS_TEST_KNOBS=1 (869ejxng3 K14)."""

import pytest

from cuemsengine.tools import test_knobs


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for n in (
        "CUEMS_TEST_KNOBS",
        "CUEMS_TEST_DROP_OSC",
        "CUEMS_TEST_PROBE_BUDGET_S",
        "CUEMS_TEST_FORCE_PERIOD",
    ):
        monkeypatch.delenv(n, raising=False)
    test_knobs.reset_for_tests()
    yield
    test_knobs.reset_for_tests()


def test_inert_without_the_master_switch(monkeypatch):
    monkeypatch.setenv("CUEMS_TEST_DROP_OSC", "/loop:1")
    monkeypatch.setenv("CUEMS_TEST_PROBE_BUDGET_S", "0.5")
    monkeypatch.setenv("CUEMS_TEST_FORCE_PERIOD", "abc:1:2")
    assert not test_knobs.drop_osc("/loop")
    assert test_knobs.probe_budget_s(15.0) == 15.0
    assert test_knobs.forced_period("abcdef") is None


def test_drop_osc_counts_per_path(monkeypatch):
    monkeypatch.setenv("CUEMS_TEST_KNOBS", "1")
    monkeypatch.setenv("CUEMS_TEST_DROP_OSC", "/loop:2,/offset_i:1")
    assert [test_knobs.drop_osc("/loop") for _ in range(3)] == [False, True, False]
    assert test_knobs.drop_osc("/offset_i")
    assert not test_knobs.drop_osc("/offset_i")
    assert not test_knobs.drop_osc("/mtcfollow")
    assert not test_knobs.drop_osc(None)


def test_budget_and_forced_period(monkeypatch):
    monkeypatch.setenv("CUEMS_TEST_KNOBS", "1")
    monkeypatch.setenv("CUEMS_TEST_PROBE_BUDGET_S", "0.25")
    monkeypatch.setenv("CUEMS_TEST_FORCE_PERIOD", "4f2a:96000:48000")
    assert test_knobs.probe_budget_s(15.0) == 0.25
    assert test_knobs.forced_period("4f2a1234") == (96000, 48000)
    assert test_knobs.forced_period("9999") is None
    monkeypatch.setenv("CUEMS_TEST_PROBE_BUDGET_S", "x")
    assert test_knobs.probe_budget_s(15.0) == 15.0


def test_announce_names_the_active_knobs(monkeypatch, caplog):
    monkeypatch.setenv("CUEMS_TEST_KNOBS", "1")
    monkeypatch.setenv("CUEMS_TEST_PROBE_BUDGET_S", "1")
    seen = []
    monkeypatch.setattr(test_knobs.Logger, "warning", lambda m, *a, **k: seen.append(m))
    test_knobs.announce()
    assert len(seen) == 1 and "CUEMS_TEST_PROBE_BUDGET_S=1" in seen[0]
    seen.clear()
    monkeypatch.delenv("CUEMS_TEST_KNOBS")
    test_knobs.announce()
    assert seen == []
