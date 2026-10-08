# ステージ

## stage.yaml 仕様

各ステージの定義ファイル。実装より先に、出力 artifact、入力 artifact、パラメータ束縛、追加のパス依存を宣言する。

```yaml
# stages/detect_cog_event/stage.yaml
desc: "COG軌跡・速度を基準にPGTイベントを検出"
status: active # active | planned | inactive

outs:
    event:
        path: events.parquet
        table: timeseries
    summary_figure:
        path: figures/summary.png

params:
    cog_pgt_threshold: { file: params/detect.yaml, key: cog_pgt_threshold }

inputs:
    tables:
        - { stage: compute_cog_velocity, out: velocity }
        - { stage: import, out: dtype }
    files:
        calibration: { stage: prepare, out: calibration_model }

path_deps:
    raw_data: data/external/raw/motion
    signal_utils: libs/signal_utils.py
```

### セクションの役割

| セクション | 宣言するもの | DVC への展開 |
| --- | --- | --- |
| `outs` | 自ステージが生成する名前付き artifact（任意の `table` で DataStore 登録） | `outs` |
| `inputs.tables` | 他ステージが生成する **table artifact** の選択 | 選択した artifact のファイルを `deps`、使用する DDL を `params` |
| `inputs.files` | 他ステージが生成する artifact のファイルアクセス用参照（ローカル名付き） | 選択した artifact のファイルを `deps` |
| `path_deps` | パスで明示する外部データ・追加コード・ファイル／ディレクトリ | `deps` |
| `params` | 外部パラメータファイルのキーへの束縛 | キー単位の `params` |
| `status` / `desc` | 状態／説明 | ステージ包含判定／`desc` |

`dvc.yaml` は派生物であり、依存する対象はこれらの宣言を合わせて導出し重複排除する。

### outs 統一スキーマ

```yaml
outs:
    <key>:
        path: <相対パス> # 必須。data/stages/<stage>/ からの相対パス
        table: <論理テーブル名> # 任意。指定時だけ DataStore 管理対象
```

