# DataStore

run.py / notebook 向けの、データアクセスの祝福されたメイン経路。スコープ解決済みの Parquet ファイル群をクエリエンジン上に VIEW として結合し、契約検証つきの高レベル API（`query`）または生 SQL の抜け道（`fetch`）でクエリする。クエリエンジンは Protocol として定義されており、現在の実装は DuckDB（`:memory:` モード）。

DataStore 自身はプロジェクト構成（`stages/`, `config/` 等）を走査しない。組み立て（ファイル収集・スコープ絞り込み・VIEW 登録・DDL 検証）は Project 層のスコープ解決ファクトリの責務であり、DataStore は解決済みのクエリエンジンを受け取る。同じファクトリを CLI のデータ参照コマンド（catalog / validate）も用いるため、CLI は DataStore ファサードに依存しない（[architecture.md](../architecture.md#スコープ解決ファクトリと依存方向)）。

## TableSchemaSet

`config/table_schemas/` の検証済みスナップショット。プロジェクトが定義した全テーブルスキーマの集合を表現する。Core 層に配置（DDL の構造的検証のみでドメイン非依存）。

### TableSchemaSet と DataStore の違い

|                  | TableSchemaSet                                     | DataStore                                  |
| ---------------- | -------------------------------------------------- | ------------------------------------------ |
| 対応ディレクトリ | `config/table_schemas/`                            | `data/stages/*/`                           |
| 表現するもの     | プロジェクトで定義されたスキーマ全体               | スコープ内のデータ                         |
| データの有無     | 不要                                               | 必須                                       |
| 問い合わせの意味 | 「プロジェクトにどんなテーブルが定義されているか」 | 「今このコンテキストで見えるデータは何か」 |

### 入力形式

`list[TableSchema]` を受け取る。テーブル名は DDL の `CREATE TABLE <name>` から一意に決まり TableSchema 自身が保持しているため、dict のキーとの乖離リスクを排除する（SSoT）。テーブル名 → スキーマのマッピングは TableSchemaSet が内部で構築する。

### 不変性

生成後は変更不可（スナップショット）。`config/table_schemas/` の YAML を変更したら作り直す。スコープの概念はない（テーブルスキーマ定義はプロジェクト全体で不変）。

コマンド実行ごとに一度だけ生成し、同一コマンド内の全処理で共有する。`staqkit repro` は1ステージ = 1プロセス = 1 DataStore の逐次実行であり、同一プロセス内で複数の DataStore を組み立てるユースケースは現状設計に存在しない。

### 生成時バリデーション

| 検証項目                   | 挙動                                        |
| -------------------------- | ------------------------------------------- |
| テーブル名の一意性         | エラー                                      |
| FK 参照先テーブルの存在    | エラー                                      |
| FK 参照先カラムの存在      | エラー                                      |
| FK カラムの型一致          | エラー                                      |
| column_descriptions 未記述 | エラーにしない（`staqkit validate` で警告） |

### 公開 API

| メソッド              | 返る情報                                                 | 利用者                                        |
| --------------------- | -------------------------------------------------------- | --------------------------------------------- |
| `table_names()`       | 定義テーブル名の一覧                                     | DataStore 組み立て、`staqkit schema`          |
| `get(table)`          | 該当 TableSchema（不在は `KeyError`）                    | DataStore、validate、`staqkit schema <table>` |
| `find_column(column)` | カラムの全出現箇所（テーブル・役割・description・FK 先） | `staqkit column`                              |
| `foreign_keys()`      | プロジェクト全体の FK 参照関係の一覧                     | validate（FK 整合性）、CLI                    |

「テーブルが持つ FK 参照先」は `get(table).foreign_keys`（TableSchema のフィールド）で得るため、TableSchemaSet 側に重複定義しない。

```python
@dataclass(frozen=True)
class ForeignKeyRef:
    table: str        # FK を持つテーブル
    column: str       # FK カラム
    ref_table: str    # 参照先テーブル
    ref_column: str   # 参照先カラム

@dataclass(frozen=True)
class ColumnOccurrence:
    table: str
    column: str
    is_primary_key: bool
    foreign_key: ForeignKeyRef | None   # FK 参照先。FK でなければ None
    description: str | None             # column_descriptions[column]。未記述は None

class TableSchemaSet:
    def table_names(self) -> list[str]: ...
    def get(self, table: str) -> TableSchema: ...
    def find_column(self, column: str) -> list[ColumnOccurrence]: ...
    def foreign_keys(self) -> list[ForeignKeyRef]: ...
```

カラムの役割は `is_primary_key`（bool）と `foreign_key`（`ForeignKeyRef | None`）という直交する2フィールドで表す。PK と FK は SQL 上で独立した軸であり、`timeseries.dkey`（複合 PK の一部であり同時に `dtype` への FK）のような「PK かつ FK」を、単一の役割 enum に潰さず表現できる。2フィールドの取り得る4通り（PK のみ・FK のみ・両方・どちらでもない）はすべて正当な状態であり、不正な組み合わせは存在しない。1カラムの FK 参照先は識別軸モデル上一意なため `foreign_key` は単数で持つ。内部データ構造（FK 関係グラフの事前構築 vs 都度走査等）は実装時判断とする。

### TableSchema のフィールド

DDL パース結果として以下を保持する:

| フィールド          | 内容                                                      | 導出元                                                |
| ------------------- | --------------------------------------------------------- | ----------------------------------------------------- |
| table_name          | テーブル名                                                | DDL `CREATE TABLE <name>`                             |
| columns             | カラム名 → 型のマッピング                                 | DDL カラム定義                                        |
| primary_key         | PK カラム名のリスト                                       | DDL `PRIMARY KEY (...)`                               |
| foreign_keys        | FK 定義のリスト（カラム名, 参照先テーブル, 参照先カラム） | DDL `REFERENCES ...`                                  |
| checks              | CHECK 制約式のリスト                                      | DDL `CHECK (...)`                                     |
| unique_constraints  | UNIQUE 制約のリスト                                       | DDL `UNIQUE (...)`                                    |
| not_null_columns    | NOT NULL 指定カラム名のリスト                             | DDL `NOT NULL`                                        |
| ddl_raw             | 生の DDL 文字列（QueryEngine への投入用）                 | table_schema YAML の `ddl` フィールド                 |
| description         | テーブルの説明                                            | table_schema YAML の `description` フィールド         |
| catalog             | カタログ出力対象か                                        | table_schema YAML の `catalog` フィールド             |
| column_descriptions | カラム名 → 説明文字列                                     | table_schema YAML の `column_descriptions` フィールド |

### バリデーションの責務分担

- **TableSchema**: テーブルスキーマ YAML 単体での成立性（例: `column_descriptions` のキーが DDL のカラム定義に存在するか）
- **TableSchemaSet**: 全体としての整合性（例: FK 参照先テーブル・カラムの存在、型一致）

### テーブル登録・エントリ追加との関係

TableSchemaSet はいずれにも関与しない。

- テーブル定義の登録 = `config/table_schemas/` に YAML ファイルを追加（人間の操作）
- エントリ追加 = DataStore の `write_table()`
- QueryEngine = 読み出し特化（VIEW 登録は組み立て相の EngineBuilder の責務であり、利用者が持つ QueryEngine は read-only）

## コンストラクタ

DataStore は解決済みの構成要素のみを受け取る。config パス・StageInfo・scope パラメータは受け取らず、自身でプロジェクト構成を走査しない。VIEW 登録はスコープ解決ファクトリ（`build_scoped_engine`）が済ませ、DataStore は登録済みの QueryEngine を受け取る。

```python
class DataStore:
    def __init__(
        self,
        engine: QueryEngine,                  # VIEW 登録済み・read-only の QueryEngine
        schemas: TableSchemaSet,              # プロジェクト全テーブルスキーマの検証済み集合
        output_paths: dict[str, Path] | None = None,  # テーブル名 → 出力先パス
    ): ...
```

- `engine`: スコープ解決ファクトリが対象スコープのファイルを VIEW 登録した結果。DataStore 自身は登録操作を行わず、問い合わせ（`query` / `fetch`）にこの engine を用いる
- `schemas`: `config/table_schemas/` のパース・検証済みスナップショット。DDL の PK/FK 制約からテーブル間関係を導出する
- `output_paths`: `None` なら `write_table` は利用不可（読み取り専用インスタンス）。run.py 経路では `open_store(writable=True)` が `stage` の outs から解決して渡す
- DataStore 自体を context manager として提供（`with DataStore(...) as store:`）。close 時に engine を解放する

### 接続ライフサイクル

DataStore のライフサイクル = QueryEngine 接続のライフサイクル（1:1）。

- run.py: ステージ実行と 1:1。`run_stage` が生成し、終了後に破棄
- CLI: コマンド実行中のみ生存

## ステージ発見

`discover_stages(layout) -> list[StageDefinition]` が `stages/**/stage.yaml` を再帰走査してステージ定義一覧を得る。各 StageDefinition の詳細フィールドは [stage.md](stage.md#実行モデル) を参照。対応する `data/stages/*/` からファイルを読む。ステージ名は `stages/` からの相対パス。

- 定義あり・データなし → planned 状態
- 定義あり・データあり → 通常ステージ
- dvc.yaml のパースに依存しない（DVC 内部構造への密結合を回避）

## スコープ解決ファクトリ

DataStore の組み立て（ステージ走査・ファイル収集・スコープ絞り込み・VIEW 登録・スキーマ読み込み）は Project 層のスコープ解決ファクトリに集約する。ファクトリはクラスではなく関数群であり、各ステップは独立して呼び出し・テストできる単位に分かれる。パス規約は [ProjectLayout](../architecture.md#projectlayout) が単一の出所として保持し、各関数はそこへ委譲する。

### 組み立てフロー

コマンド実行ごとに、次の順序で組み立てる。

1. `load_schema_set(layout) -> TableSchemaSet`: `config/table_schemas/**/*.yaml` をパース・検証し、プロジェクト全体のスキーマスナップショットを得る。スコープに依存せず、コマンド実行ごとに一度だけ構築する。
1. `discover_stages(layout) -> list[StageDefinition]`: `stages/**/stage.yaml` を再帰走査し、型付きのステージ定義一覧を得る（[ステージ発見](#ステージ発見)）。
1. `upstream_closure(stages, inputs) -> ScopeSpec`: 対象ステージの `inputs` を起点に、DAG を遡って到達可能な全ステージを算出する純粋関数。ファイルシステムに触れないため単体テストが容易。
1. `build_scoped_engine(scope, layout, schemas) -> QueryEngine`: `scope` に含まれるステージの `add_datastore: true` な outs を、同名テーブル（ステム一致）ごとに UNION ALL して VIEW 登録し、read-only の QueryEngine を返す。
1. 上記を結線して DataStore を構築する。

`ScopeSpec` は解決済みのステージ集合を表す。上流閉包の算出は呼び出し側（`run_stage` / CLI）の責務であり、`build_scoped_engine` は「与えられた集合のファイルを集めて VIEW 化する」ことに専念する。

### 入口

ファクトリの入口はコンテキスト別に分かれる。

- 低レベル（CLI データ参照）: `build_scoped_engine(scope, layout, schemas) -> QueryEngine`。解決済みスコープから read-only の QueryEngine を返す。CLI の catalog / validate が直接使う。
- run.py（管理下）: `open_store(stage, schemas, *, writable=True) -> DataStore`。引数の `StageInfo` 一つから、読み取りスコープ（`stage` の inputs 由来の上流閉包）と書き込み対象（`stage` の outs 由来の出力パス）の双方を導出し、内部で `build_scoped_engine` を用いて DataStore を組み立てる。`writable=False` のときは出力パスを与えず読み取り専用とする。
- notebook / 管理外（読み取り専用）: `open_scoped_store(root, *, up_to=None) -> DataStore`。`StageInfo` を持たない管理外コンテキスト向けの入口。プロジェクトルートから layout・stages・schemas を構築し、`up_to` 指定時はそのステージ群の上流閉包、未指定時は全ステージをスコープとして、出力パスなし（読み取り専用）の DataStore を返す。

```python
# notebook から管理下データを読む（管理境界インターフェース）
with open_scoped_store(Path("."), up_to=["normalize"]) as store:
    df = store.query("timeseries", {"subject_id": [1, 2]})
```

`open_scoped_store` は管理外から管理下データを参照する祝福された読み取り口であり、DataStore を手で構築する必要をなくす。書き込みは run.py（管理下）でのみ行うため read-only に固定する。

`StageInfo` は [ProjectLayout](../architecture.md#projectlayout) を委譲先に持つため、`open_store` は `stage` から layout を辿れる。読み取りスコープが inputs、書き込み対象が outs、という対応が `StageInfo` 一点に集約され、両者を別経路で渡す曖昧さを排除する。

`schemas` を `stage` に内包させず別引数で受けるのは、TableSchemaSet がスコープ非依存のプロジェクト全体スナップショットであり、`load_schema_set` でコマンド実行ごとに一度だけ構築して全成果物（QueryEngine 直利用の CLI 経路と DataStore 経路の双方）で共有する単位だからである。ステージごとに変わる `stage` と、コマンド全体で不変の `schemas` はライフサイクルが異なるため、引数として分離する。

### コマンド別に必要な構成要素

組み立ての各成果物は、コマンドの目的に応じて必要なものだけを構築する。

| コマンド                         | TableSchemaSet | QueryEngine            | DataStore                      |
| -------------------------------- | -------------- | ---------------------- | ------------------------------ |
| run.py（run_stage 経由）         | 必要           | 必要                   | 必要（open_store）             |
| `staqkit catalog`                | 必要           | 必要                   | 不要（build_scoped_engine 直） |
| `staqkit validate`               | 必要           | スキーマ準拠検査時のみ | 不要                           |
| `staqkit dag` / `staqkit status` | 不要           | 不要                   | 不要                           |

`staqkit validate` の config 整合性検査（参照整合性・FK 整合性）は TableSchemaSet と StageDefinition のみで成立し、QueryEngine を要しない。Parquet の DDL 準拠検査を行うときにのみ `build_scoped_engine` を併用する。

## 識別子と属性の表現

識別子の語彙（被験者・条件・計測種別等）はそのテーブルに実在する PK 値の集合、識別子の属性（被験者の身長・体重、計測種別の単位等）は同じテーブルのカラム、識別子どうしの関係は FK で表す。

### 属性によるフィルタ

識別子の属性による絞り込み（「身長 > 170 の被験者だけ」等）は次のいずれかで行う。

- `query()` でテーブル単位に取得し、polars 側で結合・絞り込む
- `fetch()` で FK を辿る JOIN と範囲条件を SQL で書く

`query()` は等値/IN・単一テーブルに閉じ（[高レベル API](#高レベル-apiquery祝福されたメイン経路)）、属性テーブルへの JOIN を内蔵しない。

### 語彙の進化と削除

- 値（行）の追加・削除: スキーマを変えないデータ操作であり、生成ステージの再実行で反映する。削除した値を FK 参照する行は孤立となり、FK 整合性検査が検出する。カスケード削除は行わず、孤立の解消はユーザの責務
- 属性（カラム）の追加・変更: DDL 変更であり、同名テーブルを出力する全ステージの [スキーマ契約](#テーブル結合のスキーマ契約)を一斉に変える。既存 parquet はスキーマ準拠検査（`on_read: schema` / `staqkit validate`）で非準拠として検出され、生成ステージの再実行で解消する。in-place 変換は行わず、マイグレーションは再生成を指す

## 読み取り API

読み取りには保証の異なる二経路がある（[architecture.md](../architecture.md#守る契約とアクセス経路の保証グラデーション)）。`query()` は契約検証つきの祝福されたメイン経路、`fetch()` は無保証の抜け道である。抜け道に降りても、スコープ安全（登録済み VIEW しか参照できない）と read-only は維持される。

### 高レベル API（query・祝福されたメイン経路）

```python
def query(
    self,
    table: str,
    filters: dict[str, object | list[object]] | None = None,
    columns: list[str] | None = None,
) -> pl.DataFrame:
    """バリデーション付きショートカット（等値/IN フィルタ + 列射影）"""
```

```python
store = DataStore(...)
df = store.query("timeseries", {"subject_id": [1, 2], "dkey": ["A", "B"]})
cols = store.query("timeseries", {"subject_id": [1]}, columns=["uid", "frame", "value"])
```

- `table`: 必須。SQL の FROM 句に相当
- `filters`: dict 形式。等値一致（`=`）/ リスト一致（`IN`）のみ。値がリストなら `IN`、それ以外は等値
- `columns`: 取得列を限定する射影。`None` なら全列。指定した列名は TableSchemaSet で実在を検証する
- 範囲条件・JOIN・集計が必要な場合は `fetch()` で SQL を書く
- query() の役割: DDL 情報（TableSchemaSet）を使ったランタイムバリデーション（テーブル名・キー名・列名・型の検証）と dict から SQL への変換
- 結果は対象テーブルの主キー昇順で返す。複合主キーの場合は DDL の宣言順に列を連ねた昇順とする。複数ファイルを UNION ALL した VIEW は行順序が不定であり、query() は決定的な順序を保証して再現性を担保する。順序保証のコストを避けたい大規模ケースでは `fetch()` で明示的に順序を指定する

### 低レベル API（fetch・無保証の抜け道）

```python
def fetch(self, sql: str, params: Sequence[Any] | None = None) -> pl.DataFrame:
    """SQL の全表現力（SELECT 系のみ）。VIEW 定義済みの状態で実行"""
```

```python
df = store.fetch(
    """
    SELECT t.uid, t.frame, t.value
    FROM timeseries t
    JOIN dtype d ON t.dkey = d.dkey
    WHERE d.data_group = ?
      AND d.coordinate = ?
    """,
    ["joint", "flexion"],
)
```

- SELECT（CTE、VALUES 含む）のみ許可。INSERT/UPDATE/DELETE/DDL は拒否。この制約は QueryEngine Protocol の責務（`fetch` の契約）
- `params`: プレースホルダ（`?`）へバインドする値。`fetch` は値を文字列連結せずエンジン側でバインドするため、利用者が値を SQL に直接埋め込む際のクォート漏れ・型崩れを避けられる
- DuckDB 実装では `read_only=True` の接続オプションでエンジンレベルで保証する。SQL パースによる判定は行わない
- `fetch` は無保証の抜け道だが、登録済み VIEW しか参照できないためスコープ安全は崩れない。`query()` の契約検証（テーブル名・キー名・型）だけが失われる
- 接続オブジェクトは staqkit 実装内では公開しない。フルカタログへ繋がれてスコープ安全が崩れること、および保守者のエンジン差し替え性が損なわれることを避けるため。最深の抜け道は `fetch` までとする

### 戻り値型

`query()` / `fetch()` の戻り値型は `polars.DataFrame` に統一。

- DuckDB とゼロコピー連携可能
- イミュータブルで staqkit の不変性原則と整合
- pandas が必要な場面では `.to_pandas()` で変換可能
- 戻り値型は `polars.DataFrame` を契約として固定する。エンジン固有の型を返さないことで、保守者が将来エンジンや戻り値ライブラリを置換する際のコスト（migration surface）を継ぎ目に局所化する

## 書き込み

### write_table

```python
def write_table(self, name: str, df: pl.DataFrame) -> None:
    """スキーマ検証 + Parquet 書き出し"""
```

```python
def run(stage: StageInfo, store: DataStore):
    result = process(...)
    store.write_table("timeseries", result)
```

- テーブル名のみ指定。出力先パスは DataStore がコンストラクタで受け取った `output_paths` から内部解決
- スキーマバリデーション + ファイル書き込みを一体で行う（バリデーション忘れ防止）
- `output_paths` が `None`（読み取り専用インスタンス）の場合はエラー
- 書き込んだデータはその DataStore インスタンスからは読めない（QueryEngine 内の VIEW を変更しない。DataStore は実行中 immutable）。run.py 内では書き込み前の DataFrame を直接保持しているため、再読み込みの必要はない

### 出力パスの SSoT

全 outs（テーブル・非テーブル）の出力パス解決は StageInfo の責務。DataStore は StageInfo が解決した結果を `output_paths` として受け取るだけ（重複ではなく委譲）。非テーブル出力（画像等）は `stage.out_path("key")` で直接取得する。

### add_datastore フラグ

デフォルト true、省略不可。

```yaml
outs:
    timeseries:
        path: timeseries.parquet
        add_datastore: true # 省略不可
    raw_dump:
        path: raw_dump.parquet
        add_datastore: false # 明示的に除外
    summary_figure:
        path: figures/summary.png
        add_datastore: false # 非 Parquet は false のみ許可
```

クロスバリデーション:

- `add_datastore: true` + スキーマ定義なし → エラー（スキーマ忘れ検出）
- `add_datastore: false` + スキーマ定義あり → エラー（矛盾検出）
- `add_datastore: false` + 同名テーブルスキーマ存在 → エラー（同名で除外は矛盾）
- フラグ省略 → エラー（意図の明示を強制）
- 非 Parquet + `add_datastore: true` → エラー

## メタデータ API

```python
@property
def schemas(self) -> TableSchemaSet:
    """プロジェクト全テーブルスキーマの検証済みスナップショット"""

def tables(self) -> list[str]:
    """登録済みテーブル一覧（スコープ内）"""

def columns(self, table: str) -> list[str]:
    """カラム名のリスト。存在しないテーブルは KeyError"""

def schema(self, table: str) -> TableSchema:
    """スキーマ定義全体（DDL パース結果 + description + catalog フラグ）。
    存在しないテーブルは KeyError"""
```

- `schemas`: コンストラクタで受け取った TableSchemaSet をそのまま露出する。カラム横断検索や FK 関係グラフなど、スキーマ内省の全 API（[公開 API](#公開-api)）への直接経路。`tables()` がスコープ内（今このコンテキストで引ける）テーブルを返すのに対し、`schemas` はプロジェクトに定義された全テーブルを表す
- `columns()` / `schema()` は `schemas` 経由の内省を日常用途向けに短縮した近道。`columns()` は型情報なしで、主用途はクエリ組み立て時のカラム名確認。型の不一致は `write_table()` のバリデーションが検出する
- `schema()` は DDL パース結果の全情報を返す。Project 層内部や将来の拡張用途に対応

## テーブル結合のスキーマ契約

DataStore は同名テーブルを全ステージ分 UNION ALL して1つの VIEW にする。全ステージが同一のカラム定義を持つことが要求されるため、`config/table_schemas/` をコンシューマ側の契約として維持し、プロデューサー側の契約は書き込み時バリデーションで実現する。

スキーマ定義は SQL DDL をそのまま記述する。DuckDB にそのまま渡せる標準 SQL を正統な形式とする。カタログ等の staqkit 固有メタデータは YAML フィールドとして併記する。

```yaml
# config/table_schemas/timeseries.yaml
ddl: |
    CREATE TABLE timeseries (
        uid VARCHAR NOT NULL,
        dkey VARCHAR NOT NULL REFERENCES dtype(dkey),
        frame INTEGER CHECK (frame >= 0),
        value DOUBLE,
        PRIMARY KEY (uid, dkey, frame)
    )
description: "正規化済み時系列データ"
catalog: true
column_descriptions:
    uid: "試行一意識別子（subject_id × trial_id で決定）"
    dkey: "データ種別識別子"
    frame: "フレーム番号（0始まり）"
    value: "測定値。意味と単位は dkey に従属"
```

- `ddl`: SQL DDL（CREATE TABLE 文）。DuckDB にそのまま渡せる標準 SQL を正統な形式とする。DDL は DuckDB 依存であり CHECK 式にエンジン固有関数を含みうる。これはエンジン差し替え時に触れる migration surface（[architecture.md](../architecture.md#エンジン置換時の作業範囲)）であり、置換時には DDL のマイグレーションを伴う
- `description`: テーブルの説明（カタログ出力に使用）
- `catalog`: `staqkit catalog` の出力対象とするか（デフォルト: false）。CLI で `--table` を明示指定した場合はそちらが優先
- `column_descriptions`: カラム名 → 説明文字列のマップ。単位は説明内に記述する（例: `"体重 [kg]"`）。FK カラムの description は省略可（参照先の description で意味が明確なため）

### table_schemas のディレクトリ構成

`config/table_schemas/` はサブディレクトリによる整理を許容する。走査は `config/table_schemas/**/*.yaml` の再帰。

- テーブル名 = ファイル名（ステム）。ディレクトリパスは名前に含めない
- 同名ファイルが異なるサブディレクトリに存在 → エラー（一意性違反）

ステージ（ディレクトリパスが名前になる）とは異なるルールだが、DDL の `CREATE TABLE <name>` と一致させるための設計判断。

## バリデーション

### 検証方式

DDL を `sqlglot` 等でパースし、制約定義を抽出。対象データに対して検証クエリを実行する。DDL の表現力がそのまま検証の表現力になるため、エンジン固有の CHECK 式も同一エンジンで検査できる。

### 検証レベル

検証レベルは `config/project.yaml` の `validation` で制御する（[directory-layout.md](../directory-layout.md#プロジェクト全体設定)）。

```yaml
validation:
    on_read: schema # constraint | schema | off
    on_write: constraint # constraint | off
```

各キーの既定値と設定不在時の挙動は [directory-layout.md](../directory-layout.md#プロジェクト全体設定) に従う。`constraint` は write_table を通らないデータ（手編集・外部取り込み）の制約違反を毎読み込みで検出する。同等の検査はリポジトリ横断の `staqkit validate` でもオンデマンドに実行できる。

#### 読み込み時

DataStore 組み立て時に適用する。

- `off`: 検証なし
- `schema`: カラム名・型が DDL と一致するか + ステージ間 UNION ALL 互換性（メタデータのみ、全行スキャン不要）
- `constraint`: schema に加え NOT NULL / PK / UNIQUE / CHECK / FK を全行スキャンで検証

#### 書き込み時

write_table 実行時に適用する。

- `off`: 検証なし
- `constraint`: カラム名・型 + 全制約検証。PK 重複・FK は既存 VIEW に対する JOIN で検証

FK 検証は読み取りスコープに依存する。write_table の FK 検証は、参照先テーブルがそのステージの読み取りスコープ（inputs 由来の上流閉包）に VIEW として存在する場合にのみ実行できる。したがって FK で参照するテーブルを生成する上流ステージは inputs に含めることを要件とする。inputs に含めず参照先がスコープ外となる場合、その FK は write 時に検証されない既知の限界として扱い、リポジトリ全体を横断する `staqkit validate` の FK 整合性検査で補完する。

検証は read-only の `fetch` の表現力だけで閉じる。書き込み候補データの FK 値を `VALUES` 句／`params` でインライン化し、参照先 VIEW への anti-join（候補側にあって参照先にない値を拾う `LEFT JOIN ... WHERE 参照先キー IS NULL` 相当）で違反行を検出する。候補フレームを VIEW として登録する経路は不要であり、利用者が持つ QueryEngine が read-only で register を持たない（[エンジンの二相](#エンジンの二相-enginebuilder-と-queryengine)）という不変条件と整合する。anti-join では候補側 FK 値が NULL の行を対象から除外する。SQL 標準の FK は NULL を違反としない（参照は「値があるなら参照先に存在せよ」の制約）ため、NULL を含めると anti-join がそれらを誤検出してしまう。NULL を許さない FK は NOT NULL 制約検査が別途捕捉するため、この除外で検証に穴は空かない。

参照先 VIEW の有無で挙動が分岐する。参照先がスコープに未登録なら検証自体をスキップする（前述の既知の限界）。登録済みなら anti-join を実行し、参照先が0行で候補値がどれも一致しない場合は全候補行が違反として `ConstraintViolationError` となる。「VIEW 不在＝スキップ」と「VIEW 存在かつ不一致＝違反」は別であり、上流 planned でデータ未配置のケース（VIEW 不在＝スキップ側）と混同しない。

書き込み時に `schema`（カラム名・型のみ、制約スキップ）レベルは提供しない。write_table はステージ出力の最終ゲートであり、制約違反を含むデータが DataStore に混入すると下流全体に波及する。開発中の高速イテレーションでは `off` で検証自体を無効化する。

### 検証クエリの生成

- NOT NULL / PK / UNIQUE / FK: DDL から構造的に抽出 → 検証クエリを機械的に生成
- CHECK: DDL から式を抽出し `WHERE NOT (expr)` として実行（エンジン依存の式はそのまま同一エンジンで実行するため問題なし）

### column_descriptions の検証

DDL に記載のカラムに対応する `column_descriptions` がない場合、`staqkit validate` で警告を出力する。エラーにはしない（TableSchemaSet の組み立て自体は可能）。`column_descriptions` に DDL に存在しないカラム名が含まれる場合は TableSchema 生成時にエラー。

## エンジンの二相: EngineBuilder と QueryEngine

クエリエンジンは「組み立て相」と「問い合わせ相」を型で分離する。可変状態（接続への VIEW 登録）が変化する窓を組み立て相に閉じ込め、利用者が受け取る問い合わせ相からは VIEW を変更する操作を型から取り除く。これにより「組み立て後のエンジンは不変」という不変条件を、規約ではなく型で保証する。可変状態は接続という不可避な一点に局所化され、その変化窓は組み立て相だけに閉じる。

両者はあわせて差し替え可能な継ぎ目を成す（[architecture.md](../architecture.md#エンジン差し替え性の二分割)）。エンジンを置換する保守者は両 Protocol を実装するが、単一の接続オブジェクトが両者を満たしてよい。

### 責務外（両相に共通）

- DDL のパース・制約検証（DataStore 側）
- メタデータ管理（テーブル一覧・カラム情報）（TableSchemaSet / DataStore 側）
- ファイルパスの解決・走査（Project 層のスコープ解決ファクトリ）
- データの正確性保証（register は渡されたものをそのまま登録するだけ）

### EngineBuilder（組み立て相）

スコープ解決ファクトリの内部だけで用いる。VIEW を登録し、封印して読み取り専用の QueryEngine を返す。

```python
class EngineBuilder(Protocol):
    def register(self, name: str, files: list[Path]) -> None:
        """files を UNION ALL 相当で結合し name でクエリ可能にする"""

    def seal(self) -> "QueryEngine":
        """登録を確定し、以降変更不可能な読み取り専用 QueryEngine を返す"""
```

- `register`: ファイル群を結合し指定名で VIEW 化する。データの正確性は検証しない。全データのメモリコピーを前提としない
- `seal`: 組み立てを終え、register を持たない QueryEngine を返す。`build_scoped_engine` はこの戻り値を返す

### QueryEngine（問い合わせ相）

DataStore と CLI が保持する。read-only であり、VIEW を変更する操作を持たない。

```python
class QueryEngine(Protocol):
    def fetch(self, sql: str, params: Sequence[Any] | None = None) -> pl.DataFrame:
        """SELECT 系の SQL を実行し結果を返す（読み取り専用を保証）"""

    def close(self) -> None:
        """リソース解放"""
```

- `fetch`: SELECT（CTE、VALUES 含む）のみ許可。INSERT/UPDATE/DELETE/DDL は拒否。`params` でプレースホルダに値をバインドし、文字列連結による組み立てを避ける
- `close`: 内部リソースの解放。DataStore が context manager として `close` を呼び出す
- register を持たないため、組み立て後に VIEW を追加・変更できない（状態の変化窓は EngineBuilder に閉じる）

### VIEW vs TABLE

| 観点            | VIEW             | TABLE                  |
| --------------- | ---------------- | ---------------------- |
| register コスト | 軽（参照のみ）   | 重（全データコピー）   |
| クエリ性能      | Parquet 読み取り | メモリアクセス（高速） |

Protocol は VIEW ベースを前提とする。TABLE 対応は将来のパフォーマンス要件に応じて検討する。

## 外部データアクセス

外部リポジトリから取り込んだデータ（`data/external/<repo>/`）は DataStore へ直接は載せない。ローカル生データと同じくソースとして扱い、下流の取り込みステージが `extra_deps` でファイルとして読み込み、加工結果を当該プロジェクト自身の `config/table_schemas/` に従って DataStore に登録する（[external-data.md](../external-data.md)）。これにより DataStore は外部由来かどうかを一切知らずに済み、外部スキーマを転送・解釈する仕組みも不要になる。取り込みステージを通さず外部データを直接クエリすることは想定しない。

### 非 Parquet データの発見

バイナリファイル（ML モデル等）を DataStore 経由で発見可能にするパターン: パスを格納した Parquet（`add_datastore: true`）+ バイナリ本体（`add_datastore: false`）。DataStore で「どのモデルがどこにあるか」を検索し、実体はパスで直接アクセス。

外部ツール出力（モーションキャプチャの trc/tsv、c3d→csv 等、[#6](https://github.com/sakashita44/staqkit/issues/6)）も同じパターンで扱う。実体ファイルを `add_datastore: false` の out として宣言し、パスを格納した sidecar parquet（`add_datastore: true`）を併設して DataStore から発見可能にする。取り込みステージ（`staqkit add-stage --template ingest`）の雛形がこの構成を生成する。
