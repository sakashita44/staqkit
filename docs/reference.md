# リファレンス

staqkit が読み取る宣言ファイルの形式、stage の処理から用いる Python API、コマンドの仕様を記す。最小の手順は [README](../README.md)、解析の構成と進め方は [ガイド](guide.md)、問題が起きた場合の対処は [トラブルシューティング](troubleshooting.md) を参照のこと。

## プロジェクトの構成

staqkit は、コマンドを実行したディレクトリ（stage の実行時は `run.py` のディレクトリ）から親ディレクトリを順にたどり、最初に見つかった `.dvc/` を含むディレクトリをプロジェクトのルートとして扱う。

プロジェクトのルートを基準とする宣言ファイルと出力の配置先を示す。

| パス                                     | 内容                                                  |
| ---------------------------------------- | ----------------------------------------------------- |
| `config/table_schemas/<テーブル名>.yaml` | テーブル定義                                          |
| `config/keys/**/*.yaml`                  | キーの宣言ファイル                                    |
| `stages/<stage 名>/stage.yaml`           | stage の宣言                                          |
| `stages/<stage 名>/run.py`               | stage の処理                                          |
| `data/stages/<stage 名>/`                | stage の出力の格納先                                  |
| `dvc.yaml`                               | `staqkit generate` が宣言から生成するパイプライン定義 |

宣言ファイルに記述するパスは、`/` で区切った相対パスとすること。絶対パス、`\` による区切り、`.` や `..` を含むパスはエラーとなる。

## テーブル定義

テーブル定義は、テーブルの列、型、主キー、制約を DuckDB の DDL で定める。staqkit は、stage の出力をテーブル定義に照らして検査し、stage が読み取るデータの列と型をテーブル定義に合わせる。

テーブルごとに `config/table_schemas/<テーブル名>.yaml` を作成する。ファイル名（拡張子を除く）がテーブル名となる。大文字と小文字だけが異なるテーブル名は重複とみなされる。

### 項目

- `ddl`: 必須。DuckDB の `CREATE TABLE` 文を 1 文記述する。
- `role`: テーブルの種類。`data`（データを格納するテーブル）または `keys`（キーを定義するテーブル）を指定する。省略時は `data` となる。
- `description`: テーブルの説明。文字列とすること。
- `column_descriptions`: 列名と説明の対応。値は文字列とすること。
- `catalog`: 真偽値とすること。

`description`、`column_descriptions`、`catalog` は、値の型だけが検査される。

### DDL の規則

- `ddl` が作成するテーブルの名前は、ファイル名と一致させること。
- すべてのテーブルに主キーを定義すること。
- 外部キーの参照先のテーブルは、別のテーブル定義として定義すること。テーブル定義の間で外部キーが循環する場合はエラーとなる。
- キーを定義するテーブルの外部キーが参照できるテーブルは、キーを定義するテーブルに限られる。
- キーを定義するテーブルでは、列名に `__staqkit_file` は指定できない。
- `ddl` は literal ブロック（`|`）で記述すること。folded ブロック（`>`）では、改行位置の変更が DDL の変更として検知されない場合がある。

DDL の `NOT NULL`、主キー、外部キー、`UNIQUE`、`CHECK` 制約は、stage が出力を書き出す際に staqkit が検査する。

## キーの宣言ファイル

キーを定義するテーブル（`role: keys`）の行は、stage の出力ではなく、キーの宣言ファイルに記述する。キーの宣言ファイルは `config/keys/` 配下に任意の階層で配置できる。1 つのテーブルの行を、複数のキーの宣言ファイルに分けて記述できる。

```yaml
table: metric
rows:
    - { metric: step_length, unit: mm }
    - { metric: step_width, unit: mm }
