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
| inputs     | 依存先ステージの宣言                          | dvc.yaml の params: + deps: で追跡                          |
| extra_deps | DAG外の外部ファイル/ディレクトリ依存          | dvc.yaml の deps: に展開                                    |

### outs 統一スキーマ

全出力を `outs` セクションに統一する。各エントリは `path`（出力先）と `add_datastore`（DataStore の VIEW（クエリエンジン上の仮想テーブル）への統合有無）を持つ。

```yaml
outs:
    <key>:
        path: <相対パス> # 必須。末尾 / でディレクトリ出力
        add_datastore: <bool> # 必須。true → DataStore VIEW に統合
```

- 展開先: `data/stages/{name}/{path}`
- key はプログラム上の識別子（`stage.out_path("<key>")` でパス解決）。ファイル名ステムとの一致を推奨
- DataStore VIEW のテーブル名はファイル名ステムから導出（例: `timeseries.parquet` → `timeseries` VIEW）
- 将来の拡張（`cache: false` 等）は value オブジェクトにフィールド追加で対応

各エントリは `OutsEntry`（frozen dataclass）として型付けし、key を内包して自己完結させる。

```python
@dataclass(frozen=True)
class OutsEntry:
    key: str            # outs の辞書キー。プログラム上の識別子
    path: Path          # data/stages/{name}/ からの相対パス
    add_datastore: bool

    @property
    def table_name(self) -> str:
        """DataStore VIEW のテーブル名。add_datastore: true の場合のみ意味を持つ"""
        return self.path.stem
```

`StageDefinition.outs` は `list[OutsEntry]` として保持し、key の一意性はパース時に検証する。key（プログラム上の識別子）と `table_name`（VIEW 名 = ステム）を分離するのは、テーブルとそれに対応する非テーブル出力（同じステムを持つ図など）を同一ステージから出力する場合にステムが衝突しうるためである。

バリデーション規則:

- `add_datastore: true` かつ拡張子 ≠ `.parquet` → エラー
- `add_datastore: true` かつディレクトリ（末尾 `/`）→ エラー
- key とファイル名ステムの不一致 → warning

### params と inputs の関心の分離

| 依存の種類                                   | 宣言場所          | DVC 追跡経路        |
| -------------------------------------------- | ----------------- | ------------------- |
| どのステージに依存するか（DAG 構造）         | stage.yaml inputs | params + deps       |
| パラメトリックな制御値                       | stage.yaml params | params              |
| どのデータをどう取得するか（クエリロジック） | run.py            | deps（run.py 変更） |

- **params**: 上流ノードの知識なしに記述可能な処理制御値。変更 → 再計算
- **inputs**: 依存先ステージ名（`source_stage`）のみ宣言。DAG の辺の宣言 + DVC params 追跡の2つの役割を持つ
- クエリ条件は run.py 内で開発者が直接記述する。フィルタ条件をパラメータとして変更可能にしたい場合は params に書き、run.py 内で `stage.params` 経由で使用する

### inputs の形式

```yaml
inputs:
    - source_stage: D
    - source_stage: X
```

```python
def run(stage: StageInfo, store: DataStore):
    cog = store.query("timeseries", {"dkey": stage.params["target_dkeys"]})
    force = store.query("timeseries", {"dkey": ["force_x", "force_y"]})
    dtypes = store.query("dtypes")
    result = process(cog, force, dtypes, **stage.params)
    store.write_table("result", result)
```

inputs の役割:

| 役割            | 仕組み                                         |
| --------------- | ---------------------------------------------- |
| DAG の辺の宣言  | source_stage → pipeline-gen が deps を自動導出 |
| DVC params 追跡 | source_stage の追加・削除で再実行トリガー      |

### DataStore スコープと status の関係

| status  | inputs                | DataStore スコープ                     | dvc.yaml |
| ------- | --------------------- | -------------------------------------- | -------- |
| planned | 未記述                | 全データ（末端相当）                   | 含めない |
| planned | source_stage 記述済み | 絞らない（DAG 可視化のみに使用）       | 含めない |
| active  | 記述済み              | 宣言した source_stage 群の全上流に限定 | 含む     |
| active  | 未記述                | 空（DataStore へのアクセス時にエラー） | 含む     |

- active かつ inputs 未記述の場合、DataStore にデータが登録されないため、クエリ実行時にエラー。inputs 不要でクエリも行わないステージ（外部データの取り込み等）は正常に実行される
- planned + inputs 未記述 → DAG 上で浮いた位置に表示
- planned + source_stage 記述済み → その先に点線で表示（スコープは絞らない）

### active が planned を参照した場合

