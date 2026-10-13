#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"
python_bin="${BUAA_PYTHON:-python3}"
if [[ -x "$project_dir/.venv/bin/python" ]]; then
  python_bin="$project_dir/.venv/bin/python"
fi
exec "$python_bin" -m core.service_cli "${1:-status}"
