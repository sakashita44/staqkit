# ステージ

## stage.yaml 仕様

各ステージの定義ファイル。パラメータ・入力仕様・説明を1ファイルに集約する。

```yaml
# stages/detect_cog_event/stage.yaml

desc: "COG軌跡・速度を基準にPGTイベントを検出"

status: active # active | planned | inactive

outs:
    timeseries:
        path: timeseries.parquet
        add_datastore: true
    dtype:
        path: dtype.parquet
        add_datastore: true
    summary_figure:
        path: figures/summary.png
        add_datastore: false

params:
    cog_pgt_threshold: 50
    cog_vel_thresholds: [100, 70, 50, 30, 0]

inputs:
    - source_stage: compute_cog_velocity
      query_args:
          data_group: cog
          quantity_type: velocity

extra_deps:
    raw_data: data/raw/motion
```

### セクションの役割

| セクション | 役割                                          | DVC連携                                                     |
| ---------- | --------------------------------------------- | ----------------------------------------------------------- |
| desc       | ステージの1行説明                             | dvc.yaml の desc フィールドに転記                           |
| status     | ステージの状態（active / planned / inactive） | planned は data/ 側未生成。inactive は下流に伝搬            |
| outs       | 全出力宣言（path + add_datastore フラグ）     | dvc.yaml の outs: に展開。上流の outs は下流の deps: に展開 |
| params     | 処理の振る舞い制御値                          | dvc.yaml の params: で追跡                                  |
| inputs     | 上流データの利用範囲                          | dvc.yaml の params: で追跡（概念的にはparamsと独立）        |
| extra_deps | DAG外の外部ファイル/ディレクトリ依存          | dvc.yaml の deps: に展開                                    |

### outs 統一スキーマ

全出力を `outs` セクションに統一する。各エントリは `path`（出力先）と `add_datastore`（DataStore VIEW への統合有無）を持つ。

```yaml
outs:
    <key>:
        path: <相対パス> # 必須。末尾 / でディレクトリ出力
        add_datastore: <bool> # 必須。true → DataStore VIEW に統合
```

- 展開先: `data/stages/{name}/{path}`
- key はプログラム上の識別子（`ctx.out_path("<key>")` でパス解決）。ファイル名ステムとの一致を推奨
- DataStore VIEW のテーブル名はファイル名ステムから導出（例: `timeseries.parquet` → `timeseries` VIEW）
- 将来の拡張（`cache: false` 等）は value オブジェクトにフィールド追加で対応

バリデーション規則:

- `add_datastore: true` かつ拡張子 ≠ `.parquet` → エラー
- `add_datastore: true` かつディレクトリ（末尾 `/`）→ エラー
- key とファイル名ステムの不一致 → warning

### params と inputs の概念的区別

- **params**: 上流ノードの知識なしに記述可能な処理制御値。変更 → 再計算
- **inputs**: 上流ノードの属性構造に依存する参照情報。変更 → 依存の意味が変わる

DVC の params 追跡機構を共有しつつ、概念的区別は stage.yaml 内のセクション分離で表現する。

### inputs: query_args 方式

`query_args` は DataStore.query() のキーワード引数と構造的に対応する。処理関数で `store.query(**spec['query_args'])` と書けば、stage.yaml と実装が構造的に一致する。

- 既存の query API の引数仕様をそのままYAMLに書く。新たなDSL設計が不要
- query API の進化に inputs が自動追従する
- DVC params 追跡: `query_args.data_group` 単位で変更検知可能

### extra_deps: DAG外の外部依存

自動導出されるdeps（run.py・上流outs・table_schemas）に該当しない外部ファイルやディレクトリを明示的に宣言する。

```yaml
extra_deps:
    raw_data: data/raw/motion # ディレクトリ指定
    calibration: data/raw/calibration.csv # ファイル指定
    lib_utils: lib/signal_utils.py # 共有スクリプト
```

- globパターン（`*`, `?` 等を含む値）はジェネレータがPythonの `glob.glob()` で展開
- ディレクトリ指定はDVCネイティブの挙動（中のファイル全体をハッシュ追跡）
- dvc.yaml の deps のみに展開。params には含めない

