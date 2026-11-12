#!/usr/bin/env bash
# Shared runtime for the server installation. Credentials live inside this project.
autoresearch_root=/root/autodl-tmp/yzb/autoresearch
export CODEX_HOME="$autoresearch_root/.cache/codex"
export CODEX_CLI="${AUTORESEARCH_CODEX_CLI:-$autoresearch_root/.tools/codex/bin/codex}"
export CODEX_USE_USER_CONFIG=1
export CODEX_IGNORE_USER_CONFIG=0
export AUTORESEARCH_CONNECTION_PROXY=1
export CODEX_MODEL="${CODEX_MODEL:-gpt-6-astra}"
export CODEX_REASONING_EFFORT="${CODEX_REASONING_EFFORT:-medium}"
export PIP_CACHE_DIR="$autoresearch_root/.cache/pip"
export XDG_CACHE_HOME="$autoresearch_root/.cache"
export TMPDIR="$autoresearch_root/assets/tmp"
export PATH="$autoresearch_root/.conda-env/bin:$autoresearch_root/deployment/tools:$PATH"
export LATEX_COMPILER="$autoresearch_root/deployment/tools/tectonic"
export NO_PROXY="localhost,127.0.0.1${NO_PROXY:+,$NO_PROXY}"
mkdir -p "$CODEX_HOME" "$TMPDIR" "$PIP_CACHE_DIR"
chmod 700 "$CODEX_HOME"
