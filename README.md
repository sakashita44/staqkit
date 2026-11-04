# staqkit

> [!NOTE]
> 開発中のため、公開 API、コマンド、宣言ファイルの形式は予告なく変更される場合がある。

staqkit は、ファイルベースの実験データ解析に、意味的なデータアクセス、データ契約、生成関係の追跡を提供する Python ツールである。

## コンセプト

- 属性ベースのデータアクセス: 物理ファイルパスに依存せず、意味的な属性でデータを参照する。
- データ依存関係の明示化: 入力データ、処理、パラメータと成果物の関係を宣言し、変更の影響範囲を把握できるようにする。
- スキーマに基づく契約: データの構造と制約を明示し、管理対象のデータを検証する。
- 生成関係の追跡: 宣言した生成条件と成果物の整合性を、追跡可能な範囲で確認できるようにする。

## 動作要件

- Python 3.13 以上
- Git
- [uv](https://docs.astral.sh/uv/)（クイックスタートのコマンド実行に用いる）

DVC、DuckDB、polars は staqkit の依存関係としてインストールされる。

## インストール

staqkit は PyPI に公開されていないため、GitHub のリポジトリを指定してインストールする。

```bash
uv add git+https://github.com/sakashita44/staqkit
```

## クイックスタート

試行ごとの計測値を CSV から取り込み、しきい値以上の試行について実験条件ごとの平均値を求めるパイプラインを作成する。パイプラインは 2 つの stage で構成する。

- `ingest`: CSV を読み取り、計測値のテーブル `measurements` を出力する。
- `summarize`: `measurements` を読み取り、平均値のテーブル `summary` を出力する。

作成するファイルを示す。パスにはプロジェクトのルートからの相対パスを用いる。

| パス                                                     | 内容                                 |
| -------------------------------------------------------- | ------------------------------------ |
| `data/raw/measurements.csv`                              | 生データ                             |
| `params.yaml`                                            | パラメータ                           |
| `config/table_schemas/<テーブル名>.yaml`                 | テーブル定義（3 テーブル）           |
| `config/keys/conditions.yaml`                            | 実験条件の一覧（キーの宣言ファイル） |
| `stages/ingest/stage.yaml`、`stages/ingest/run.py`       | `ingest` の宣言と処理                |
| `stages/summarize/stage.yaml`、`stages/summarize/run.py` | `summarize` の宣言と処理             |

### プロジェクトの準備

解析プロジェクトを Git と DVC で初期化し、staqkit を追加する。staqkit は、`.dvc/` を含むディレクトリをプロジェクトのルートとして扱う。

```bash
git init
uv init --python 3.13
uv add git+https://github.com/sakashita44/staqkit
uv run dvc init
```

生データ `data/raw/measurements.csv` とパラメータ `params.yaml` を作成する。

```csv
subject_id,condition,trial,value
S01,control,1,1.2
S01,treatment,2,0.4
S02,control,1,1.5
S02,treatment,2,2.1
```

```yaml
# params.yaml
summarize:
    min_value: 0.5
```

### テーブルの定義

stage が読み書きするテーブルの列、型、制約を、`config/table_schemas/<テーブル名>.yaml` に DuckDB の `CREATE TABLE` 文で定義する。staqkit は、stage の出力をこの定義に照らして検査する。すべてのテーブルに主キーを定義すること。

実験条件のように、解析者が意図を持って定める分類の語彙は、キーとして YAML で宣言する。キーを定義するテーブルには `role: keys` を指定し、行をキーの宣言ファイルに記述する。被験者や試行のように実験の進行に伴って生じる識別子は、キーとして宣言せず、生データから取り込む。

```yaml
# config/table_schemas/conditions.yaml
role: keys
description: 実験条件の一覧
ddl: |
    CREATE TABLE conditions (
      condition   VARCHAR PRIMARY KEY,
      description VARCHAR NOT NULL
    )
```

```yaml
# config/keys/conditions.yaml
table: conditions
rows:
    - { condition: control, description: 介入なし }
    - { condition: treatment, description: 介入あり }
```

stage が出力するデータのテーブルを定義する。`condition` を外部キーで `conditions` に結び付けると、宣言した実験条件以外の値は書き出せなくなる。

```yaml
# config/table_schemas/measurements.yaml
description: 試行ごとの計測値
ddl: |
    CREATE TABLE measurements (
      subject_id VARCHAR NOT NULL,
      condition  VARCHAR NOT NULL REFERENCES conditions (condition),
      trial      BIGINT NOT NULL,
      value      DOUBLE NOT NULL,
      PRIMARY KEY (subject_id, trial)
    )
```

```yaml
# config/table_schemas/summary.yaml
description: 実験条件ごとの平均値
ddl: |
    CREATE TABLE summary (
      condition  VARCHAR PRIMARY KEY REFERENCES conditions (condition),
      mean_value DOUBLE NOT NULL
    )
```

### stage の作成

stage ごとに、`stages/<stage 名>/stage.yaml` に入力、パラメータ、出力を宣言し、`stages/<stage 名>/run.py` に処理を記述する。staqkit は `stage.yaml` から DVC のパイプライン定義を生成する。

`ingest` は、stage の出力ではない生データを `path_deps` に宣言する。宣言したファイルが変更されると、stage が再実行される。

```yaml
# stages/ingest/stage.yaml
inputs: {}
params: {}
path_deps:
    - data/raw/measurements.csv
outs:
    measurements: { path: measurements.parquet, table: measurements }
```

`run.py` では、`run` 関数を定義して `run_stage` に渡す。テーブルへの出力は、`outs` のキーを指定して `store.write_table` で書き出す。DataFrame の列の型は、DDL の型と一致させること（`VARCHAR`、`BIGINT`、`DOUBLE` は polars の `String`、`Int64`、`Float64`）。

```python
# stages/ingest/run.py
import polars as pl

from staqkit import DataStore, StageInfo, run_stage


def run(stage: StageInfo, store: DataStore) -> None:
    df = pl.read_csv(
        stage.root / "data/raw/measurements.csv",
        schema={
            "subject_id": pl.String,
            "condition": pl.String,
            "trial": pl.Int64,
            "value": pl.Float64,
        },
    )
    store.write_table("measurements", df)


if __name__ == "__main__":
    run_stage(run)
```

`summarize` は、`ingest` の出力を `inputs.tables` に、しきい値を `params` に宣言する。

```yaml
# stages/summarize/stage.yaml
inputs:
    tables:
        - { stage: ingest, out: measurements }
params:
    min_value: { file: params.yaml, key: summarize.min_value }
outs:
    summary: { path: summary.parquet, table: summary }
```

入力のテーブルは、ファイルのパスではなくテーブル名を指定して `store.query` で読み取る。パラメータの値は `stage.params` から取得する。

```python
# stages/summarize/run.py
import polars as pl

from staqkit import DataStore, StageInfo, run_stage


def run(stage: StageInfo, store: DataStore) -> None:
    measurements = store.query("measurements")
    summary = (
        measurements.filter(pl.col("value") >= stage.params["min_value"])
        .group_by("condition")
        .agg(pl.col("value").mean().alias("mean_value"))
    )
    store.write_table("summary", summary)


if __name__ == "__main__":
    run_stage(run)
```

### パイプラインの実行

1. 宣言から `dvc.yaml` を生成する。宣言を編集するたびに実行すること。`dvc.yaml` は生成のたびに全体が上書きされるため、直接編集しないこと。

    ```bash
    uv run staqkit generate
    ```

1. パイプラインを実行する。`ingest`、`summarize` の順に実行され、`data/stages/ingest/measurements.parquet`、`data/stages/summarize/summary.parquet`、`dvc.lock` が作成される。

    ```bash
    uv run dvc repro
    ```

1. プロジェクト全体の整合性を検査する。すべての検査項目を通過すると、`検査に合格した` と表示される。失敗した場合は、表示された原因を解消して再実行すること。

    ```bash
    uv run staqkit check
    ```

1. 作成したファイル、`dvc.yaml`、`dvc.lock`、および DVC が出力ディレクトリに作成する `.gitignore` を Git にコミットする。`data/stages/` 配下の出力は DVC が管理するため、Git に追加しないこと。

## 文書

- [ガイド](docs/guide.md): staqkit を用いた解析の構成と進め方
- [リファレンス](docs/reference.md): 宣言ファイルの全項目、Python API、コマンドの仕様
- [トラブルシューティング](docs/troubleshooting.md): 起きやすい問題と対処
- [要求定義](docs/requirements.md): staqkit が目指す性質

## 開発

開発環境の構築とテストの実行には、[uv](https://docs.astral.sh/uv/) を用いる。

```bash
# 依存関係の同期と pre-commit フックの導入
bash scripts/setup.sh

# テストの実行
uv run pytest
```

## ライセンス

[MIT](LICENSE)
