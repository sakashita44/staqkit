# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## プロジェクト概要

実験データ解析フレームワーク。解析者の暗黙的な依存（データの意味、パラメータの経緯、処理の前提条件）を明示的に外部化し、再現性と追跡性を構造的に保証する。

設計ドキュメント: `docs/` 配下

- [docs/requirements.md](docs/requirements.md) — 要求定義（設計原則 + 要求I〜VI）
- [docs/architecture.md](docs/architecture.md) — アーキテクチャ（概要・スコープ・概念モデル・設計方針・要求マッピング）
- [docs/directory-layout.md](docs/directory-layout.md) — ディレクトリ構成
- [docs/components/datastore.md](docs/components/datastore.md) — DataStore（識別軸定義・クエリAPI・バリデーション）
- [docs/components/stage.md](docs/components/stage.md) — ステージ（stage.yaml仕様・状態管理・実行モデル・run_meta）
- [docs/components/pipeline-gen.md](docs/components/pipeline-gen.md) — パイプライン生成（dvc.yaml導出・バリデーション）
- [docs/components/cli.md](docs/components/cli.md) — CLI リファレンス（全コマンド一覧）
- [docs/components/external-data.md](docs/components/external-data.md) — 外部データ（DAG間合成・dvc import）
- [docs/toolstack.md](docs/toolstack.md) — ツールスタック

## アーキテクチャ

2層構成。依存方向は **Framework → Core** の一方向のみ（Core は Framework を import しない）。

- **Core Library**（`staqkit.core`）: ドメイン非依存の部品群。axes.yaml 等のプロジェクト固有語彙を知らない。QueryEngine, SchemaValidator, Provenance, DAGBuilder
- **Framework**（`staqkit.framework`）: 規約の強制。Core を組み合わせて stages/, config/ 等の規約を解釈する。DataStore（ファサード）, StageInfo, run_stage, Discovery, Generator
- **CLI**（`staqkit.cli`）: CLI エントリポイント。Framework を呼び出す薄いレイヤー

## 設計原則

- **暗黙依存の外部化**: データの意味・経緯・前提をメタデータとして明示化
- **構造的保証**: 識別軸とスキーマの宣言的定義 → 定義に準拠しないデータは管理下に存在不可
- **不変性と純粋関数性**: 処理ステップは `f(入力データ, パラメータ) → 新データ`
- **データ依存DAG**: 全データ間関係は有向非巡回グラフ

## 開発コマンド

```bash
uv sync                      # 依存インストール
uv run pre-commit install    # フック有効化
uv run pytest                # 全テスト実行
uv run pytest tests/test_foo.py            # 単一ファイル
uv run pytest tests/test_foo.py::test_bar  # 単一テスト
uv run pytest -k "keyword"                 # キーワードで絞り込み
uv run pyright               # 型チェック
```

依存の追加・削除は `uv add` / `uv remove` を使用（pyproject.toml を手書き編集しない）。

## ツール設定

設定ファイルは `.config/` に集約:

- `.config/ruff.toml` — Ruff（lint/format, Python 3.11, line-length 88）
- `.config/.prettierrc` — Prettier（Markdown, YAML, JSON, TOML）
- `.config/.markdownlint.jsonc` — markdownlint
- `pyproject.toml [tool.pyright]` — pyright（standard モード）

## Pull Request

PR作成時は `.github/PULL_REQUEST_TEMPLATE.md` のテンプレートに従う。

## pre-commit フック

コミット時に以下が自動実行される:

- **Prettier** — Markdown, JSON, YAML, TOML のフォーマット
- **Ruff** — Python の lint（`--fix`）+ format
- **markdownlint-cli2** — Markdown lint
- **pre-commit-hooks** — 末尾空白除去、ファイル末尾改行、改行コード LF 統一
