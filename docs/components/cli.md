# CLI リファレンス

全コマンドは `staqkit` プレフィックスで統一する。各コマンドは Framework 層を呼び出す薄いラッパーである。

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

### staqkit catalog

```bash
staqkit catalog                          # config で catalog: true な全テーブル → stdout
staqkit catalog --table dtype timeseries # 指定テーブルのみ → stdout
staqkit catalog --up-to B Y             # スコープ付き（B, Y の上流閉包のみ）→ stdout
staqkit catalog --table dtype --up-to B  # テーブル指定 + スコープ → stdout
```

`config/table_schemas/` で `catalog: true` に設定されたテーブルの内容を一覧出力する。`--table` で明示指定した場合はそちらが優先される。

出力は常に stdout。ファイルへの保存はパイプで行う。

```bash
# Git 管理用カタログの生成例
staqkit catalog > docs/dtype_catalog.md
```

`--up-to` は [DataStore.scoped()](datastore.md#db組み立て) と同じ原理で、指定ステージの上流閉包（DAG を遡って到達可能な全ステージ）に出力を限定する。特定ステージの依存範囲だけを確認したい場合に使う。

### staqkit column

```bash
staqkit column <column_name>
```

指定カラム名の全テーブルでの出現箇所を横断検索する。`config/table_schemas/` の DDL と `column_descriptions` を集約して表示する。

```bash
staqkit column uid
# → record.uid [PK]: "試行一意識別子（subject_id × trial_id で決定）"
# → timeseries.uid [FK → record(uid)]: （参照先の description を表示）
# → ...全テーブルでの出現箇所
```

カラムの役割（PK/FK/通常）、description、FK 参照先を表示する。データの置き場所（table_schema）と見せ方（CLI）の分離により、発見性・引き継ぎ性を実現する。

### staqkit import

```bash
staqkit import --repo <url> --stages <list>
```

外部リポジトリからデータをインポートする。詳細は [外部データ](external-data.md) を参照。

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
