# CLI リファレンス

全コマンドは `staqkit` プレフィックスで統一する。各コマンドは Project 層を呼び出す薄いラッパーである。データ実体を参照するコマンド（catalog / validate（スキーマ準拠検査時のみ））は、Project 層のスコープ解決ファクトリ（`build_scoped_engine`）と Core 層の SchemaValidator を用い、run.py / notebook 向けの DataStore ファサードには依存しない（[architecture.md](../architecture.md#スコープ解決ファクトリと依存方向)）。スキーマ内省コマンド（schema / column）はデータ実体を要さず、TableSchemaSet（`load_schema_set`）のみで成立する。

## パイプライン操作

### staqkit repro

```bash
staqkit repro [stage]
```

stage.yaml 群から dvc.yaml を動的生成 → 最小限バリデーション → `dvc repro` を実行する。stage を指定すると対象ステージとその上流のみ再実行する。

### staqkit status

```bash
staqkit status
```

stage.yaml 群から dvc.yaml を動的生成 → `dvc status` を実行し、各ステージの鮮度を表示する。

### staqkit dag

```bash
staqkit dag
```

stage.yaml から直接 DAG を生成して可視化する。dvc.yaml の生成を経由しないため、planned ステージも含めた全体構造を表示可能。

## ステージ管理

### staqkit add-stage

```bash
staqkit add-stage <path> [--status <active|planned|inactive>]
```

新しいステージのディレクトリ（`stages/<path>/`）に stage.yaml と run.py のボイラープレートを生成する。`--status` で初期状態を指定する（既定: planned）。プロジェクト全体の初期化は Copier が担い、本コマンドは既存プロジェクト内へのステージ追加に専念する（[distribution.md](../distribution.md#初期化とステージ追加の責務分担)）。コマンドの詳細仕様（add 系の拡張要否・登録ステージ用テンプレート等）は [#7](https://github.com/sakashita44/staqkit/issues/7) で策定中。

## バリデーション

### staqkit validate

```bash
staqkit validate
```

横断的なフルチェックを実行する。

- 参照整合性（source_stage の実在確認・循環検出）
- スキーマ整合性（Parquet ファイル vs `config/table_schemas/`）
- TableSchemaSet 整合性（FK 参照先の存在・型一致）
- column_descriptions 未記述の警告

## データ管理

### staqkit clean

```bash
staqkit clean              # 孤児・inactive データを検出して一覧表示
staqkit clean --remove     # 確認の上、実際に削除
```

検出対象:

- `data/stages/xxx/` が存在するが対応する `stage.yaml` がない（孤児）
- `data/stages/xxx/` が存在し、status が inactive（休止中データ）

### staqkit import

```bash
staqkit import --repo <url> --stages <list>
```

外部リポジトリからデータをインポートする。詳細は [外部データ](external-data.md) を参照。

## スキーマ内省・カタログ出力

これらのコマンドは「テーブルの構造・意味」と「テーブルの実体（行）」を別々に見せる。`schema` / `column` は `config/table_schemas/`（[TableSchemaSet](datastore.md#tableschemaset)）由来で、データ実体がなくても引ける構造・意味の面を出力する。`catalog` は `data/stages/` 由来で、スコープ内の実データ行をダンプする。

### staqkit schema

```bash
staqkit schema           # 定義済みテーブル名の一覧 + 各テーブルの desc
staqkit schema <table>   # 単一テーブルの全スキーマ
```

引数なしでプロジェクトに定義された全テーブル（`config/table_schemas/`）の名前と1行説明を一覧する。引数を与えると、そのテーブルのカラム・型・PK/FK・CHECK/UNIQUE/NOT NULL 制約と `column_descriptions`、`catalog` フラグを表示する。データ実体を要さないため、planned テーブル（定義のみ・データ未生成）も対象となる。

```bash
staqkit schema timeseries
# timeseries — 正規化済み時系列データ
#   uid    VARCHAR  NOT NULL  PK                  試行一意識別子（subject_id × trial_id で決定）
#   dkey   VARCHAR  NOT NULL  PK  FK→dtype(dkey)  データ種別識別子
#   frame  INTEGER            PK  CHECK(frame>=0) フレーム番号（0始まり）
#   value  DOUBLE                                 測定値。意味と単位は dkey に従属
#   primary key: (uid, dkey, frame)
#   catalog: true
```

TableSchemaSet の `table_names()` / `get(table)`（[公開 API](datastore.md#公開-api)）を集約して表示する。

### staqkit column

```bash
staqkit column <column_name>
```

指定カラム名の全テーブルでの出現箇所を横断検索する。`schema <table>` がテーブル軸の内省であるのに対し、`column` はカラム軸で `config/table_schemas/` を横断する。

```bash
staqkit column dkey
# dtype.dkey       PK                  データ種別の識別子（辞書テーブルの主キー）
# timeseries.dkey  PK  FK→dtype(dkey)  （参照先 dtype.dkey の description を表示）
```

各出現箇所について、PK か・FK か（両立しうる）・description・FK 参照先を表示する。`timeseries.dkey` のように複合 PK の一部かつ他テーブルへの FK である列は、両方のマーカーを併記する（[直交する2フィールド](datastore.md#公開-api)）。TableSchemaSet の `find_column()` が返す [ColumnOccurrence](datastore.md#公開-api) を整形して出力する。データの置き場所（table_schema）と見せ方（CLI）の分離により、発見性・引き継ぎ性を実現する。

### staqkit catalog

```bash
staqkit catalog                          # config で catalog: true な全テーブルのエントリ → stdout
staqkit catalog --table dtype timeseries # 指定テーブルのみ → stdout
staqkit catalog --up-to normalize analyze     # スコープ付き（normalize, analyze の上流閉包のみ）→ stdout
staqkit catalog --table dtype --up-to normalize  # テーブル指定 + スコープ → stdout
```

`config/table_schemas/` で `catalog: true` に設定されたテーブルのエントリ（実データ行）を一覧出力する。`schema` が構造を見せるのに対し、`catalog` は参照テーブル（`dtype` 辞書等）の中身を人間可読な目録として publish する。`--table` で明示指定した場合はそちらが優先される。planned テーブル（定義のみ・データ未生成）を指定した場合は空出力とし、エラーにはしない（スコープ内に存在する行を出すコマンドであり、行が無いことは異常ではない）。

出力は常に stdout。ファイルへの保存はパイプで行う。

```bash
# Git 管理用カタログの生成例
staqkit catalog > docs/dtype_catalog.md
```

`--up-to` は Project 層の[スコープ解決](datastore.md#スコープ解決ファクトリ)と同じ原理で、指定ステージの上流閉包（DAG を遡って到達可能な全ステージ）に出力を限定する。特定ステージの依存範囲だけを確認したい場合に使う。

## プロヴェナンス

### staqkit history

```bash
staqkit history <stage>
```

指定ステージの過去の run_meta 一覧を表示する。内部的には `git log` をラップする。

### staqkit provenance

```bash
staqkit provenance <stage>
```

指定ステージのプロヴェナンスチェーン（deps_runs を再帰的に辿った実行系譜）を表示する。
