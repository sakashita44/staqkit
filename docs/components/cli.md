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
staqkit add-stage <path> [--status <active|planned|inactive>] [--template <default|ingest>]
```

新しいステージのディレクトリ（`stages/<path>/`）に stage.yaml と run.py のボイラープレートを生成する。プロジェクト全体の初期化は Copier が担い、本コマンドは既存プロジェクト内へのステージ追加に専念する（[distribution.md](../distribution.md#初期化とステージ追加の責務分担)）。

- `--status`: 初期状態（既定: planned。宣言の先行＝実体に先立つ宣言と整合）。
- `--template`: run.py 雛形の種別。`default` は通常ステージ（`store.query` → 加工 → `store.write_table`）、`ingest` は生データ・外部 import データをソースとして取り込む取り込みステージ（`extra_deps` でソースを受け、非 Parquet 出力は `add_datastore: false`、パスを格納した sidecar parquet で DataStore から発見可能にする。[external-data.md](external-data.md)、[#6](https://github.com/sakashita44/staqkit/issues/6)）。
- 既存ステージ（同一パス）と重複する場合はエラー終了する。

テンプレートはパッケージに同梱し、バージョン更新で改善が伝播する（プロジェクト側に焼かない。[distribution.md](../distribution.md#雛形と改善の伝播)）。`add-table` 等の他の add 系コマンドは設けない（table schema は単一 YAML で `staqkit schema` により内省でき scaffold 価値が低く、CLI の契約面を不要に増やさないため）。実装時の詳細は [#7](https://github.com/sakashita44/staqkit/issues/7) で追跡する。

## バリデーション

### staqkit validate

```bash
staqkit validate                       # 全検査群を統合実行
staqkit validate --target schema       # スキーマ系のみ
staqkit validate --target references   # 参照整合性のみ
staqkit validate --target descriptions # description 網羅検査のみ
```

引数なしで横断的なフルチェックを実行する。全検査群を回す `staqkit validate` が保証の本体であり、A3（引き継ぎ）・A5（公開）のゲートはこれに依存する。`--target` は編集ループ中に「いま触っている部分だけ」を回すための便宜フィルタであり、検査群の網羅的な列挙でも硬い契約でもない。検査群が増えても、単独実行したい編集ループの局面がある場合にだけ既存のいずれかへ寄せ、なければフル実行に委ねる。トップレベルの検査コマンドは増やさず、`staqkit validate` を統合エントリに保つ。

- 参照整合性（source_stage の実在確認・循環検出、params 束縛先 `file`・`key` の実在確認）: `--target references`
- スキーマ整合性（Parquet ファイル vs `config/table_schemas/`）+ TableSchemaSet 整合性（FK 参照先の存在・型一致）: `--target schema`
- description 網羅検査（説明欄充足・説明系ファイル存在）と column_descriptions 未記述の警告: `--target descriptions`

検査群の責務分割の経緯と方針（CLI コマンドを増やさず `--target` フラグで出し分ける判断）は [#19](https://github.com/sakashita44/staqkit/issues/19) で確定済み。キャッチオール検査対象ファイルの具体的列挙など残る詳細は validate 実装時に確定する。

## データ管理

### staqkit clean

```bash
staqkit clean              # 孤児・inactive データを検出して一覧表示
staqkit clean --remove     # 確認の上、実際に削除
```

検出対象:

- `data/stages/xxx/` が存在するが対応する `stage.yaml` がない（孤児）
- `data/stages/xxx/` が存在し、status が inactive（休止中データ）

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

指定ステージの過去実行（params・入出力ハッシュの変遷）を表示する。`dvc.lock` の当該ステージ部分を git 履歴上で辿る（`git log` をラップ）。

### staqkit provenance

```bash
staqkit provenance <stage>
```

指定ステージのプロヴェナンスチェーン（実行系譜）を表示する。`dvc.lock` の dep ハッシュを起点に、それを確立した上流 commit を `git log -S <hash> -- dvc.lock` で再帰的に辿って導出する。独自の履歴 DB は持たない（[stage.md](stage.md#来歴チェーンの辿り方)）。