- `key` は公開される artifact identity の一部であり、他のステージは `{stage, out}` で参照する。自ステージのコードは `stage.out_path("<key>")`、管理テーブルは `store.write_table("<key>", df)` で出力する。
- `path` は任意のファイル名でよい。**拡張子／ファイル名 stem からテーブル名を推論しない。**
- `table` を宣言した出力だけが DataStore に参加し、同名の `TableSchemaSet` 定義を必須とする。現行の `add_datastore` フラグは廃止する。
- `table` を省略した出力は、拡張子にかかわらず通常の DVC artifact。非管理 Parquet も `table: null` などの特例宣言を要しない。未宣言の table artifact を DataStore に暗黙登録することもない。
- `table` を持つ出力は Parquet ファイルとし、書き込み時に論理テーブル名と DDL の SHA-256 を Parquet key-value metadata に必ず記録する。詳細は [datastore.md](datastore.md#parquet-metadata-の契約)。
- `table` があるのにスキーマが存在しない／非 Parquet／ディレクトリ指定 → 宣言検証でエラー。`key` 重複・出力パス重複もエラー。
- 既存の `OutsEntry.table_name = path.stem` は廃止し、`table_name: str | None` を明示宣言から取得する。

### params と inputs の関心の分離

- `params` は計算に使う制御値を、外部ファイルの `(file, key)` に束縛する。利用側は `stage.params["<local_name>"]` で値を得る。
- `inputs` は別ステージが公開した artifact の identity `(stage, out)` を選択する。処理コードによるクエリ条件の指定とは別。
- `path_deps` は artifact identity を持たない物理パスへの依存や追加ソースコードの追跡であり、通常の `params` や選択済み `inputs` を重ねて書かない。

### inputs の形式

```yaml
inputs:
    tables:
        - { stage: import, out: joint_angle }
        - { stage: import, out: dtype }
    files:
        model: { stage: train, out: checkpoint }
```

- `tables` はローカル alias を持たないリスト。同じ入力 artifact の `outs.<key>.table` を参照して DataStore の VIEW に登録する。未宣言の artifact は VIEW へ含めない。
- `files` はローカル名から artifact identity への辞書。`stage.input_path("model")` で宣言先の出力パスを解決する。`table` のない artifact も参照できる。
- 同一 artifact を `tables` と `files` の両方に記載してよい。DVC `deps` は重複排除する。`files` だけの指定で DataStore の可視範囲は広がらない。
- 別の stage 名／out key の不在や、`tables` から `table` 未宣言の出力への参照は、`validate`／実行前の参照整合性検査でエラー。
- `run.py` の通常の読み取りは `store.query("timeseries", ...)` のようにテーブル名とデータ内識別子で行い、`inputs.tables` の物理パスや別名をコードに出さない。

```python
def run(stage: StageInfo, store: DataStore):
    angles = store.query("timeseries", {"dkey": ["angle_x"]})
    model = load_model(stage.input_path("model"))
    output = process(angles, model, **stage.params)
    store.write_table("result", output)
```

### DataStore スコープと status の関係

| status | DataStore の可視範囲 | dvc.yaml |
| --- | --- | --- |
| active | `inputs.tables` で選択した artifact だけ（上流閉包へ拡張しない） | effective-active の場合に含める |
| planned | 実データなしでも入出力宣言を記述できる。探索時の可視範囲は読み取り専用 `open_scoped_store` を使う | 含めない |
| inactive | 実行対象外 | 含めない |

active で `inputs.tables` が空なら DataStore の読み取り VIEW も空。生データ取り込みなど DataStore 入力を要しないステージは実行可能。

### active が planned を参照した場合

active（effective-active）のステージが `inputs.tables` または `inputs.files` から planned の artifact を参照した場合、`staqkit validate` は警告、`staqkit repro` は実行前に `ReferenceIntegrityError`。planned 同士の参照は設計中の構造として許容する。inactive を参照する active は従来どおり suppressed 扱いとする。

### 入力宣言漏れの既知の限界

必要な artifact の宣言漏れは、VIEW 内のデータが不足していてもクエリ自体は成功する場合がある。staqkit は必要な全データを解析コードから推定できない。宣言の網羅性は解析者の責務であり、出力を確認する必要がある。

### path_deps: 物理パスで指定する追加依存

```yaml
path_deps:
    raw_data: data/external/raw/motion
    calibration: data/external/raw/calibration.csv
    signal_utils: libs/signal_utils.py
```

- リポジトリルート相対のファイル／ディレクトリ／glob を DVC `deps` に展開。glob の 0 件マッチは生成時にエラー。
- `stage.path_dep("raw_data")` で宣言されたリテラルパスを取得できる。共有 Python モジュールのように、変更追跡だけが必要な依存はコードからパス取得しなくてもよい。
- `run.py` 自体は自動追跡する。外部パラメータファイルは `params` でキー単位に追跡するため `path_deps` に重複宣言しない。
- `uv` / `pip` 等で管理する外部パッケージや環境ロックファイルは、標準で DVC dependency に加えない。Git と環境管理ツールによる記録に委ねる。環境を変えただけでは DVC の自動再実行は発生しない（手動で再実行した結果が変わる場合の追跡とは別）。必要な場合に限り明示的な `path_deps` を許す。
- 直接パスで入力を変更することは非推奨だが、staqkit は任意の Python コードによる改変を禁止しない。その場合の再現性・DVC 整合性は保証しない。実行時の改変検知警告は有用性とコストを確認してから任意に検討し、必須機構とはしない。

### params（外部ファイル参照）

params は処理の制御値を宣言する。値そのものは stage.yaml に書かず、DVC が追跡できる外部 params ファイルへ置き、stage.yaml は「ローカル名からどのファイルのどのキーを引くか」の束縛だけを持つ。

```yaml
params:
    sampling_rate: { file: params/motion.yaml, key: sampling_rate }
    cutoff: { file: params/motion.yaml, key: butterworth.cutoff }
    threshold: { file: params/detect.yaml, key: cog_pgt_threshold }
```

- 左辺（マッピングキー）はステージローカルなパラメータ名。run.py は `stage.params["<左辺>"]` で値を読む。アクセス面はこの名前のみで、params ファイルの配置やネスト構造は run.py に現れない。
- 右辺 `key` は DVC ネイティブのパラメータパス。ファイル内がネストしている場合は `butterworth.cutoff` のようにドットで辿る。`file` はリポジトリルート相対のパス。
- 値の SSoT は params ファイル。stage.yaml はどの値を使うかの束縛宣言であり、値は持たない。
- 同一ステージ内で左辺が重複した場合はエラー（YAML のキー一意性で検出される）。
- params ファイルの再編（別ファイルへの移動・ファイル内ネストの変更）は右辺の修正だけで吸収され、run.py が使うキー（左辺）は不変に保たれる。値の所在の揺れを stage.yaml が吸収し、解析コードは平らなローカル名だけに依存する。

run.py には宣言した左辺の集合だけが `stage.params` に渡る。宣言していない params ファイル上の値は見えないため、「使う param ＝ 宣言した param」が構造的に保証され、DVC が追跡する範囲（dvc.yaml に出る参照先キー）と run.py が読む範囲が一致する。

params ファイルは DVC ネイティブの params ファイル（任意の YAML）であり、staqkit は配置や粒度を規定しない。複数ステージが同じ `file`・`key` を参照すれば、その値を共有する。値の SSoT は単一ファイルに一本化され、どのステージにも帰属しない。共有のための専用構文も「定義元ステージ」の概念も持たない。慣習としては params ファイルをプロジェクト直下の `params/` に集約する運用を推奨するが、これは強制ではなく、DVC が読めるパスであればどこでもよい（[directory-layout.md](../directory-layout.md)）。

ジェネレータは各束縛の右辺 `(file, key)` を `file` 単位にまとめ、dvc.yaml の `params:` へ `<file>: [<key>, ...]` として展開する（[pipeline-gen.md](pipeline-gen.md#導出マッピング)）。DVC は当該キー単位で追跡するため、参照したキーの値が変わったときだけ参照側ステージが無効化される。左辺（ローカル名）は dvc.yaml には現れない。

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
- ディレクトリ構成が状態表現を自然に担う: 定義の存在 ≠ データの存在

planned 段階で書ける情報:

- **stage.yaml の outs**: 出力予定テーブル一覧
- **テーブルデータ**: `table` を宣言した出力は、実データの生成前にスキーマと出力 IF を定義できる
- **データテーブル**: データ実体がないので未生成

### 孤児データの管理

```bash
staqkit clean              # 孤児・inactive データを検出して一覧表示
staqkit clean --remove     # 確認の上、実際に削除
```

検出対象:

- `data/stages/xxx/` が存在するが対応する `stage.yaml` がない → 孤児
- `data/stages/xxx/` が存在し、status が inactive → 休止中データ

### ステージの削除

ステージの永久削除は、下流の参照を先に解消してから行う。

- 下流が `inputs.tables`／`inputs.files` で当該ステージの artifact を参照したまま削除すると、参照整合性検査が参照先不在を検出してエラーになる（警告のみで通す緩和経路は設けない）
- 手順: 下流ステージの inputs から当該参照を除く（または代替ソースへ繋ぎ替える）→ `stages/xxx/`・`data/stages/xxx/` を削除 → `staqkit clean` で残る孤児データを整理
- 可逆な休止が目的なら削除でなく inactive を用いる（[inactive 伝搬](#inactive-伝搬と-suppressed-状態)。上流を active に戻せば下流も自動復帰する）

## ステージ出力の構成

各 DVC ステージは `data/stages/xxx/` 配下に artifact を出力する。`outs.<key>.table` が宣言された Parquet のみ DataStore の VIEW に統合される。1ステージが複数 artifact、同じ論理テーブルに属する複数 artifact を出力してよい。

## 分散テーブルの統合

異なる artifact が同じ `outs.<key>.table` を宣言していれば、DataStore は**その run.py が `inputs.tables` に指定した artifact に限り** UNION ALL で1つの VIEW に統合する。

```text
import/joint_angle  → data/stages/import/joint_angle.parquet  (table: timeseries)
import/fsr          → data/stages/import/fsr.parquet          (table: timeseries)
```

例えば `joint_angle` だけを宣言した consumer に FSR の行は見えない。両方を宣言した場合は `timeseries` VIEW に UNION ALL する。ファイル名はテーブル名と無関係。個別 artifact の schema / metadata を VIEW 作成前に照合する。

同じ論理テーブルの artifact 間で PK が衝突してはならない（[#38](https://github.com/sakashita44/staqkit/issues/38)）。同一 stage の出力間 FK や stage 横断 PK の検証相は [#54](https://github.com/sakashita44/staqkit/issues/54) で決める。

- 出力は artifact ごとに独立して DVC 追跡されるが、DVC stage 自体の実行単位を出力ごとに分割する必要はない。
- カタログ出力は `staqkit catalog` を用いる（[CLI リファレンス](cli.md#staqkit-catalog)）。

### DAG循環の回避

「処理関数は他ステージのメタデータを読まない」原則:

- 各ステージの処理関数は、自分が出力するデータのみに責任を持つ
- 上流ステージの出力は DVC の `deps:` に含めてよい（循環しないため）
- テーブルの統合は DataStore が読み取り時に行う（UNION ALL）

## 来歴の所在

来歴（T1 来歴到達性: あるデータがいつ・どのパラメータで・どの上流実行から生成されたか）は、専用の実行記録ファイルを持たず、git 管理された `dvc.lock` と git 履歴から導出する。staqkit はステージ実行時に独自の来歴記録を書き出さない。

`dvc.lock` は各ステージについて、実行時に使われた params の実値・deps と outs のファイルハッシュ・cmd を記録し、commit 単位で git に永続する。したがって「どのパラメータで生成されたか」（params）と「どのデータから生成されたか」（dep ハッシュ）は、過去の任意の commit について `dvc.lock` を読めば判明する。実行時刻は当該 commit の時刻、実行の識別子は commit hash が担う。

### 来歴チェーンの辿り方

「ある出力が、どの上流の実行から生成されたか」は、`dvc.lock` のハッシュを git 履歴上で辿って特定する。あるステージの dep ハッシュ `h` を起点に、上流ステージの出力ハッシュが `h` を確立した最新 commit を `git log -S <h> -- dvc.lock` で探すと、その commit が上流の実行イベントに対応する。これを dep ハッシュに沿って再帰すれば実行系譜が得られる。`dvc.lock` の読み取りは DAG の順方向であり循環は生じない。

ハッシュは実データのバイト列を指すため、非決定的なステージ（再実行で出力が変わる）でも、下流が実際に消費した出力インスタンスを一意に指す。同一ハッシュは同一データであり、来歴上は等価とみなす。

### 専用の実行記録を持たない理由

実行時パラメータ・入出力ハッシュは `dvc.lock` が既に git 永続で記録するため、別途 staqkit 固有の実行記録を持つと情報が二重化する。さらに、git 管理された独立アーティファクトは `dvc.lock` の整合性機構（`dvc status` / `dvc checkout` による実体との突合）の外にあり、手編集やマージ事故で実体と乖離しても検知されず、来歴記録だけが恒久的に嘘をつきうる。来歴を `dvc.lock` + git からの導出に一本化することで、この乖離が原理的に生じない（嘘をつける独立記録が存在しない）。

行数のような `dvc.lock` に無い実行サマリは記録せず、必要なときにデータ実体から再計算する。データ実体への独立性（実体が消えても来歴を読める）は、`dvc.lock` 自体が git テキストとして残るため成立する。外部から `dvc import` で取り込んだデータの来歴は、出典元リポジトリを clone し、clone 先で同じ導出を行う（[external-data.md](external-data.md#追跡性)、[Discussion #50](https://github.com/sakashita44/staqkit/discussions/50) C2a）。

### CLIラッパー

- `staqkit history <stage>`: 当該ステージの `dvc.lock` の変遷（params・ハッシュの履歴）を git log 上で一覧表示
- `staqkit provenance <stage>`: 上記のハッシュ追跡で導出した実行系譜（来歴チェーン）を表示

いずれも `dvc.lock` と git をラップするだけで、独自の履歴 DB は持たない。

## description 3層構造

| 層      | 粒度     | 格納先                        | 内容                                 |
| ------- | -------- | ----------------------------- | ------------------------------------ |
| Layer 1 | 1行      | stages/xxx/stage.yaml の desc | 何をするか                           |
| Layer 2 | 段落     | stages/xxx/README.md          | アルゴリズム説明、既知の制限、注意点 |
| Layer 3 | 外部参照 | README.md 内のリンク          | 設計経緯（研究ノート等）             |

README に書くもの: アルゴリズムの説明、ドメイン固有のロジック、設計経緯の短縮版、既知の制限・注意点

README に書かないもの（他所がSSoT）: パラメータの実値（→ 外部 params ファイル）、入出力 artifact の宣言（→ stage.yaml）、前後のステージ（→ `staqkit dag`）

## 実行モデル

### 構成要素

ステージの実行は3つの要素で構成される。

| 要素              | 種別             | 責務                                                                                   |
| ----------------- | ---------------- | -------------------------------------------------------------------------------------- |
| StageInfo         | frozen dataclass | stage.yaml パース結果 + パス解決済みランタイム情報。params, out_path(), input_path(), path_dep() 等 |
| DataStore         | クラス           | 読み書き + バリデーションの単一アクセスポイント                                        |
| run_stage(run_fn) | 関数             | ブートストラップ → run_fn(stage, store) → エピローグ                                   |

補助的なデータクラス:

- **StageDefinition**: stage.yaml の型付き表現（StageInfo の構築元）
- **OutsEntry**: outs の各エントリの型付き表現（[outs 統一スキーマ](#outs-統一スキーマ)）
- **TableSchema**: テーブル定義（カラム・型・制約・カタログ出力設定）

StageDefinition は stage.yaml をパースした frozen dataclass であり、次のフィールドを持つ。ステージ走査（`discover_stages`）が `list[StageDefinition]` を返し、グラフ操作（パイプライン生成・参照整合性検査）はパス解決を伴わない本表現を用いる。

| フィールド | 内容                                   | 由来                    |
| ---------- | -------------------------------------- | ----------------------- |
| name       | ステージ名（`stages/` からの相対パス） | ディレクトリ位置        |
| desc       | 1行説明                                | stage.yaml `desc`       |
| status     | active / planned / inactive            | stage.yaml `status`     |
| outs       | `list[OutsEntry]`                      | stage.yaml `outs`       |
| params     | パラメータ辞書                         | stage.yaml `params`     |
| inputs     | tables の artifact refs と files のローカル名 → artifact refs | stage.yaml `inputs` |
| path_deps  | key → パスの辞書                       | stage.yaml `path_deps` |

StageInfo は StageDefinition に [ProjectLayout](../architecture.md#projectlayout) を束ねた実行時ビューであり、`out_path()` / `input_path()` / `path_dep()` 等のパス解決を ProjectLayout へ委譲する。単一ステージの run.py 文脈に注入されるのは StageInfo、グラフ走査に用いるのは StageDefinition、と用途で使い分ける。

StageInfo は status によって挙動を変えない。planned/active の区別はオーケストレーション層（dvc.yaml 生成時に planned ステージを除外する等）の責務である。

### run.py エントリポイント規約

DVC は `python stages/X/run.py` で各ステージを呼び出す。`run_stage` は自身のディレクトリから stage.yaml を読み、StageInfo を構築し、スコープ解決ファクトリ（`open_store`）で DataStore を組み立てて処理関数に注入する。run.py が制御を `run_stage` に渡す制御反転（IoC）の形を採る。

```python
from staqkit import run_stage
from staqkit.types import StageInfo, DataStore

def run(stage: StageInfo, store: DataStore):
    df = store.query("timeseries", {"subject_id": [1, 2]})
    result = normalize(df, **stage.params)
    store.write_table("result", result)

if __name__ == "__main__":
    run_stage(run)
```

`store.write_table()` は現在の stage に宣言された `outs` artifact key を受け取る（テーブル名ではない）。`store.query` が契約検証つきの祝福されたメイン経路、`store.fetch` が生 SQL の抜け道である（保証の差は [datastore.md](datastore.md#読み取り-api)）。

### post-run 検証

run_stage のエピローグで実施する検証。

| 検証項目                                 | 担当                  | タイミング                                       |
| ---------------------------------------- | --------------------- | ------------------------------------------------ |
| outs の変更追跡（ハッシュベース）        | DVC                   | dvc repro / dvc status                           |
| スキーマ構造・Parquet metadata | DataStore write_table / 入力構築 | 管理テーブル artifact ごと。横断的な制約検証の相は #54 で判断 |
| 未生成ファイル（declared − actual）      | run_stage エピローグ  | ステージ実行後 → 例外 → DVC 停止                 |
| 未宣言ファイル（actual − declared）      | run_stage エピローグ  | ステージ実行後 → 警告（post_run で例外昇格可能） |

- エピローグの例外は Python プロセスの非ゼロ終了コードとなり、DVC がステージ失敗と判定してパイプラインを停止する
- 未宣言ファイルの扱いは `config/project.yaml` の `validation.post_run`（`strict|warn|off`）で制御する。既定値は [directory-layout.md](../directory-layout.md#プロジェクト全体設定) に従う
