# 設計・開発ドキュメント

## 開発セットアップ

```bash
uv sync                      # 依存インストール
uv run pre-commit install    # pre-commitフックの有効化
uv run pytest                # テスト
uv run pyright               # 型チェック
```

## 設計ドキュメント

- [要求定義](requirements.md) — 宣言の先行と信頼・理解・独立の三観点（核要求・委譲・派生）
- [ユースケース](usecases.md) — 利用シナリオの体系化（CLI 体系・連携機能の設計入力）
- [アーキテクチャ](architecture.md) — 2層構成・スコープ・概念モデル・設計方針・要求マッピング
- [ディレクトリ構成](directory-layout.md) — ステージ単位ディレクトリと定義/成果物の分離
- [ツールスタック](toolstack.md) — ランタイム・開発ツールの選定と役割

コンポーネント詳細設計:

- [DataStore](components/datastore.md) — 識別軸定義・クエリAPI・バリデーション
- [ステージ](components/stage.md) — stage.yaml仕様・状態管理・実行モデル・来歴
- [パイプライン生成](components/pipeline-gen.md) — dvc.yaml導出・バリデーション
- [外部データ](components/external-data.md) — DAG間合成・dvc import
