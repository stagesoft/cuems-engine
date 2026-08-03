#!/bin/bash
# Replace the installed cuemsengine package under /usr/lib/cuems with a symlink
# to the source tree so edits in src/cuems-engine are used by the system.
# Requires sudo (to modify /usr/lib/cuems).
#
# Usage: run from the cuems-engine repo root, or from anywhere with CUEMS_ENGINE_SRC set:
#   ./scripts/link-dev.sh
#   sudo ./scripts/link-dev.sh
#
# To restore the installed package: reinstall the deb (e.g. dpkg -i ...cuems-engine*.deb).

set -e

SITE_PACKAGES="/usr/lib/cuems/lib/python3.11/site-packages"
PACKAGE_NAME="cuemsengine"

if [ -n "$CUEMS_ENGINE_SRC" ]; then
    SOURCE_PKG="$CUEMS_ENGINE_SRC/src/cuemsengine"
else
    # Script is in .../cuems-engine/scripts/; repo root is parent of scripts/
    REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
    SOURCE_PKG="$REPO_ROOT/src/cuemsengine"
fi

if [ ! -d "$SOURCE_PKG" ]; then
    echo "Source package not found: $SOURCE_PKG"
    echo "Set CUEMS_ENGINE_SRC to the cuems-engine repo root, or run this script from the repo."
    exit 1
fi

if [ ! -d "$SITE_PACKAGES" ]; then
    echo "Site-packages not found: $SITE_PACKAGES"
    echo "Install cuems-engine (and cuems-utils) first so /usr/lib/cuems exists."
    exit 1
fi

INSTALLED_PKG="$SITE_PACKAGES/$PACKAGE_NAME"

if [ -L "$INSTALLED_PKG" ]; then
    echo "Already a symlink: $INSTALLED_PKG -> $(readlink "$INSTALLED_PKG")"
    exit 0
fi

if [ -d "$INSTALLED_PKG" ]; then
    echo "Removing installed package directory (will be replaced by symlink)..."
    sudo rm -rf "$INSTALLED_PKG"
fi

echo "Linking $INSTALLED_PKG -> $SOURCE_PKG"
sudo ln -s "$SOURCE_PKG" "$INSTALLED_PKG"
echo "Done. Edits in $(dirname "$SOURCE_PKG") will be used by controller-engine and node-engine."
echo "To restore the installed package, reinstall the cuems-engine deb."
