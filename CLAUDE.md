# sard

## プロジェクト概要

実験データ解析フレームワーク。解析者の暗黙的な依存（データの意味、パラメータの経緯、処理の前提条件）を明示的に外部化し、再現性と追跡性を構造的に保証する。

設計ドキュメント: `docs/` 配下

- [docs/requirements.md](docs/requirements.md) — 要求定義（設計原則 + 要求I〜VI）
- [docs/architecture.md](docs/architecture.md) — アーキテクチャ（概要・スコープ・概念モデル・設計方針・要求マッピング）
- [docs/directory-layout.md](docs/directory-layout.md) — ディレクトリ構成
- [docs/components/datastore.md](docs/components/datastore.md) — DataStore（識別軸定義・クエリAPI・バリデーション）
- [docs/components/stage.md](docs/components/stage.md) — ステージ（stage.yaml仕様・状態管理・run_meta・dtype）
- [docs/components/pipeline-gen.md](docs/components/pipeline-gen.md) — パイプライン生成（dvc.yaml導出・バリデーション）
- [docs/components/external-data.md](docs/components/external-data.md) — 外部データ（DAG間合成・dvc import）
- [docs/toolstack.md](docs/toolstack.md) — ツールスタック

## アーキテクチャ

2層構成:

- **Core Library**（`sard.core`）: ドメイン非依存の部品群。QueryEngine, SchemaValidator, Provenance, DAGBuilder
- **Framework**（`sard.framework`）: 規約の強制。DataStore（ファサード）, StageContext, Discovery, Generator

```text
src/sard/
├── core/           ← ドメイン非依存（axes.yaml等の語彙を知らない）
│   ├── models.py
│   ├── query_engine.py
│   ├── schema_validator.py
│   ├── provenance.py
│   └── dag_builder.py
├── framework/      ← 規約の強制（stages/, config/ 等を解釈）
│   ├── datastore.py
│   ├── stage_context.py
│   ├── generator.py
│   └── discovery.py
└── cli/            ← CLIエントリポイント
    └── main.py
```

## 設計原則

- **暗黙依存の外部化**: データの意味・経緯・前提をメタデータとして明示化
- **構造的保証**: 識別軸とスキーマの宣言的定義 → 定義に準拠しないデータは管理下に存在不可
- **不変性と純粋関数性**: 処理ステップは `f(入力データ, パラメータ) → 新データ`
- **データ依存DAG**: 全データ間関係は有向非巡回グラフ

## 開発コマンド

```bash
uv sync                      # 依存インストール
uv run pre-commit install    # フック有効化
uv run pytest                # テスト
uv run pyright               # 型チェック
```

## ツール設定

設定ファイルは `.config/` に集約:

- `.config/ruff.toml` — Ruff（Python lint/format）
- `.config/.prettierrc` — Prettier（Markdown, YAML, JSON, TOML）
- `.config/.markdownlint.jsonc` — markdownlint
- `pyproject.toml [tool.pyright]` — pyright

## 依存ライブラリ

### ランタイム

- `duckdb` — インメモリクエリエンジン
- `polars` — DataFrame操作（イミュータブル・Arrow形式でDuckDBとゼロコピー連携）
- `pydantic` — 設定・スキーマのランタイムバリデーション
- `pandera` — DataFrameバリデーション
- `networkx` — DAG構造の構築・走査・検証
- `dvc` — データバージョン管理・パイプライン実行
- `ruamel.yaml` — YAML 1.2パーサー（ラウンドトリップ保存）
- `typer` — CLIフレームワーク

### 開発

- `pre-commit` — コミット時の自動チェック
- `pyright` — 静的型チェック
- `pytest` + `pytest-cov` — テスト・カバレッジ
