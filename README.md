# staqkit

> [!NOTE]
> WIP

staqkit は、ファイルベースの実験データ解析に、意味的なデータアクセス、データ契約、生成関係の追跡を提供する Python ツールである。

## コンセプト

- 属性ベースのデータアクセス: 物理ファイルパスに依存せず、意味的な属性でデータを参照する。
- データ依存関係の明示化: 入力データ・処理・パラメータと成果物の関係を宣言し、変更の影響範囲を把握できるようにする。
- スキーマに基づく契約: データの構造と制約を明示し、管理対象のデータを検証する。
- 生成関係の追跡: 宣言された生成条件と成果物の整合性を、追跡可能な範囲で確認できるようにする。

目的と要求の詳細: [要求定義](docs/requirements.md)

## インストールと使い方

### インストール

解析プロジェクトの仮想環境に staqkit を導入する。DVC は staqkit の依存として同時に導入される。

```bash
uv add git+https://github.com/sakashita44/staqkit
```

解析プロジェクトは Git と DVC で初期化しておくこと（`git init`、`uv run dvc init`）。staqkit は `.dvc/` を含むディレクトリをプロジェクトのルートとして扱う。

### プロジェクトの構成

staqkit は、プロジェクトのルートから次の位置にある宣言を読み込む。

| パス                                     | 内容                                     |
| ---------------------------------------- | ---------------------------------------- |
| `config/table_schemas/<テーブル名>.yaml` | テーブルの定義（DDL）                    |
| `config/keys/**/*.yaml`                  | キーを定義するテーブルの行               |
| `stages/<stage 名>/stage.yaml`           | stage の入力、パラメータ、出力の宣言     |
| `stages/<stage 名>/run.py`               | stage の処理                             |
| `data/stages/<stage 名>/`                | stage の出力の格納先（staqkit が決める） |
| `dvc.yaml`                               | 宣言から生成するパイプライン定義         |

stage 名は `stages/` からのディレクトリの相対パスであり、各区切りには ASCII の英数字、`_`、`-` を用いる。

### 宣言の例

テーブルの定義では、`ddl` に DuckDB の `CREATE TABLE` を 1 文記述する。すべてのテーブルに主キーが必要である。DDL は literal ブロック（`|`）で記述すること。folded ブロック（`>`）では、改行位置の変更が DDL の変更として検知されない場合がある。

```yaml
# config/table_schemas/step_observation.yaml
description: 1 歩ごとの観測値
ddl: |
    CREATE TABLE step_observation (
      trial        TEXT NOT NULL,
      step_ordinal INTEGER NOT NULL,
      metric       TEXT NOT NULL REFERENCES metric (metric),
      value        DOUBLE NOT NULL,
      PRIMARY KEY (trial, step_ordinal, metric)
    );
```

キーの語彙と属性を宣言で提供するテーブルには `role: keys` を指定し、行を `config/keys/` 配下の宣言ファイルに記述する。行の値の型は DDL の列の型と一致させること。文字列の列に `01` のような値を記述する場合は引用符で囲む。

```yaml
# config/table_schemas/metric.yaml
role: keys
ddl: |
    CREATE TABLE metric (
      metric TEXT PRIMARY KEY,
      unit   TEXT NOT NULL
    );
```

```yaml
# config/keys/metrics_spatial.yaml
table: metric
rows:
    - { metric: step_length, unit: mm }
    - { metric: step_width, unit: mm }
```

stage の宣言では、`inputs` と `params` が必須である。使わない場合は空の対応（`{}`）を記述する。`outs` の `path` は `data/stages/<stage 名>/` からの相対パスであり、`table` を指定した出力は Parquet ファイルとして staqkit が書き出す。

```yaml
# stages/summarize_steps/stage.yaml
inputs:
    tables:
        - { stage: extract_steps, out: og } # extract_steps の出力 og だけを読む
    keys:
        - config/keys/metrics_spatial.yaml # 省略時は、テーブルが参照するすべての宣言ファイル
params:
    min_value: { file: params.yaml, key: summarize.min_value }
outs:
    summary: { path: summary.parquet, table: step_summary }
```

`run.py` は `run` 関数を定義し、`run_stage` に渡す。読み取りは論理テーブル名で、書き出しは `outs` のキーで指定する。

```python
# stages/summarize_steps/run.py
import polars as pl

from staqkit import DataStore, StageInfo, run_stage


def run(stage: StageInfo, store: DataStore) -> None:
    observations = store.query("step_observation", {"metric": ["step_length"]})
    summary = observations.group_by("trial", "metric").agg(
        pl.len().cast(pl.Int64).alias("n"), pl.col("value").mean().alias("mean")
    )
    store.write_table("summary", summary)


if __name__ == "__main__":
    run_stage(run)
```

`write_table` に渡す DataFrame の列の型は、DDL の型と一致させること（例: `INTEGER` の列には `pl.Int32`）。

### 実行

1. 宣言を検査し、`dvc.yaml` を生成する。宣言を編集するたびに再実行すること。

    ```bash
    uv run staqkit generate
    ```

1. パイプラインを実行する。stage の `cmd` は PATH 上の `python` で実行されるため、staqkit を導入した仮想環境で実行すること。

    ```bash
    uv run dvc repro
    ```

1. コミットの前に、プロジェクト全体の整合性を検査する。

    ```bash
    uv run staqkit check
    ```

    成功すると終了コード 0 を返す。失敗した場合は、表示された原因（`dvc.yaml` の再生成、`dvc repro` の再実行、主キーの重複など）を解消して再実行すること。

`LongPathsEnabled` が無効な Windows では、プロジェクトのルートの絶対パスがおよそ 80 文字を超えると、`dvc repro` が run cache の保存に失敗する。ルートを短いパスに配置するか、`LongPathsEnabled` を有効にすること。

pyarrow や DuckDB の版を上げると、Parquet に記録される版情報が変わる。版を上げた後に stage を再実行すると、データが同一でも下流の stage まで再実行される。

## 開発環境

必要なツール: [uv](https://docs.astral.sh/uv/)

```bash
# 依存関係の同期と pre-commit フックの導入
bash scripts/setup.sh

# テストの実行
uv run pytest
```

## ライセンス

[MIT](LICENSE)
