#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
#
# Checks for a release PR to debian/bookworm (1amfwm7kan4). Run from the root
# of a checkout:
#   release-check.sh tree [HEAD_REF]   the tree equals the rc_1 commit it integrates
#   release-check.sh changelog         debian/changelog parses and matches pyproject.toml
#   release-check.sh deb               inspect the built deb(s) in the parent directory
# Local run of `tree` needs `origin/rc_1` fetched; the workflow does that.
set -euo pipefail

fail() { echo "::error::$*"; exit 1; }

# Print FILE as it is in REV with the lines that legitimately differ in a
# release removed: the version in pyproject.toml, the version and the comment
# header (contributor lines) in src/cuemsengine/__init__.py.
normalised() {
    local rev=$1 file=$2
    case $file in
        pyproject.toml)              git show "$rev:$file" | grep -v '^version = ' || true ;;
        src/cuemsengine/__init__.py) git show "$rev:$file" | grep -v -e '^__version__ = ' -e '^#' || true ;;
        *)                           git show "$rev:$file" ;;
    esac
}

check_tree() {
    local head=${1:-HEAD} base
    git rev-parse --verify -q origin/rc_1 >/dev/null || fail "origin/rc_1 is not fetched"
    # The newest rc_1 commit in the head's history is the one the release merged.
    base=$(git merge-base origin/rc_1 "$head") || fail "$head shares no history with rc_1"
    echo "rc_1 commit integrated by $head: $(git rev-parse --short "$base")"

    local bad=0 f
    # Every file, in either tree, outside debian/ (debian/bookworm owns that).
    while IFS= read -r f; do
        case $f in
            debian/*) continue ;;
            pyproject.toml|src/cuemsengine/__init__.py)
                if ! diff -q <(normalised "$base" "$f" 2>/dev/null) <(normalised "$head" "$f" 2>/dev/null) >/dev/null; then
                    echo "::error file=$f::differs from rc_1 ($base) beyond the version/header lines"
                    bad=1
                fi ;;
            *)
                echo "::error file=$f::differs from rc_1 ($base)"
                bad=1 ;;
        esac
    done < <(git diff --name-only "$base" "$head")
    [ "$bad" = 0 ] || fail "the tree is not rc_1's: a release must only add debian/ and the version"
    echo "OK: the tree equals rc_1 ($(git rev-parse --short "$base")) outside debian/ and the version lines"
}

check_changelog() {
    local deb pyproj
    deb=$(dpkg-parsechangelog -S Version) || fail "debian/changelog does not parse"
    pyproj=$(sed -n 's/^version = "\(.*\)"$/\1/p' pyproject.toml | head -n1)
    [ -n "$pyproj" ] || fail "no version in pyproject.toml"
    echo "changelog: $deb   pyproject.toml: $pyproj"
    [ "${deb%-*}" = "$pyproj" ] || fail "changelog upstream version '${deb%-*}' is not pyproject.toml's '$pyproj'"
    [ "$(dpkg-parsechangelog -S Distribution)" = bookworm ] || fail "changelog distribution is not bookworm"
    echo "OK: debian/changelog is valid and matches pyproject.toml"
}

check_deb() {
    local deb list control
    deb=$(ls ../cuems-engine_*_all.deb 2>/dev/null | head -n1) || true
    [ -n "$deb" ] || fail "no ../cuems-engine_*_all.deb was built"
    echo "deb: $deb"
    list=$(dpkg-deb -c "$deb")
    control=$(dpkg-deb -f "$deb" Depends)
    echo "Depends: $control"
    if grep -q 'usr/lib/cuems/CACHEDIR.TAG$' <<<"$list"; then
        fail "the deb ships usr/lib/cuems/CACHEDIR.TAG (cuems-nodeconf owns it; dpkg refuses the install)"
    fi
    grep -q 'site-packages/rtmidi/__init__.py$' <<<"$list" || fail "rtmidi is not vendored in the venv"
    grep -q 'site-packages/cuemsengine/' <<<"$list" || fail "cuemsengine is not in the venv"
    local dep
    for dep in cuems-utils cuems-common python3-pyossia python3-systemd ffmpeg; do
        grep -q "$dep" <<<"$control" || fail "Depends lost $dep"
    done
    echo "OK: no CACHEDIR.TAG, rtmidi and cuemsengine in the venv, Depends complete"
}

case ${1:-} in
    tree)      shift; check_tree "$@" ;;
    changelog) check_changelog ;;
    deb)       check_deb ;;
    *)         echo "usage: $0 tree [HEAD_REF] | changelog | deb" >&2; exit 2 ;;
esac