```

- `table`: 必須。行を記述するテーブルの名前。キーを定義するテーブルに限られる。
- `rows`: 必須。行のリスト。各行は列名と値の対応で記述する。

同一テーブルに属するすべてのキーの宣言ファイルの行は、まとめて DDL の制約に照らして検査される。ファイルが異なっても、主キーが重複する行はエラーとなる。

行の値の型は、DDL の列の型と一致させること。`null` はすべての型の列に記述できる。キーの宣言ファイルで値を記述できる列の型は、次の型に限られる。

- `VARCHAR`（`TEXT`）: 文字列。`01` や `true` のように YAML が文字列以外として解釈する値は、引用符で囲むこと。
- `BOOLEAN`: 真偽値。
- 整数型（`TINYINT`、`SMALLINT`、`INTEGER`、`BIGINT`、`HUGEINT` とその符号なし型）: 整数。
- `FLOAT`、`DOUBLE`、`DECIMAL`: 数値。
- `DATE`: 日付（`2026-01-31` の形式）。
- `TIMESTAMP`: 日時。

## stage の宣言

stage の宣言は、stage が読み取る入力、参照するパラメータ、書き出す出力を定める。staqkit は、この宣言から `dvc.yaml` の stage を生成する。宣言にない入力の読み取りや出力の書き出しは、stage の実行時にエラーとなる。

stage ごとに `stages/<stage 名>/stage.yaml` を作成する。stage 名には、`stages/` から `stage.yaml` のあるディレクトリまでの相対パスが用いられる。たとえば `stages/gait/extract/stage.yaml` の stage 名は `gait/extract` である。stage 名の各階層の名前に使用できる文字は、ASCII の英数字、`_`、`-` に限られる。

```yaml
inputs:
    tables:
        - { stage: extract_steps, out: og }
    keys:
        - config/keys/metrics_spatial.yaml
    files:
        qc: { stage: extract_steps, out: qc_plot }
params:
    min_value: { file: params.yaml, key: summarize.min_value }
path_deps:
    - data/raw/trials
outs:
    summary: { path: summary.parquet, table: step_summary }
```

`inputs` と `params` は必須である。使用しない場合は空のマッピング（`{}`）を記述すること。`path_deps` と `outs` は省略できる。

### inputs

- `tables`: 読み取るテーブルの artifact のリスト。各要素は、出力元の stage 名（`stage`）と、その stage の `outs` のキー（`out`）で指定する。
- `keys`: 読み取るキーの宣言ファイルのリスト。`config/keys/` 配下のファイルを、プロジェクトのルートからの相対パスで指定する。
- `files`: `table` を指定しない出力のうち、読み取る対象。名前と、`tables` と同じ形式の artifact の対応で指定する。

`tables` に指定した artifact のうち同じテーブルのものは、読み取る際に 1 つのテーブルに統合される。統合した範囲で主キーが重複する場合はエラーとなる。

`keys` は、stage から見えるキーを定める。stage は、見えるキーを参照する行だけを読み取り、見えるキーの値だけを書き出せる。`keys` を省略した場合は、読み取るテーブルと出力するテーブルが参照するキーを定義するテーブルについて、すべてのキーの宣言ファイルが見えるキーとなる。見えるキーの行が、外部キーで別のキーを定義するテーブルの行を参照する場合は、参照先の行を含むキーの宣言ファイルも見えるキーに加わる。

出力するテーブルの外部キーが、データを格納する別のテーブルを参照する場合は、参照先のテーブルの artifact を `tables` に指定するか、同じ stage の `outs` に含めること。

### params

stage の処理が参照するパラメータの名前と、値の所在の対応。値の所在は、YAML ファイル（`file`、プロジェクトのルートからの相対パス）と、そのファイル内のキー（`key`）で指定する。入れ子のキーは `.` で区切る。

### path_deps

stage の出力ではないファイルやディレクトリのうち、stage が読み取るもののリスト。プロジェクトのルートからの相対パスで指定する。生データや、`run.py` が import するプロジェクト内のモジュールが該当する。staqkit は、`run.py` が読み取るファイルや import するモジュールを自動では追跡しない。

### outs

出力のキーと、出力の対応。

- `path`: 必須。`data/stages/<stage 名>/` からの相対パス。すべての stage の出力の間で、パスの重複と、一方が他方を含む配置はエラーとなる。大文字と小文字だけが異なるパスも重複とみなされる。
- `table`: 出力するテーブルの名前。データを格納するテーブルに限られる。`table` を指定した出力の `path` は、拡張子を `.parquet` とすること。

`table` を指定した出力は、`DataStore.write_table` で書き出す。staqkit は、出力を主キーの順に並べ、Parquet ファイルとして書き出す。`table` を指定しない出力には、図など任意のファイルを出力できる。

### stage が再実行される条件

`dvc.yaml` の stage は、次のファイルを依存関係とする。DVC は、これらのファイルが変更された stage を再実行する。

- `run.py`
- `inputs.tables` と `inputs.files` に指定した artifact
- `path_deps` に指定したファイルとディレクトリ
- 見えるキーの宣言ファイル
- `stage.yaml` の `inputs` と `params`
- `params` に指定したパラメータの値
- 読み書きするテーブルのテーブル定義の `ddl`

テーブル定義の `description` などを編集しても、stage は再実行されない。

## Python API

stage の処理は、`stages/<stage 名>/run.py` に記述する。

```python
from staqkit import DataStore, StageInfo, run_stage


