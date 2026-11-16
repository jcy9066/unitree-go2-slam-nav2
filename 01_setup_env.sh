#!/usr/bin/env bash
# Validate go2_nav2 first; create or request consent before correcting an existing environment.
# All installation configuration comes from environment.json.
set -Eeuo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
BOOTSTRAP_PYTHON="${GO2_BOOTSTRAP_PYTHON:-/usr/bin/python3}"
[[ -x "$BOOTSTRAP_PYTHON" ]] || {
    echo 'ERROR: Python bootstrap interpreter missing; set GO2_BOOTSTRAP_PYTHON.' >&2
    exit 1
}
# The bootstrap imports only the standard library. Conda itself is already installed.
exec env -u PYTHONHOME -u PYTHONPATH \
    "$BOOTSTRAP_PYTHON" "$SCRIPT_DIR/scripts/environment.py" "$@"
