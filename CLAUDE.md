# 開発ガイド

## プロジェクト

staqkit はファイルベースの実験データ解析を対象とする Python パッケージ。目指す性質と管理範囲は `docs/requirements.md` に記述する。

現在の `src/staqkit/` は初期状態であり、CLI・DataStore・stage runtime 等の公開APIは未実装。実在しない内部クラスやモジュール構成を前提にしない。

## 開発コマンド

```bash
uv sync
uv run pre-commit install
uv run pytest
uv run pytest tests/test_placeholder.py
uv run pyright
```

Python 依存関係の追加・削除は `uv add` / `uv remove` を使用する。

## 設定

- `pyproject.toml`: パッケージ設定、依存関係、型チェック・テスト設定
- `.config/ruff.toml`: Ruff
- `.config/.prettierrc`: Prettier
- `.config/.markdownlint.jsonc`: Markdownlint
- `.pre-commit-config.yaml`: コミット前の検査

## 保守

- 実装の構造はコードと型、期待する振る舞いはテストで表す。
- 要求文書はソフトウェアの目指す性質を表す。未実装の内部クラス構造や処理手順を要求として固定しない。
- 利用・開発ドキュメントは現行の実装と整合させ、未実装の機能を利用可能なものとして記載しない。
- ドキュメントの内容はリポジトリ内で完結させる。
