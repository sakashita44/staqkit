# パイプライン生成

dvc.yaml は `stages/*/stage.yaml` 群から動的に生成される派生物であり、Git管理しない。`dvc.lock` のみGit管理。ルートに単一の dvc.yaml を生成する。

## CLIラッパー

パイプライン関連の主要コマンド。全コマンドの詳細は [CLI リファレンス](cli.md) を参照。

```bash
staqkit repro [stage]       # 1. Generate → 2. Validate(最小限) → 3. dvc repro
staqkit status              # 1. Generate → 2. dvc status
staqkit dag                 # stage.yaml から直接生成（dvc.yaml 不要）
staqkit validate            # フルチェック（参照・スキーマ・config 整合性）
staqkit clean               # 孤児・inactive データ検出（--remove で削除）
staqkit catalog             # テーブルカタログ出力（→ stdout）
```

## 導出マッピング

| dvc.yaml フィールド | 導出元                                                                                                                                                                                                                    |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| stage 名            | stages/ からの相対ディレクトリパス                                                                                                                                                                                        |
| cmd                 | `python stages/{name}/run.py`                                                                                                                                                                                             |
| deps                | ① `stages/{name}/run.py`（自身のコード）② 上流ステージの全 outs ファイル（inputs の source_stage から展開）③ `config/table_schemas/{table}.yaml`（自ステージの outs テーブル名に対応するスキーマ）④ extra_deps の各 value |
| params              | `stage.yaml:params` および `stage.yaml:inputs`                                                                                                                                                                            |
| outs                | stage.yaml の outs の各 path から `data/stages/{name}/{path}` を生成                                                                                                                                                      |
| desc                | stage.yaml の desc                                                                                                                                                                                                        |

## ステージ包含ルール

- **active**: dvc.yaml に含める
- **planned**: dvc.yaml に含めない（DAG可視化は stage.yaml ベースで別途生成）
- **inactive**: dvc.yaml に含めない。下流も再帰的に除外

## バリデーション

| 検査項目                                           | validate（フル） | repro（最小限） |
| -------------------------------------------------- | ---------------- | --------------- |
| 参照整合性（source_stage 実在・循環検出）          | YES              | YES             |
| スキーマ整合性（parquet vs config/table_schemas/） | YES              | ---             |
| config 整合性（axes 定義 vs 既存データ）           | YES              | ---             |

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
    method: z_score
inputs:
    - source_stage: import
      query_args: { data_group: joint }
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
        params:
            - stages/normalize/stage.yaml:
                  - params
                  - inputs
        outs:
            - data/stages/normalize/timeseries.parquet
            - data/stages/normalize/dtype.parquet
        desc: "生データの正規化"
```
