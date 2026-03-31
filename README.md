# staqkit

staqkit — Structured Tabular Access and Query Kit for reproducible research data management.

**S**tructured **T**abular **A**ccess and **Q**uery **Kit** — ファイルベースの Python 解析パイプラインに SQL クエリ層を被せる接着剤。意味的座標による構造化データアクセスと、スキーマの一元管理を提供する。

## コンセプト

- **意味的座標によるデータアクセス**: データ属性（被験者・条件・処理段階等）を識別軸として定義し、SQL（DuckDB）で横断クエリ可能な scoped VIEW を自動構築する
- **スキーマ一元管理**: テーブルスキーマの宣言的定義により、規約に沿ったデータ構造を強制する
- **データ依存関係の明示化**: 処理単位間のデータ依存を宣言的に記述し、変更の影響範囲を追跡可能にする
- **再現性を志向するパイプライン管理**: DVC 等のデータバージョン管理との連携と実行記録の保持により、解析状態の再現を支援する

## ドキュメント

設計・開発に関するドキュメントは [docs/](docs/) を参照。

## ライセンス

MIT
