# ディレクトリ構成

## 全体構造

ステージ単位ディレクトリ + 定義/成果物の分離:

```text
config/                      ← Git管理（プロジェクト設定）
  project.yaml
  axes.yaml                  ← 識別軸定義
  table_schemas/
    timeseries.yaml          ← テーブルごとのカラム定義
    record.yaml
    dtype.yaml

stages/                      ← Git管理（定義側）。再帰走査
  import/                    ← グループ（stage.yaml なし）
    raw_motion/              ← ステージ "import/raw_motion"
      run.py                 ← エントリポイント
      stage.yaml             ← params + inputs + desc
      run_meta.yaml          ← Git管理（実行記録）
      README.md              ← アルゴリズム説明
    raw_force/
      run.py
      stage.yaml
      README.md
  normalize/
    run.py                   ← フラットステージも共存可
    stage.yaml
    README.md

data/                        ← DVC管理（成果物側）
  raw/                       ← ソースデータ（ステージ生成物ではない）
    motion/                  ← 計測機器からの生データ等
    calibration.csv
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
  external/                  ← 外部staqkitリポジトリからのimportデータ
    <source>/
      <stage>/
        ...
```

## 分離の根拠

- **管理境界の明確化**: コード・設定はGit、データ成果物はDVC。混在ディレクトリだと `.gitignore` / `.dvcignore` が煩雑
- **クリーンビルド**: `data/stages/` を丸ごと削除 → `dvc repro` で再生成が自然に可能
- **dvc.yamlの位置づけ**: `stages/*/stage.yaml` 群から動的生成される派生物。stage.yaml がSSoT

## ネストディレクトリ

ステージ数が増えた場合の一覧性確保のため、ディレクトリのネストを許容する。

- **ステージ名** = `stages/` からの相対パス（例: `import/raw_motion`）
- **ステージ判定**: `stage.yaml` が存在するディレクトリがleafステージ。それ以外は純粋なグルーピング
- **禁止ルール**: stage.yaml を持つディレクトリの下にサブステージ不可（ステージかつグループは不可）
- **data/ ミラー**: `data/stages/import/raw_motion/timeseries.parquet`（stages/ 以下をそのまま反映）
- **参照形式**: `source_stage: import/raw_motion`（パス形式）
- **発見**: `stages/**/stage.yaml` を再帰走査。フラットとネストが共存可能
