# ガイド

staqkit を用いた解析の構成と、staqkit が想定する解析の組み立て方を、例を通して記す。最小の手順は [README のクイックスタート](../README.md#クイックスタート)、宣言ファイルと API の全項目は [リファレンス](reference.md) を参照のこと。

## 解析の構成要素

staqkit を用いる解析は、複数の stage で構成する。stage は、入力を読み取り、処理した結果を出力（以下、artifact）として書き出す処理の単位である。stage が読み書きする表形式のデータには、テーブルとして列、型、主キー、制約を定義する。

テーブル定義と、各 stage の入力、パラメータ、出力は YAML で宣言する。staqkit は、宣言を次の用途に用いる。

- パイプラインの生成: 宣言から DVC のパイプライン定義（`dvc.yaml`）を生成する。stage の実行と、入力やパラメータが変更された stage の再実行は DVC が担う。
- データの参照: stage の処理では、ファイルのパスではなく、テーブル名と列の値を指定してデータを読み取る。
- 読み書きの制限: stage の処理で読み書きできるデータは、宣言した入力と出力に限られる。
- 出力の検査: stage が書き出すデータを、テーブル定義の型と制約に照らして検査する。

テーブルは、格納するデータの由来によって 2 種類に分かれる。

- データを格納するテーブル: stage が出力するデータを格納する。
- キーを定義するテーブル: データの分類に用いる値（以下、キー）とその属性を格納する。行は stage の出力ではなく、キーの宣言ファイルに YAML で記述する。

## キーとデータの切り分け

識別子をキーとして宣言するか、データとして取り込むかは、その値がどのように生じ、増えていくかで判断する。

- キー: 解析者が意図を持って定める分類の語彙。値は、キーの宣言ファイルを編集したときにだけ増減する。探索の過程で指標を追加する場合も、追加は宣言の変更として Git に記録され、編集したキーの宣言ファイルを見えるキーとする stage が再実行される。例: 実験条件、指標名、計測の種類、マーカーと軸、データの分割（学習用、検証用、評価用）。
- データ: 実験や計測の進行に伴って生じる識別子。値は生データとともに増え、解析者が値を 1 つずつ定めるものではない。例: 被験者、試行、試験片、学習の実行。

データを格納するテーブルの列が外部キーでキーを参照すると、宣言にない値は書き出しの時点でエラーとなる。表記の揺れや想定外の値は、出力に混ざる前に検出される。

同じ種類の識別子でも、どちらとして扱うかは解析の方針によって変わる。たとえば、被験者を事前に定めた名簿で管理し、名簿への追加を解析者の判断とみなす解析では、被験者をキーとしてもよい。

データとして扱う識別子は、一覧のファイル（被験者の一覧の CSV など）や生データから stage で取り込み、データを格納するテーブルとして出力する。別のテーブルの列がこの識別子を外部キーで参照する場合は、参照先のテーブルの artifact を、参照する側の stage の `inputs.tables` に指定する。

キーを定義するテーブルは必須ではない。小さな語彙は、DDL の `CHECK` 制約で値を制限してもよい。

## 被験者実験での組み立て

被験者実験のプロジェクトを例に、staqkit を用いた解析の組み立て方を示す。生データと解析の内容を示す。

- 生データ: 被験者の一覧の CSV と、2 種類の計測機器が試行ごとに出力するファイル。
- 解析: 両方の計測機器のファイルから指標の値を取り出し、指標ごとに集計して、図を作成する。

### テーブルの設計

被験者は実験の進行に伴って生じる識別子であるため、被験者の一覧から取り込むデータを格納するテーブル `subject` とする。指標名は解析者が定める分類の語彙であるため、キーを定義するテーブル `metric` とする。

```yaml
# config/table_schemas/metric.yaml
role: keys
ddl: |
    CREATE TABLE metric (
      metric TEXT PRIMARY KEY,
      unit   TEXT NOT NULL
    );
```

指標の値を格納するテーブルは、`subject` と `metric` の両方を外部キーで参照する。

```yaml
# config/table_schemas/observation.yaml
ddl: |
    CREATE TABLE observation (
      subject TEXT NOT NULL REFERENCES subject (subject),
      trial   TEXT NOT NULL,
      metric  TEXT NOT NULL REFERENCES metric (metric),
      value   DOUBLE NOT NULL,
      PRIMARY KEY (subject, trial, metric)
    );
```

1 つのテーブルのキーは、複数のキーの宣言ファイルに分けて記述できる。この例では、指標を空間的な指標（`config/keys/metrics_spatial.yaml`）と時間的な指標（`config/keys/metrics_temporal.yaml`）に分けて宣言する。分けたファイルは、stage が読み書きするキーを選ぶ単位となる。

### 生データの取り込み

生データを読み取る stage（以下、取り込み stage）は、被験者の一覧と計測機器ごとに作成する。stage 名には `stages/` からのディレクトリの相対パスが用いられるため、`stages/import/subjects/`、`stages/import/force_plate/`、`stages/import/mocap/` のように階層を分けて配置できる。

取り込み stage は、生データのファイルやディレクトリを `path_deps` に宣言する。被験者を追加して生データが変更されると、DVC はその取り込み stage と下流の stage を再実行する。`observation` は `subject` を参照するため、計測機器の取り込み stage は `subject` の artifact を `inputs.tables` に指定する。

```yaml
# stages/import/force_plate/stage.yaml
inputs:
    tables:
        - { stage: import/subjects, out: subjects }
params: {}
path_deps:
    - data/raw/force_plate
outs:
    observations: { path: observations.parquet, table: observation }
```

`run.py` が import するプロジェクト内のモジュール（計測機器のファイル形式を読む関数など）も、`path_deps` に宣言する。staqkit は、`run.py` が読み取るファイルや import するモジュールを自動では追跡しない。

### 同じテーブルへの複数の stage からの出力

2 つの計測機器の取り込み stage は、どちらも `observation` に出力する。下流の stage は、両方の artifact を `inputs.tables` に指定し、1 つのテーブルとして読み取る。

```yaml
# stages/summarize/spatial/stage.yaml
inputs:
    tables:
        - { stage: import/subjects, out: subjects }
        - { stage: import/force_plate, out: observations }
        - { stage: import/mocap, out: observations }
    keys:
        - config/keys/metrics_spatial.yaml
params: {}
outs:
    summary: { path: summary.parquet, table: metric_summary }
```

同じテーブルを出力する artifact の間で、主キーの値が重複してはならない。この例では、2 つの計測機器が異なる指標を出力するように分担する。重複は、両方を読み取る stage の実行時と、`staqkit check` で検出される。

### 見えるキーの絞り込み

stage が読み書きできるキーは、`inputs.keys` に指定したキーの宣言ファイルのキー（以下、見えるキー）に限られる。「同じテーブルへの複数の stage からの出力」の節の `stages/summarize/spatial` は、`metrics_spatial.yaml` だけを指定しているため、次のように動作する。

- `store.query("observation")` は、空間的な指標の行だけを返す。
- 出力するテーブルの `metric` 列に時間的な指標の値を書き出すと、エラーとなる。

時間的な指標を集計する stage は、`metrics_temporal.yaml` を指定する。`inputs.keys` を省略した stage では、すべてのキーの宣言ファイルが見えるキーとなる。

### テーブル以外のファイルの受け渡し

図やレポートのように、テーブルではないファイルも stage の出力にできる。`outs` で `table` を省略して宣言し、`stage.output_path` が返すパスに書き出す。

```yaml
# stages/figures/stage.yaml
inputs:
    tables:
        - { stage: summarize/spatial, out: summary }
params: {}
outs:
    trend: { path: trend.png }
```

別の stage でこのファイルを読み取る場合は、`inputs.files` に名前を付けて指定し、`stage.input_path` でパスを取得する。

```yaml
inputs:
    files:
        trend: { stage: figures, out: trend }
```

## 他の分野での構成

被験者実験と同じ考え方で、他の分野の解析も構成できる。

### 材料試験

引張試験で、試験片ごとの荷重と変位の記録から機械的特性を求める解析の例である。

- キー: 材料の種類、熱処理などの試験条件、特性値の名前（降伏応力、引張強さ、破断伸び）。
- データを格納するテーブル: 試験片の一覧（試験片の寸法と試験条件）、試験片ごとの特性値、試験条件ごとの集計。
- stage: 試験片の一覧の取り込み、試験機の記録の取り込みと特性値の計算、試験条件ごとの集計、図の作成。

試験片は試験の進行に伴って生じる識別子であるため、キーとせず、一覧のファイルから取り込む。特性値の計算に用いるひずみの範囲などの設定値は、`params` に宣言する。値を変更すると、計算する stage と下流の stage が再実行される。

### 機械学習

データセットの前処理、モデルの学習、評価を行う解析の例である。

- キー: データの分割（学習用、検証用、評価用）、評価指標の名前、特徴量の名前。
- データを格納するテーブル: 前処理済みのデータ、学習の記録、評価指標の値。
- stage: データセットの取り込みと分割、前処理、学習、評価、図の作成。

学習率などのハイパーパラメータは `params` に宣言する。学習済みのモデルのようにテーブルではないファイルは、`table` を指定しない出力とし、評価の stage が `inputs.files` で読み取る。

データの分割をキーとし、分割ごとにキーの宣言ファイルを分けておくと、評価の stage は評価用の分割のファイルだけを `inputs.keys` に指定できる。この stage からは、学習用と検証用のデータの行は返されない。

## 日常の作業の流れ

宣言や処理を変更するたびに、次の作業を繰り返す。

1. 宣言ファイルや `run.py` を編集する。
1. `uv run staqkit generate` で `dvc.yaml` を生成し直す。`dvc.yaml` は直接編集しないこと。
1. `uv run dvc repro` で、変更の影響を受ける stage を再実行する。
1. `uv run staqkit check` で、プロジェクト全体の整合性を検査する。
1. 宣言ファイル、`run.py`、`dvc.yaml`、`dvc.lock`、DVC が作成する `.gitignore` を Git にコミットする。`data/stages/` 配下の出力は Git に追加しないこと。

`outs` や `path_deps` の変更は、`staqkit generate` を実行するまで `dvc.yaml` に反映されない。`staqkit generate` の実行を省くと、`dvc repro` は変更を検知しない。生成し直していない状態は、`staqkit check` で検出される。
