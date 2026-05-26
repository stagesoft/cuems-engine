# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>

from cuemsengine import __version__ as version
import re


def is_zero_or_digit(s: str) -> bool:
    if s[0] == "0":
        return len(s) == 1
    return s.isdigit()


def is_alpha_beta_rc(s: str) -> bool:
    p = r"^(?:0|[1-9]\d*)(?:a[1-9]\d*|b[1-9]\d*|rc[1-9]\d*)?$"
    sre = re.match(p, s)
    if sre is None:
        return False
    return sre.span() == (0, len(s))


def test_zero_or_digit():
    assert is_zero_or_digit("0")
    assert is_zero_or_digit("1")
    assert is_zero_or_digit("123")
    assert not is_zero_or_digit("0123")
    assert not is_zero_or_digit("0123a")


def test_alpha_beta_rc():
    assert is_alpha_beta_rc("1a1")
    assert is_alpha_beta_rc("1b1")
    assert is_alpha_beta_rc("1rc1")
    assert is_alpha_beta_rc("0")
    assert is_alpha_beta_rc("1")
    assert not is_alpha_beta_rc("01")
    assert not is_alpha_beta_rc("1a01")
    assert not is_alpha_beta_rc("1a")
    assert not is_alpha_beta_rc("2a0")
    assert not is_alpha_beta_rc("1a1a")
    assert not is_alpha_beta_rc("1b1b")
    assert not is_alpha_beta_rc("1rc1rc")


def test_version():
    version_split = version.split(".")
    assert isinstance(version, str)
    assert len(version) > 0
    assert len(version_split) in (3, 4)
    assert is_zero_or_digit(version_split[0])
    assert is_zero_or_digit(version_split[1])

    if len(version_split) == 4:
        # Allow for a revision (post) number after a dot
        assert is_zero_or_digit(version_split[2])
        assert version_split[3][:4] == "post"
        assert version_split[3][4] != "0"
        assert version_split[3][4:].isdigit()
    else:
        # Allow for a revision (alpha, beta, rc) number without a dot
        assert is_alpha_beta_rc(version_split[2])
