#!/usr/bin/env bash
set -euo pipefail
cd /root/autodl-tmp/yzb/autoresearch
source deployment/env.sh
exec .conda-env/bin/python3 -u -m workbench --host "${AUTORESEARCH_BIND_HOST:-127.0.0.1}" --port 8760 --workspace /root/autodl-tmp/yzb/autoresearch --data-dir /root/autodl-tmp/yzb/autoresearch/assets/output/workbench
