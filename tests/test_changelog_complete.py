# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>

"""The stable changelog lists every build that ever shipped (contract C3).

0.1.1-1 is the first stable release, so its ``debian/changelog`` must carry the
whole released history of the 0.1.0 pre-releases: every entry of
``origin/debian/bookworm``, of ``origin/rc_1`` and of each ``v0.1.0*`` tag
(the rc5-2..rc5-6 hotfix builds exist only on a tag).

The sources are LIVE git refs, so a build released after this branch was cut
fails the test instead of slipping past it. A repository that lacks a ref
(a shallow checkout, a fresh clone) SKIPS with the missing names: loudly, never
silently green.
"""

import re
import shutil
import subprocess
from functools import cmp_to_key
from pathlib import Path

import pytest

BOOKWORM = "origin/debian/bookworm"
RC_1 = "origin/rc_1"
TAG_PATTERN = "v0.1.0*"
CHANGELOG = "debian/changelog"

HEADER = re.compile(r"^(?P<package>\S+) \((?P<version>[^)]+)\) ", re.MULTILINE)


def git(*args, cwd):
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=False
    )


@pytest.fixture(scope="module")
def repo():
    top = git("rev-parse", "--show-toplevel", cwd=Path(__file__).parent)
    assert top.returncode == 0, top.stderr
    return Path(top.stdout.strip())


def entries(text):
    """``{version: entry text}``, in file order.

    An entry runs from its header line to the line before the next header.
    """
    headers = list(HEADER.finditer(text))
    found = {}
    for position, header in enumerate(headers):
        end = headers[position + 1].start() if position + 1 < len(headers) else None
        found[header.group("version")] = text[header.start() : end]
    return found


def _char_order(char):
    """dpkg's weight of one non-digit character; the end of a run weighs 0."""
    if char == "~":
        return -1
    if char.isalpha():
        return ord(char)
    return ord(char) + 256


def _compare_part(a, b):
    """dpkg's comparison of an upstream version or a revision: -1, 0 or 1."""
    while a or b:
        letters_a, letters_b = re.match(r"\D*", a).group(), re.match(r"\D*", b).group()
        a, b = a[len(letters_a) :], b[len(letters_b) :]
        for position in range(max(len(letters_a), len(letters_b))):
            weight_a = (
                _char_order(letters_a[position]) if position < len(letters_a) else 0
            )
            weight_b = (
                _char_order(letters_b[position]) if position < len(letters_b) else 0
            )
            if weight_a != weight_b:
                return 1 if weight_a > weight_b else -1
        digits_a, digits_b = re.match(r"\d*", a).group(), re.match(r"\d*", b).group()
        a, b = a[len(digits_a) :], b[len(digits_b) :]
        difference = int(digits_a or 0) - int(digits_b or 0)
        if difference:
            return 1 if difference > 0 else -1
    return 0


def compare_versions(a, b):
    """Debian version comparison: -1, 0 or 1. Used when dpkg is not installed."""

    def split(version):
        epoch, _, rest = version.rpartition(":")
        upstream, _, revision = rest.rpartition("-")
        return int(epoch or 0), upstream or rest, revision

    (epoch_a, upstream_a, revision_a), (epoch_b, upstream_b, revision_b) = (
        split(a),
        split(b),
    )
    if epoch_a != epoch_b:
        return 1 if epoch_a > epoch_b else -1
    return _compare_part(upstream_a, upstream_b) or _compare_part(
        revision_a, revision_b
    )


def dpkg_greater(a, b):
    """True when version *a* is strictly newer than *b*."""
    if shutil.which("dpkg"):
        return (
            subprocess.run(["dpkg", "--compare-versions", a, "gt", b]).returncode == 0
        )
    return compare_versions(a, b) > 0


