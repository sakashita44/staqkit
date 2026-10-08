#!/usr/bin/env bash
# ホスト環境の初期セットアップ
set -euo pipefail
uv sync --dev
uv run pre-commit install --hook-type pre-commit --hook-type pre-push
