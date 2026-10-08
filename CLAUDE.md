# 開発ガイド

## プロジェクト

staqkit はファイルベースの実験データ解析を対象とする Python パッケージである。目指す性質と管理範囲は `docs/requirements.md` に示す。

`src/staqkit/` は初期状態であり、公開CLI・解析ランタイムは未実装である。実在しない内部クラスやモジュール構成を前提にしないこと。

## 開発コマンド

初回のセットアップでは、依存関係を同期し、pre-commit フックを有効化する。

```bash
uv sync
uv run pre-commit install
```

変更後の検証では、テストと型チェックを実行し、いずれもエラーなく終了することを確認する。単一のテストファイルだけを実行する場合は `uv run pytest <テストファイルのパス>` とする。

```bash
uv run pytest
uv run pyright
```

Python 依存関係の追加・削除には `uv add` / `uv remove` を使用する。

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