def run(stage: StageInfo, store: DataStore) -> None: ...


if __name__ == "__main__":
    run_stage(run)
```

### run_stage

`run_stage(run)` は、`run` 関数を定義したファイルの位置から stage を特定し、`run` 関数を呼び出す。呼び出しの前に、`dvc.yaml` の stage が宣言から生成される内容と一致することを検査し、一致しない場合はエラーとなる。`run` 関数が終了した後、出力の検査を行う。

エラーが発生した場合、`run_stage` はメッセージを標準エラー出力へ表示し、終了コード 1 でプロセスを終了する。

### StageInfo

- `name`: stage 名。
- `root`: プロジェクトのルートの絶対パス（`pathlib.Path`）。`path_deps` に指定したファイルは、`stage.root / "data/raw/trials"` のように参照する。
- `params`: `params` に指定したパラメータの名前と値の対応。
- `input_path(name)`: `inputs.files` に指定した出力の絶対パス。
- `output_path(key)`: `outs` のうち `table` を指定しない出力の絶対パス。親ディレクトリは自動で作成される。

### DataStore

`query(table, filters=None)` は、テーブルの行を polars の DataFrame として返す。`table` には、`inputs.tables` で読み取るテーブル、または見えるキーを定義するテーブルの名前を指定する。

`filters` には、列名と値の対応を指定する。

- 値を 1 つ指定した場合は、その値に一致する行を返す。`None` は `NULL` に一致する。
- リストまたはタプルを指定した場合は、いずれかの値に一致する行を返す。空のリストを指定した場合は、行を返さない。
- 見えるキーにない値で、キーを定義するテーブルを参照する列を絞り込んだ場合は、エラーとなる。

データを格納するテーブルの行のうち、見えるキーにない値のキーを参照する行は返されない。外部キーの列が `NULL` の行は返される。

`write_table(key, df)` は、`outs` のうち `table` を指定した出力に、polars の DataFrame を書き出す。DataFrame の列の型は、DDL の型と一致させること（例: `INTEGER` の列には `pl.Int32`、`BIGINT` の列には `pl.Int64`）。staqkit は、書き出す前に列の型、`NOT NULL`、主キー、外部キー、`UNIQUE`、`CHECK` 制約を検査し、違反があればエラーとなる。同じ出力を 2 回書き出すとエラーとなる。

`run` 関数が終了するまでに、`table` を指定したすべての出力を書き出すこと。staqkit はその後、宣言した入力と今回の出力を合わせた範囲で、主キーの重複と、データを格納するテーブルを参照する外部キーを検査する。

### 例外

staqkit が送出する例外は、いずれも `StaqkitError` を継承する。

- `ConfigError`: 宣言ファイルの形式や内容の誤り。
- `AccessError`: 宣言にないテーブル、列、出力への読み書き。
- `ValidationError`: データの検査の失敗。

## コマンド

コマンドは、プロジェクトのルートまたはその配下のディレクトリで実行する。失敗した場合は、メッセージを標準エラー出力へ表示し、終了コード 1 を返す。

### staqkit generate

宣言ファイルを検査し、`dvc.yaml` を生成する。`dvc.yaml` は生成のたびに全体が上書きされるため、直接編集しないこと。

`outs` や `path_deps` の変更は、`staqkit generate` を実行するまで `dvc.yaml` に反映されない。宣言を編集した後は、`staqkit generate` を実行すること。

### staqkit check

プロジェクト全体の整合性を検査する。宣言ファイルの検査に加えて次の項目を検査し、すべてを満たす場合に終了コード 0 を返す。

- `dvc.yaml` が宣言から生成される内容と一致する。
- `dvc status` において、すべての stage が最新である。
- `dvc.lock` に記録された依存関係が、`dvc.yaml` の依存関係と一致する。
- 同じテーブルを出力する artifact の間で、主キーが重複しない。出力の実体ファイルがない artifact がある場合は失敗する。

出力の型、`NOT NULL`、外部キー、`UNIQUE`、`CHECK` 制約は stage の実行時に検査され、`staqkit check` の対象には含まれない。DVC が run cache から出力を復元した stage では、stage の処理が実行されないため、これらの検査も行われない。
