#!/usr/bin/env bash
# Local compression/restoration only. The operator handles Git pull/commit/push.
set -Eeuo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
BOOTSTRAP_PYTHON="${GO2_BOOTSTRAP_PYTHON:-/usr/bin/python3}"
[[ -x "$BOOTSTRAP_PYTHON" ]] || {
    echo 'ERROR: Python bootstrap missing; set GO2_BOOTSTRAP_PYTHON.' >&2
    exit 1
}
ENV_NAME=$(env -u PYTHONHOME -u PYTHONPATH PYTHONNOUSERSITE=1 "$BOOTSTRAP_PYTHON" -c \
    'import json,sys; print(json.load(open(sys.argv[1]))["conda"]["name"])' \
    "$SCRIPT_DIR/../environment.json")
PYTHON_BIN="$BOOTSTRAP_PYTHON"
if [[ -n ${CONDA_PREFIX:-} && "$(basename -- "$CONDA_PREFIX")" == "$ENV_NAME" ]]; then
    PYTHON_BIN="$CONDA_PREFIX/bin/python"
fi
# Map preparation uses the standard library and zstd; no ROS overlay is loaded.
exec env -u PYTHONHOME -u PYTHONPATH PYTHONNOUSERSITE=1 \
    "$PYTHON_BIN" "$SCRIPT_DIR/map_archives.py" "$@"
