# Idea / 横断的観点

ユースケース整理や設計議論の中で浮上した、特定機能・特定シナリオに閉じない論点を集約する。構造化された雑記帳として運用し、論点が固まったら正規ドキュメント（architecture.md, components/\*.md）または issue に昇格させる。

各項目には以下を記述する:

- **論点**: 何が未決か
- **スコープ**: 影響するシナリオ（[usecases.md](usecases.md) のID）または機能領域
- **選択肢**: 取り得る方針
- **関連**: issue, 既存ドキュメント

---

## 編集時バリデーション支援

- **論点**: `staqkit validate` を細粒度に分割し、ユースケース毎に必要な検証だけを統合実行する仕組みが必要か
- **スコープ**: A1, A2, A4, B1, B12, B13 など、yaml/スキーマ編集を伴うシナリオ全般
- **背景**:
    - 現状の `staqkit validate` は横断フルチェック（参照整合性、スキーマ整合性、TableSchemaSet 整合性、column_descriptions 警告）の一括実行
    - スキーマ定義中に「今編集している table_schema だけ検証したい」「stage.yaml の参照整合性だけ見たい」など、部分検証のニーズがある
    - フル validate は時間がかかる場合があり、編集サイクルに組み込みにくい
- **選択肢**:
    - **A. validate のオプション化**: `staqkit validate --target schema|references|descriptions` のようにフラグで対象指定
    - **B. 個別検証コマンドの公開**: `staqkit check-schema`, `staqkit check-refs` 等を独立コマンドとして提供
    - **C. validate 内部の責務分割のみ**: API レベルで分割し、CLI は引き続き `staqkit validate` を統合エントリとする
    - **D. 編集中の即時フィードバック**: pre-commit や IDE 連携（LSP 風）で個別検証を自動実行
- **関連**: #3（エラーハンドリング・設計判断の策定）, [components/cli.md](components/cli.md)

---

## 横断パラメータの扱い

- **論点**: 複数ステージで同じ値（例: サンプリングレート、被験者リスト）を参照するケースの設計仕様
- **スコープ**: stage.yaml の params 設計、B2（パラメータ変更再実行）
- **現状**: architecture.md「未解決事項」に明記されている既知論点
- **関連**: [architecture.md](architecture.md)（未解決事項）

---

## 運用ルール

- 論点が解消したら該当セクションを削除し、解決内容を正規ドキュメントに反映する
- 論点が長期化・複雑化したら独立した issue または ADR ドキュメントに昇格させる
- 本ファイルは「決定事項」を書く場所ではない。決定済み事項は architecture.md / components/ に書く
