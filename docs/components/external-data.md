# 外部データ

## 取り込み

`dvc import` でデータをローカルにコピーし、出典元への参照を `.dvc` ファイルに記録する。

- データ実体のコピー + `rev_lock` によるスナップショット固定 + `repo.url` による出典参照保持
- `dvc update` で明示的に上流追従
- importはリーフ（使いたいデータ）のみで十分。中間データの全量importは不要

## 配置構造

```text
data/external/<source>/<stage>/   ← 上流の data/stages/<stage>/ をミラー
```

- `sard import --repo <url> --stages <list>` でステージ単位の一括取得
- `dvc update data/external/` で一括更新
- `DataStore.from_external("data/external/<source>/")` で独立インスタンスとしてアクセス

## 上流の公開IF

フレームワークの標準構造（`stages/*`, `config/`, `data/stages/*`）自体が外部IFとして機能する。上流リポジトリに `exports.yaml` 等の追加設定を要求しない。

## 上流DAG理解

上流リポジトリの詳細な来歴は、上流リポジトリを別途clone/参照して辿る。フレームワークの責務外。

## リモートアクセスツール（TODO）

`sard remote` コマンド群でリモートリポジトリのデータ参照・取得を提供する。実装手段はgh CLIまたはGitHub APIを想定。privateリポジトリにも対応。
