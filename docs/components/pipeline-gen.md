# パイプライン生成

dvc.yaml は `stages/*/stage.yaml` 群から動的に生成される派生物であり、Git管理しない。`dvc.lock` のみGit管理。ルートに単一の dvc.yaml を生成する。

`dvc.lock` は各ステージの実行時パラメータ・入出力ハッシュを commit 単位で記録するため、来歴追跡（T1）の源泉も兼ねる。`staqkit provenance` / `staqkit history` は `dvc.lock` と git 履歴からチェーンを導出する（[stage.md](stage.md#来歴の所在)）。

## CLIラッパー

パイプライン関連の主要コマンド。全コマンドの詳細は [CLI リファレンス](cli.md) を参照。

```bash
staqkit repro [stage]       # 1. Generate → 2. Validate(最小限) → 3. dvc repro
staqkit status              # 1. Generate → 2. dvc status
staqkit dag                 # stage.yaml から直接生成（dvc.yaml 不要）
staqkit validate            # フルチェック（参照整合性 + スキーマ検証全般）
staqkit clean               # 孤児・inactive データ検出（--remove で削除）
staqkit catalog             # テーブルカタログ出力（→ stdout）
```

## 導出マッピング

| dvc.yaml フィールド | 導出元                                                                                                                                                                                                                                                                 |
| ------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| stage 名            | stages/ からの相対ディレクトリパス                                                                                                                                                                                                                                     |
| cmd                 | `python stages/{name}/run.py`                                                                                                                                                                                                                                          |
| deps                | ① `stages/{name}/run.py`（自身のコード）② 上流ステージの全 outs ファイル（inputs の source_stage から展開）③ `config/table_schemas/{table}.yaml`（自ステージの outs テーブル名に対応するスキーマ）④ extra_deps の各 value                                              |
| params              | `stage.yaml` の `params`・`inputs` キー（`stages/{name}/stage.yaml: [params, inputs]`）で束縛宣言自体を追跡。加えて `params` の各束縛の右辺 `(file, key)` を `file` 単位にまとめ、`<file>: [<key>, ...]` として展開する（[stage.md](stage.md#params外部ファイル参照)） |
| outs                | stage.yaml の outs の各 path から `data/stages/{name}/{path}` を生成                                                                                                                                                                                                   |
| desc                | stage.yaml の desc                                                                                                                                                                                                                                                     |

## ステージ包含ルール

- **active**: dvc.yaml に含める
- **planned**: dvc.yaml に含めない（DAG可視化は stage.yaml ベースで別途生成）
- **inactive**: dvc.yaml に含めない。下流も再帰的に除外

active ステージが inputs で planned ステージを参照する場合、参照先 outs は dvc.yaml に存在せず実行できない。`staqkit validate` は警告に留め、`staqkit repro` は `ReferenceIntegrityError` で停止する（[stage.md](stage.md#active-が-planned-を参照した場合)）。検査は実行対象（effective-active）にのみ発火するため、planned から planned への参照は対象外。

## バリデーション

| 検査項目                                           | validate（フル） | repro（最小限） |
| -------------------------------------------------- | ---------------- | --------------- |
| 参照整合性（source_stage 実在・循環検出）          | YES              | YES             |
| active が planned を inputs 参照                   | YES（警告）      | YES（エラー）   |
| extra_deps の glob が 0 件マッチ                   | YES（エラー）    | YES（エラー）   |
| スキーマ整合性（parquet vs config/table_schemas/） | YES              | ---             |
| TableSchemaSet 整合性（FK 参照先・型一致）         | YES              | ---             |
| column_descriptions 未記述                         | YES（警告）      | ---             |

`staqkit validate` の各検査群は `--target schema|references|descriptions` で個別実行でき、編集ループ中の部分検証に使える（[cli.md](cli.md#staqkit-validate)）。

## 生成例

stage.yaml:

```yaml
# stages/normalize/stage.yaml
desc: "生データの正規化"
status: active
outs:
    timeseries:
        path: timeseries.parquet
        add_datastore: true
    dtype:
        path: dtype.parquet
        add_datastore: true
params:
    method: { file: params/normalize.yaml, key: method }
    sampling_rate: { file: params/motion.yaml, key: sampling_rate }
inputs:
    - source_stage: import
```

生成される dvc.yaml:

```yaml
stages:
    normalize:
        cmd: python stages/normalize/run.py
        deps:
            - stages/normalize/run.py
            - data/stages/import/timeseries.parquet
            - data/stages/import/dtype.parquet
            - data/stages/import/record.parquet
            - config/table_schemas/timeseries.yaml
            - config/table_schemas/dtype.yaml
        params:
            - stages/normalize/stage.yaml:
                  - params
                  - inputs
            - params/normalize.yaml:
                  - method
            - params/motion.yaml:
                  - sampling_rate
        outs:
            - data/stages/normalize/timeseries.parquet
            - data/stages/normalize/dtype.parquet
        desc: "生データの正規化"
```