解析コードからは `ctx.extra_dep("<key>")` でパスを解決する。stage.yaml がパス定義のSSoTであり、DVC deps と解析コードの両方が同一の値を参照する。

```python
def run(ctx: StageContext):
    raw_dir = ctx.extra_dep("raw_data")      # → Path("data/raw/motion")
    cal_file = ctx.extra_dep("calibration")   # → Path("data/raw/calibration.csv")
```

## ステージ状態管理

### active / planned / inactive

- **active**: 実装済み・データ生成可能。dvc.yaml に含まれる
- **planned**: 定義のみ。`data/stages/xxx/` は存在しないか空。DAGマップで点線表示
- **inactive**: 休止中。dvc.yaml に含めない。既存データは保持されるが再実行対象外

### inactive 伝搬と suppressed 状態

あるステージが inactive になった場合、そのステージに依存する下流ステージも全て自動的に除外される。

- dvc.yaml 生成時にDAGグラフを走査し、inactive ステージの下流を検出
- 伝搬は dvc.yaml 生成の論理で処理（stage.yaml 自体は書き換えない）
- 上流が active に戻れば、下流も自動的に復帰

#### 宣言的状態と実効状態

- **宣言的状態**: stage.yaml の `status` フィールド。ユーザーの意図を表す（SSoT）
- **実効状態（effective status）**: 宣言的状態 + 上流の状態から導出。dvc.yaml 包含判定に使用
- **suppressed**: 自身の宣言的状態は active だが、上流に inactive があるため dvc.yaml から除外されている状態

### planned 状態の活用

issue駆動開発（最終成果物から逆算してノードを定義 → 順次実装）を支援する。

- DataStore は `stages/*/stage.yaml`（定義）と `data/stages/*/`（実データ）を分けて認識
- ディレクトリ構成が状態表現を自然に担う: **定義の存在 ≠ データの存在**

planned 段階で書ける情報:

- **dtype.parquet**: dkey の属性定義は実装前に書ける（出力IFの事前定義）
- **stage.yaml の outs**: 出力予定テーブル一覧
- **データテーブル**: データ実体がないので未生成

### 孤児データの管理

```bash
sard clean              # 孤児・inactive データを検出して一覧表示
sard clean --remove     # 確認の上、実際に削除
```

検出対象:

- `data/stages/xxx/` が存在するが対応する `stage.yaml` がない → 孤児
- `data/stages/xxx/` が存在し、status が inactive → 休止中データ

## ステージ出力の構成

各DVCステージは `data/stages/xxx/` 配下にテーブル名.parquet 形式でファイルを出力する。

| ファイル               | 内容                                                                      | 備考                                    |
| ---------------------- | ------------------------------------------------------------------------- | --------------------------------------- |
| `<table_name>.parquet` | データ本体                                                                | 1ステージが複数テーブルを出力可         |
| `dtype.parquet`        | このステージが生成した dkey 行。新規 dkey を生成しないステージは0行を出力 | StageContext が書き込み完了時に自動生成 |

## dtype レジストリ管理

dtype はデータとセットで生まれるもの。各ステージが出力し、DataStore で統合する。dtype.parquet を各ステージの出力として配置することで、「このステージが何を生成するか」が自己完結的にわかる局所性を優先する。「存在しないdkeyへの参照」は実行するまで検出できないトレードオフを受容する。

```text
data/stages/import/dtype.parquet        ← import ステージが出力
data/stages/normalize/dtype.parquet     ← normalize ステージが出力
docs/dtype_catalog.md                   ← 閲覧専用、自動更新、Git管理
```

- SSoT は各ステージの出力（dtype.parquet）であり、静的な設定ファイルではない
- DataStore コンストラクタで全ステージの dtype.parquet を UNION ALL して VIEW 化
- dkey の重複チェック（複数ステージで同一 dkey 定義 → 警告）
- `docs/dtype_catalog.md` は `sard catalog` コマンドで自動生成

### DAG循環の回避

「処理関数はメタデータを読まない」原則:

