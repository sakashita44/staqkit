# ディレクトリ構成

## 全体構造

ステージ単位ディレクトリ + 定義/成果物の分離:

```text
config/                      ← Git管理（プロジェクト設定）
  table_schemas/             ← テーブルごとのスキーマ定義（サブディレクトリ許容）
    timeseries.yaml
    record.yaml
    meta/                    ← サブディレクトリによる整理（テーブル名はファイル名で決まる）
      dtype.yaml

params/                      ← Git管理（パラメータ値）。推奨配置（強制ではない）
  motion.yaml                ← DVC ネイティブの params ファイル
  detect.yaml
  normalize.yaml

stages/                      ← Git管理（定義側）。再帰走査
  import/                    ← グループ（stage.yaml なし）
    raw_motion/              ← ステージ "import/raw_motion"
      run.py                 ← エントリポイント
      stage.yaml             ← params 参照 + inputs + desc
      README.md              ← アルゴリズム説明
    raw_force/
      run.py
      stage.yaml
      README.md
  normalize/
    run.py                   ← フラットステージも共存可
    stage.yaml
    README.md

libs/                        ← Git管理（共有コード）。複数ステージから参照
  signal_utils.py
  sim-model/                 ← submodule（外部リポジトリのコード/データ）

data/                        ← DVC管理（成果物側）
  stages/                    ← ステージ出力。stages/ をミラー
    import/
      raw_motion/
        timeseries.parquet   ← テーブル名.parquet
        record.parquet
        dtype.parquet
      raw_force/
        ...
    normalize/
      timeseries.parquet
      ...
  external/                  ← DAG 外のソース（どのステージも生成しない）
    raw/                     ← ローカル生データ（計測機器からの出力等）
      motion/
      calibration.csv
    <repo>/                  ← 別リポジトリから dvc import したデータ
```

## 分離の根拠

- **管理境界の明確化**: コード・設定はGit、データ成果物はDVC。混在ディレクトリだと `.gitignore` / `.dvcignore` が煩雑
- **クリーンビルド**: `data/stages/` を丸ごと削除 → `dvc repro` で再生成が自然に可能
- **dvc.yamlの位置づけ**: `stages/*/stage.yaml` 群から動的生成される派生物。stage.yaml がSSoT

## 固定パスと参考配置

構成図のパスは2種に分かれる。staqkit が場所・名前を前提に走査・導出するものは固定であり、それ以外は staqkit が宣言されたパスを解決するだけで配置を強制しない。

### 固定パス（規約契約）

staqkit が走査・ミラー・呼び出しの起点とするため、配置と名前を規約として固定する。

- `stages/` と各ステージの `stage.yaml` / `run.py`: ステージ発見は `stages/**/stage.yaml` の再帰走査、実行は `python stages/<stage>/run.py`。ディレクトリ名・ファイル名で位置と入口が決まる。
- `config/table_schemas/` と配下の `*.yaml`: スキーマ発見は `config/table_schemas/**/*.yaml` の再帰走査。テーブル名はファイルステムで決まる。
- `data/stages/<stage>/`: 出力先をステージ名から機械的に導出する（`stages/` のミラー）。

プロジェクト全体設定（`validation` 等）の置き場・既定値は [#26](https://github.com/sakashita44/staqkit/issues/26) で確定する。

### 参考配置

staqkit は `extra_deps` や params 束縛が宣言したパスをリポジトリルート相対で解決するだけで、これらの場所を前提にしない。配置は変更可能であり、構成図が示す位置は一覧性のための参考にすぎない。

- `libs/`: 共有コード。`extra_deps` が任意パスで宣言する（[libs](#libs共有コード)）。
- params ファイル（`params/` 等）: stage.yaml の束縛が指すパスを解決する（[params](#paramsパラメータ値)）。
- `data/external/`: DAG にとって外部のソース（どのステージも生成せず、取り込みステージが消費する）。ローカル生データも別リポジトリからの dvc import も同一カテゴリで、来歴強度のみが異なる（[external-data.md](components/external-data.md)）。
- ステージ直下の `README.md`: アルゴリズム説明。staqkit は要求も走査もしない。

## ネストディレクトリ

### table_schemas

`config/table_schemas/` はサブディレクトリによる整理を許容する。走査は `config/table_schemas/**/*.yaml` の再帰。

- テーブル名 = ファイル名（ステム）。ディレクトリパスは名前に含めない（DDL の `CREATE TABLE <name>` と一致させるため）
- 同名ファイルが異なるサブディレクトリに存在 → エラー（一意性違反）

### stages

ステージ数が増えた場合の一覧性確保のため、ディレクトリのネストを許容する。

- **ステージ名** = `stages/` からの相対パス（例: `import/raw_motion`）
- **ステージ判定**: `stage.yaml` が存在するディレクトリがleafステージ。それ以外は純粋なグルーピング
- **禁止ルール**: stage.yaml を持つディレクトリの下にサブステージ不可（ステージかつグループは不可）
- **data/ ミラー**: `data/stages/import/raw_motion/timeseries.parquet`（stages/ 以下をそのまま反映）
- **参照形式**: `source_stage: import/raw_motion`（パス形式）
- **発見**: `stages/**/stage.yaml` を再帰走査。フラットとネストが共存可能

## libs（共有コード）

複数ステージから参照する共有コード（ユーティリティ、シミュレーションモデル等）を置く。Git 管理。

- ステージは `extra_deps` で `libs/...` を宣言して依存追跡する（[stage.md](components/stage.md#extra_deps-dag外の外部依存)）。変更は DVC が下流を無効化する。
- 外部リポジトリで管理するコード/データは git submodule として `libs/<name>/` に配置できる。submodule コミットの更新が `extra_deps` 経由で DVC の変更検知に連動する。submodule を「生きたコード・データの共有」に使うのは、雛形コピー用途（不採用）とは別の用途であり distribution.md と整合する（[distribution.md](distribution.md#雛形と改善の伝播)）。

## params（パラメータ値）

パラメータの値は DVC ネイティブの params ファイル（任意の YAML）に置き、stage.yaml の `params` がローカル名から `{ file, key }` を束縛する（[stage.md](components/stage.md#params外部ファイル参照)）。

- **配置は staqkit が規定しない**。`params/` への集約は一覧性のための参考配置であり、強制ではない。stage.yaml の束縛が指すパス（リポジトリルート相対）を DVC が読めれば、配置はどこでもよい。
- staqkit が前提とするのは「束縛に書かれたパスをリポジトリルート相対で解決する」一点のみ。ステージごとの相対パスは生じない。
