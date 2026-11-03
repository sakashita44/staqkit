# Changelog

このプロジェクトの変更履歴を記録する。
形式は [Keep a Changelog](https://keepachangelog.com/ja/1.1.0/) に基づき、
バージョニングは [Semantic Versioning](https://semver.org/lang/ja/) に準拠する。

## [Unreleased]

### Added

- stage、テーブル定義、キーの宣言ファイルを検査し、`dvc.yaml` を生成する `staqkit generate` を追加
- stage の処理に宣言した入力だけを提供する `run_stage`、`DataStore.query`、`DataStore.write_table` を追加。書き出し時と stage の終了時に、型、主キー、外部キー、`CHECK` を検査する
- プロジェクト全体の整合性をコミット前に検査する `staqkit check` を追加
