#!/usr/bin/env bash
set -euo pipefail
cd /root/autodl-tmp/yzb/autoresearch
exec .conda-env/bin/python3 deployment/guard.py "$@"