active ステージが inputs の source_stage で planned ステージ（データ実体なし）を参照する状態は、「実行可能なステージが未実装の依存に依存する」設計矛盾を表す。検査は実際に実行されるステージ（effective-active）に対してのみ発火する。ここで effective-active とは宣言 active かつ [suppressed](#宣言的状態と実効状態) でない状態を指し、dvc.yaml に含まれないステージ（planned・inactive・suppressed）は発火対象から外れる。したがって planned から planned への参照は対象外となる（DAG 可視化目的の参照として許容する）。これは特例ではなく、同一ルールが「実行されないステージには発火しない」帰結である。

- `staqkit validate`（設計時レビュー）: 警告。issue 駆動開発で下流を先に定義し上流を順次実装する途中段階を許容し、編集を止めない
- `staqkit repro`（実行ゲート）: エラー。planned の参照先 outs は実体がなく active ステージは実行できないため、DVC 呼び出し前に `ReferenceIntegrityError` で停止する

この段階差は[アクセス経路の保証グラデーション](../architecture.md#守る契約とアクセス経路の保証グラデーション)と同じ思想であり、設計時は緩く、実行時に硬く扱う。

planned を参照する active が repro でエラー停止するのに対し、inactive を参照する active は [inactive 伝搬](#inactive-伝搬と-suppressed-状態)で suppressed となり、エラーにならず dvc.yaml から静かに除外される。この非対称は、inactive が「意図的な休止（上流を active に戻せば下流も自動復帰）」を表すのに対し、planned は「未実装（参照先の実体がそもそも存在しない）」を表すという意味の違いに由来する。前者は復帰可能な一時状態として伝搬で扱い、後者は依存の欠落として実行時に顕在化させる。

### source_stage 指定漏れの既知の限界

source_stage の指定漏れは「データの不在」ではなく「データの不足」を引き起こす。スコープ内のデータだけでクエリが成功し、エラーなく処理が完了するが、本来必要なデータが静かに欠落した不完全な結果が出力される可能性がある。

これは「何が必要か」が解析者の頭の中にしかない問題であり、inputs の形式をどう変えても解決しない種類の問題として受容する。ステージを適切な粒度で設計すること、DAG 図で依存経路の欠落を視覚的に確認すること、run.py で明示的にクエリを書いて結果を確認することが軽減策となる。

将来的に `staqkit lint` 等で「run.py 内の query 呼び出しで参照するテーブル名」と「inputs の source_stage が提供するテーブル名」の突合チェックを提供できれば、静的に検出可能なケースは拾える。

### extra_deps: DAG外の外部依存

自動導出されるdeps（run.py・上流outs・table_schemas）に該当しない外部ファイルやディレクトリを明示的に宣言する。

```yaml
extra_deps:
    raw_data: data/raw/motion # ディレクトリ指定
    calibration: data/raw/calibration.csv # ファイル指定
    lib_utils: lib/signal_utils.py # 共有スクリプト
```

- globパターン（`*`, `?` 等を含む値）はジェネレータがPythonの `glob.glob()` で展開
- glob パターンが 0 件マッチの場合はエラー（`ConfigError`）。リテラルパスの不在は DVC が deps 不在として検出するが、glob は展開結果が空になるとジェネレータが何も出力せず DVC からは見えないため、依存欠落を静かに見逃さないよう生成時に検出する
- ディレクトリ指定はDVCネイティブの挙動（中のファイル全体をハッシュ追跡）
- dvc.yaml の deps のみに展開。params には含めない

解析コードからは `stage.extra_dep("<key>")` でパスを解決する。stage.yaml がパス定義のSSoTであり、DVC deps と解析コードの両方が同一の値を参照する。StageInfo・DataStore の定義は[実行モデル](#実行モデル)を参照。

```python
def run(stage: StageInfo, store: DataStore):
    raw_dir = stage.extra_dep("raw_data")      # → Path("data/raw/motion")
    cal_file = stage.extra_dep("calibration")   # → Path("data/raw/calibration.csv")
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

- **stage.yaml の outs**: 出力予定テーブル一覧
- **テーブルデータ**: `add_datastore: true` のテーブルは実装前に手動配置可能（出力IFの事前定義）
- **データテーブル**: データ実体がないので未生成

### 孤児データの管理

```bash
staqkit clean              # 孤児・inactive データを検出して一覧表示
staqkit clean --remove     # 確認の上、実際に削除
```

検出対象:

- `data/stages/xxx/` が存在するが対応する `stage.yaml` がない → 孤児
- `data/stages/xxx/` が存在し、status が inactive → 休止中データ

## ステージ出力の構成

各DVCステージは `data/stages/xxx/` 配下にファイルを出力する。`add_datastore: true` のファイルは DataStore の VIEW に統合される。1ステージが複数テーブルを出力可能。

## 分散テーブルの統合

同名テーブルを複数ステージが出力するパターンがある。DataStore はこれらを UNION ALL で1つの VIEW に統合する。

```text
data/stages/import/timeseries.parquet       ← import ステージが出力
data/stages/normalize/timeseries.parquet    ← normalize ステージが出力
→ DataStore: timeseries VIEW（UNION ALL）
```

- SSoT は各ステージの出力ファイルであり、静的な設定ファイルではない
- `config/table_schemas/` の [DDL 定義](datastore.md#テーブル結合のスキーマ契約)に基づき、UNION ALL 後のキー一意性等を検証
- カタログ出力: `staqkit catalog` で対象テーブルの内容を一覧表示（詳細は [CLI リファレンス](cli.md#staqkit-catalog) を参照）

### DAG循環の回避

「処理関数は他ステージのメタデータを読まない」原則:

- 各ステージの処理関数は、自分が出力するデータのみに責任を持つ
- 上流ステージの出力は DVC の `deps:` に含めてよい（循環しないため）
- テーブルの統合は DataStore が読み取り時に行う（UNION ALL）

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

# 実行結果サマリ
row_counts:
    timeseries: 128000

# データハッシュ（実行事実の記録）
input_hashes:
    data/stages/import/timeseries.parquet: "md5:abc123..."
output_hashes:
    data/stages/normalize/timeseries.parquet: "md5:mno345..."
    data/stages/normalize/run_meta.yaml: null # 自身は除外（循環回避）
```

### フィールド仕様

- **`run_id`**: この実行の一意識別子。`<YYYYMMDDThhmmss>_<短縮サフィックス>` 形式（例: `20250320T143000_a1b2c3`）。時系列ソート可能・人間可読・`git log -S <run_id>` での検索容易を満たす。短縮サフィックスは同一秒内の衝突を避けるためのランダム値（生成時の乱数を数桁に短縮）であり、実行内容から導出する決定的ハッシュではない。run_meta は run_id・executed_at を含む非決定的な実行記録であり、来歴の同一性照合は実行内容由来の `deps_runs` / `input_hashes` が担う
- **`executed_at`**: 実行日時（ISO-8601）
- **`deps_runs`**: 依存ステージ名 → その時点の run_id。実行時に上流の run_meta.yaml から読み取って記録
- **`params` / `inputs`**: 実行時のパラメータスナップショット。stage.yaml は「現在の定義」、run_meta は「実行時の実値」
- **`row_counts`**: テーブルごとの出力行数
- **`input_hashes` / `output_hashes`**: 実行時に自前でmd5を計算。dvc.lockとは独立した実行事実の記録

### Git管理の利点

- `dvc repro` の影響を受けない（実行記録が再実行で上書きされてもGit履歴に残る）
- run_idベースの時系列追跡が `git log -S <run_id>` で可能
- commit単位でrun_metaの変遷を追える

### dvc.lock との役割分離

- **dvc.lock**: 「各ファイルの現在期待されるハッシュは何か」 — 宣言的（現在の期待状態）
- **run_meta**: 「このステージはいつ・何で・どう実行されたか」 — 事実的（実行時の記録）

### データ実体との独立性

run_meta は実行事実の記録であり、データ実体への依存を持たない。データ実体が消えていても（DVC キャッシュクリーンアップ、DVC remote アクセス不可、過去 commit の参照等）、git に残った run_meta から「いつ・何のパラメータで・どの上流実行から生成されたか」を完全に追跡できる。

dvc.lock がデータ実体への参照（ファイルハッシュ）であるのに対し、run_meta は実行事実の独立記録として機能する。両者は補完関係にあり、

- データ実体の整合性確認 → dvc.lock
- 来歴・パラメータ・行数の追跡 → run_meta

外部から `staqkit import` で取り込んだデータについても、出典元リポジトリを clone すれば run_meta が取得でき、DVC remote へのアクセスなしに git のみで来歴文書として参照可能。

### プロヴェナンスチェーン

`deps_runs` により実行系譜を再帰的に辿れる。上流の run_meta.yaml を読むのはDAGの順方向であり、循環は生じない。

### CLIラッパー

- `staqkit history <stage>`: 過去の run_meta 一覧表示
- `staqkit provenance <stage>`: プロヴェナンスチェーン表示

内部的には `git log` をラップするだけで、独自の履歴DBは持たない。

## description 3層構造

| 層      | 粒度     | 格納先                        | 内容                                 |
| ------- | -------- | ----------------------------- | ------------------------------------ |
| Layer 1 | 1行      | stages/xxx/stage.yaml の desc | 何をするか                           |
| Layer 2 | 段落     | stages/xxx/README.md          | アルゴリズム説明、既知の制限、注意点 |
| Layer 3 | 外部参照 | README.md 内のリンク          | 設計経緯（研究ノート等）             |

README に書くもの: アルゴリズムの説明、ドメイン固有のロジック、設計経緯の短縮版、既知の制限・注意点

README に書かないもの（他所がSSoT）: パラメータ値（→ stage.yaml）、入出力ファイル（→ dvc.yaml）、前後のステージ（→ `staqkit dag`）

## 実行モデル

### 構成要素

ステージの実行は3つの要素で構成される。

| 要素              | 種別             | 責務                                                                                   |
| ----------------- | ---------------- | -------------------------------------------------------------------------------------- |
| StageInfo         | frozen dataclass | stage.yaml パース結果 + パス解決済みランタイム情報。params, out_path(), extra_dep() 等 |
| DataStore         | クラス           | 読み書き + バリデーションの単一アクセスポイント                                        |
| run_stage(run_fn) | 関数             | ブートストラップ → run_fn(stage, store) → エピローグ                                   |

補助的なデータクラス:

- **StageDefinition**: stage.yaml の型付き表現（StageInfo の構築元）
- **OutsEntry**: outs の各エントリの型付き表現（[outs 統一スキーマ](#outs-統一スキーマ)）
- **RunMeta**: 実行記録（run_stage のエピローグで生成）
- **TableSchema**: テーブル定義（カラム・型・制約・カタログ出力設定）

StageDefinition は stage.yaml をパースした frozen dataclass であり、次のフィールドを持つ。ステージ走査（`discover_stages`）が `list[StageDefinition]` を返し、グラフ操作（パイプライン生成・参照整合性検査）はパス解決を伴わない本表現を用いる。

| フィールド | 内容                                   | 由来                    |
| ---------- | -------------------------------------- | ----------------------- |
| name       | ステージ名（`stages/` からの相対パス） | ディレクトリ位置        |
| desc       | 1行説明                                | stage.yaml `desc`       |
| status     | active / planned / inactive            | stage.yaml `status`     |
| outs       | `list[OutsEntry]`                      | stage.yaml `outs`       |
| params     | パラメータ辞書                         | stage.yaml `params`     |
| inputs     | source_stage のリスト                  | stage.yaml `inputs`     |
| extra_deps | key → パスの辞書                       | stage.yaml `extra_deps` |

StageInfo は StageDefinition に [ProjectLayout](../architecture.md#projectlayout) を束ねた実行時ビューであり、`out_path()` / `extra_dep()` 等のパス解決を ProjectLayout へ委譲する。単一ステージの run.py 文脈に注入されるのは StageInfo、グラフ走査に用いるのは StageDefinition、と用途で使い分ける。

StageInfo は status によって挙動を変えない。planned/active の区別はオーケストレーション層（dvc.yaml 生成時に planned ステージを除外する等）の責務である。

### run.py エントリポイント規約

DVC は `python stages/X/run.py` で各ステージを呼び出す。`run_stage` は自身のディレクトリから stage.yaml を読み、StageInfo を構築し、スコープ解決ファクトリ（`open_store`）で DataStore を組み立てて処理関数に注入する。run.py が制御を `run_stage` に渡す制御反転（IoC）の形を採る。

```python
from staqkit import run_stage
from staqkit.types import StageInfo, DataStore

def run(stage: StageInfo, store: DataStore):
    df = store.query("timeseries", {"subject_id": [1, 2]})
    result = normalize(df, **stage.params)
    store.write_table("timeseries", result)

if __name__ == "__main__":
    run_stage(run)
```

`store.query` が契約検証つきの祝福されたメイン経路、`store.fetch` が生 SQL の抜け道である（保証の差は [datastore.md](datastore.md#読み取り-api)）。

### post-run 検証

run_stage のエピローグで実施する検証。

| 検証項目                                 | 担当                  | タイミング                                     |
| ---------------------------------------- | --------------------- | ---------------------------------------------- |
| outs の変更追跡（ハッシュベース）        | DVC                   | dvc repro / dvc status                         |
| スキーマ整合性（カラム構成 vs DDL 定義） | DataStore write_table | 書き込み時（on_write バリデーション）          |
| 未生成ファイル（declared − actual）      | run_stage エピローグ  | ステージ実行後 → 例外 → DVC 停止               |
| 未宣言ファイル（actual − declared）      | run_stage エピローグ  | ステージ実行後 → 警告（config で例外昇格可能） |

- エピローグの例外は Python プロセスの非ゼロ終了コードとなり、DVC がステージ失敗と判定してパイプラインを停止する
- 未宣言ファイルの扱いは `validation: post_run: strict|warn|off` で制御
