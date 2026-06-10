# 外部データ

## 取り込み

`dvc import` でデータをローカルにコピーし、出典元への参照を `.dvc` ファイルに記録する。

- データ実体のコピー + `rev_lock` によるスナップショット固定 + `repo.url` による出典参照保持
- `dvc update` で明示的に上流追従
- import はリーフ（使いたいデータ）のみで十分。中間データの全量 import は不要

## ソースとしての扱い

取り込んだデータは DataStore へ直接は載せず、生データ（`data/raw/`）と同じく**ソース**として扱う。下流の取り込みステージが `extra_deps` でファイルとして読み込み、加工結果を当該プロジェクト自身の `config/table_schemas/` に従って DataStore に登録する（[stage.md](stage.md#extra_deps-dag外の外部依存)）。

- 取り込みステージは `extra_deps` のソースを読み、run.py で `data/stages/<stage>/` 配下（＝当該ステージの outs）へ書き出す。非 Parquet 出力をそのまま管理下に置く場合は `run.py` で `shutil.copy` し、コピー先を `add_datastore: false` の out として宣言、パスを格納した sidecar parquet（`add_datastore: true`）を併設すると DataStore から発見できる。加工して Parquet 化する場合は `store.write_table` で `add_datastore: true` の out を書く。`staqkit add-stage --template ingest` がこの定型を生成する。
- DataStore に入るデータは必ずそのプロジェクト自身がスキーマ契約を宣言する。これは生データ取り込みと同一の原則であり、外部だけの特例ではない。上流の公開スキーマ（標準構造そのものが外部 IF）はステージ著者が定義を書くときに参照する。
- 上流データの意味確定に別テーブルが必要な場合は、そのテーブルの parquet も import する。「スキーマを必ず import する」というルールではなく、生データを複数ファイル読むのと同じ必要駆動の取り込みである。
- これにより子リポジトリは自身のスキーマで自己完結し、外部スキーマを転送・解釈する専用の仕組みを持たない。

## 追跡性

ソース扱いでも追跡性は損なわれない。`dvc import` はコンテンツハッシュに加えて出典（`repo.url`）と固定コミット（`rev_lock`）を Git 管理の `.dvc` に記録するため、出自リンクを持たないローカル生データの `dvc add` より強い来歴を持つ。

- 取り込みステージは `data/external/...` を `extra_deps` の deps として取るため、`dvc.lock` にハッシュが記録される。来歴の源泉（`dvc.lock` + git 履歴）で「上流コミット → `data/external/` → 取り込みステージ出力 → 下流」が一本に繋がる。
- `dvc update` で上流 `rev_lock` が変わるとハッシュが変わり、取り込みステージ以降が DVC により無効化される。鮮度伝搬がリポジトリ境界を越えて働く。
- 上流リポジトリ内部での来歴（上流での生成過程）まで辿るには、固定 `rev` で上流リポジトリを別途参照する。下流は正確・再現可能なポインタを保持し、より深い来歴はそれを解決して辿る。

## 配置構造

```text
data/external/<source>/<stage>/   ← 上流の data/stages/<stage>/ をミラー
```

- `staqkit import --repo <url> --stages <list>` でステージ単位の一括取得
- `dvc update data/external/` で一括更新

## 上流の公開IF

staqkit の標準構造（`stages/*`, `config/`, `data/stages/*`）自体が外部IFとして機能する。上流リポジトリに `exports.yaml` 等の追加設定を要求しない。

## 関連

- CLI 実行困難な外部ツール処理の登録ステージパターン: [#6](https://github.com/sakashita44/staqkit/issues/6)

## リモートアクセスツール（TODO）

`staqkit remote` コマンド群でリモートリポジトリのデータ参照・取得を提供する。実装手段は gh CLI または GitHub API を想定。private リポジトリにも対応。