- 各ステージの処理関数は、自分が出力するデータとメタデータのみに責任を持つ
- 上流の dtype.parquet は DVC の `deps:` に含めてよい（循環しないため）
- メタデータの統合は DataStore が読み取り時に行う（UNION ALL）

## run_meta.yaml（実行記録）

ステージ実行時に自動生成される自己完結型の実行記録。**Git管理**（`stages/` 配下に配置。dvc.yaml の outs/deps からは除外）。

```yaml
# stages/normalize/run_meta.yaml
run_id: "20250320T143000_a1b2c3"
executed_at: "2025-03-20T14:30:00+09:00"

# プロヴェナンス（依存ステージの実行ID）
deps_runs:
    import: "20250319T100000_d4e5f6"
    compute_cog_velocity: "20250320T120000_g7h8i9"

# 実行時パラメータスナップショット
params:
    cog_pgt_threshold: 50
    cog_vel_thresholds: [100, 70, 50, 30, 0]
inputs:
    - source_stage: compute_cog_velocity
      query_args:
          data_group: cog
          quantity_type: velocity

# 実行結果サマリ
dkeys: [cog_x, cog_y, cog_velocity]
row_counts:
    timeseries: 128000
    dtype: 6

# データハッシュ（実行事実の記録）
input_hashes:
    data/stages/import/timeseries.parquet: "md5:abc123..."
    data/stages/import/dtype.parquet: "md5:def456..."
output_hashes:
    data/stages/normalize/timeseries.parquet: "md5:mno345..."
    data/stages/normalize/dtype.parquet: "md5:pqr678..."
    data/stages/normalize/run_meta.yaml: null # 自身は除外（循環回避）
```

### フィールド仕様

- **`run_id`**: この実行の一意識別子（タイムスタンプ + 短縮ハッシュ or UUID）
- **`executed_at`**: 実行日時（ISO-8601）
- **`deps_runs`**: 依存ステージ名 → その時点の run_id。実行時に上流の run_meta.yaml から読み取って記録
- **`params` / `inputs`**: 実行時のパラメータスナップショット。stage.yaml は「現在の定義」、run_meta は「実行時の実値」
- **`dkeys`**: このステージが出力した dkey の一覧
- **`row_counts`**: テーブルごとの出力行数
- **`input_hashes` / `output_hashes`**: 実行時に自前でmd5を計算。dvc.lockとは独立した実行事実の記録

### Git管理の利点

- `dvc repro` の影響を受けない（実行記録が再実行で上書きされてもGit履歴に残る）
- run_idベースの時系列追跡が `git log -S <run_id>` で可能
- commit単位でrun_metaの変遷を追える

### dvc.lock との役割分離

- **dvc.lock**: 「各ファイルの現在期待されるハッシュは何か」 — 宣言的（現在の期待状態）
- **run_meta**: 「このステージはいつ・何で・どう実行されたか」 — 事実的（実行時の記録）

### プロヴェナンスチェーン

`deps_runs` により実行系譜を再帰的に辿れる。上流の run_meta.yaml を読むのはDAGの順方向であり、循環は生じない。

### CLIラッパー

- `sard history <stage>`: 過去の run_meta 一覧表示
- `sard provenance <stage>`: プロヴェナンスチェーン表示

内部的には `git log` をラップするだけで、独自の履歴DBは持たない。

## description 3層構造

| 層      | 粒度     | 格納先                        | 内容                                 |
| ------- | -------- | ----------------------------- | ------------------------------------ |
| Layer 1 | 1行      | stages/xxx/stage.yaml の desc | 何をするか                           |
| Layer 2 | 段落     | stages/xxx/README.md          | アルゴリズム説明、既知の制限、注意点 |
| Layer 3 | 外部参照 | README.md 内のリンク          | 設計経緯（研究ノート等）             |

README に書くもの: アルゴリズムの説明、ドメイン固有のロジック、設計経緯の短縮版、既知の制限・注意点

README に書かないもの（他所がSSoT）: パラメータ値（→ stage.yaml）、入出力ファイル（→ dvc.yaml）、前後のステージ（→ `sard dag`）