@pytest.fixture(scope="module")
def sources(repo):
    """``{source name: {version: entry}}`` from the live refs, or skip."""
    names = {"bookworm": BOOKWORM, "rc_1": RC_1}
    tags = git("tag", "-l", TAG_PATTERN, cwd=repo).stdout.split()
    missing = [
        ref
        for ref in names.values()
        if git("rev-parse", "--verify", ref, cwd=repo).returncode
    ]
    if not tags:
        missing.append(f"tags {TAG_PATTERN}")
    if missing:
        pytest.skip(f"missing refs: {missing}")

    found = {}
    for name, ref in names.items():
        found[name] = entries(git("show", f"{ref}:{CHANGELOG}", cwd=repo).stdout)
    for tag in sorted(tags):
        shown = git("show", f"{tag}:{CHANGELOG}", cwd=repo)
        if shown.returncode == 0:
            found[tag] = entries(shown.stdout)
    return found


@pytest.fixture(scope="module")
def worktree(repo):
    text = (repo / CHANGELOG).read_text()
    return text, entries(text)


def test_the_top_entry_is_the_stable_release(worktree):
    text, _ = worktree
    assert HEADER.search(text).group("version") == "0.1.1-1"


def test_every_released_version_is_listed(worktree, sources):
    _, listed = worktree
    released = set().union(*(set(found) for found in sources.values()))
    missing = sorted(released - set(listed), key=cmp_to_key(compare_versions))
    assert not missing, f"released builds missing from debian/changelog: {missing}"


def test_released_entries_are_byte_identical_to_their_source(worktree, sources):
    """The first source that carries a version decides its text.

    Order: bookworm, the tags, rc_1: the line the Debian packages shipped from
    comes first.
    """
    _, listed = worktree
    order = ["bookworm", *sorted(n for n in sources if n.startswith("v")), "rc_1"]
    differing = []
    for version in sorted(set().union(*(set(f) for f in sources.values()))):
        if version not in listed:
            continue  # reported by the superset assertion
        owner = next(name for name in order if version in sources[name])
        if listed[version] != sources[owner][version]:
            differing.append(f"{version} (from {owner})")
    assert not differing, f"entries that differ from their source: {differing}"


def test_entries_are_in_descending_version_order(worktree):
    text, _ = worktree
    versions = [h.group("version") for h in HEADER.finditer(text)]
    misordered = [
        (newer, older)
        for newer, older in zip(versions, versions[1:])
        if not dpkg_greater(newer, older)
    ]
    assert not misordered, f"not in descending dpkg order: {misordered}"


def _released_versions(sources):
    return set().union(*(set(found) for found in sources.values()))


def _named_in_changelog_md(version, text):
    """A ``<!-- source: ... <version> ... -->`` comment, or ``(<version>, date)``."""
    token = rf"(?<![0-9A-Za-z.~+:-]){re.escape(version)}(?![0-9A-Za-z.~+:-])"
    for comment in re.findall(r"<!--\s*source:.*?-->", text, flags=re.DOTALL):
        if re.search(token, comment):
            return True
    return re.search(rf"\({re.escape(version)}, \d{{4}}-\d{{2}}-\d{{2}}\)", text)


@pytest.fixture(scope="module")
def changelog_md(repo):
    return (repo / "CHANGELOG.md").read_text()


def test_changelog_md_names_every_released_build(sources, changelog_md):
    missing = sorted(
        (
            v
            for v in _released_versions(sources)
            if not _named_in_changelog_md(v, changelog_md)
        ),
        key=cmp_to_key(compare_versions),
    )
    assert not missing, f"released builds absent from CHANGELOG.md: {missing}"


def test_changelog_md_leads_with_the_stable_release(changelog_md):
    sections = re.split(r"^## (?=v)", changelog_md, flags=re.MULTILINE)[1:]
    assert sections[0].startswith("v0.1.1")
    assert not re.search(r"not (yet )?reconciled", sections[0].lower())


@pytest.mark.parametrize(
    "newer, older",
    [
        ("0.1.1-1", "0.1.0rc6-6"),
        ("0.1.0rc6-6", "0.1.0rc6-5"),
        ("0.1.0rc5-1", "0.1.0rc4-1"),
        ("0.1.0rc2-3", "0.1.0rc2-2"),
        ("0.1.0-1", "0.1.0~rc1-1"),
    ],
)
def test_the_fallback_comparison_agrees_with_dpkg_on_the_history(newer, older):
    assert compare_versions(newer, older) == 1
    assert compare_versions(older, newer) == -1
