# DataStore

データアクセスの唯一のエントリポイント。スコープ解決済みの Parquet ファイル群をクエリエンジン上に VIEW として結合し、SQL または高レベル API でクエリする。クエリエンジンは Protocol として定義されており、現在の実装は DuckDB（`:memory:` モード）。

DataStore 自身はプロジェクト構成（`stages/`, `config/` 等）を走査しない。組み立て（ファイル収集・スコープ絞り込み・インスタンス生成）は Framework 層の責務であり、DataStore は解決済みデータのみを受け取る。

## TableSchemaSet

`config/table_schemas/` の検証済みスナップショット。プロジェクトが定義した全テーブルスキーマの集合を表現する。Core 層に配置（DDL の構造的検証のみでドメイン非依存）。

### TableSchemaSet と DataStore の違い

| | TableSchemaSet | DataStore |
|---|---|---|
| 写し先 | `config/table_schemas/` | `data/stages/*/` |
| 表現するもの | プロジェクトで定義されたスキーマ全体 | スコープ内のデータ |
| データの有無 | 不要 | 必須 |
| 問い合わせの意味 | 「プロジェクトにどんなテーブルが定義されているか」 | 「今このコンテキストで見えるデータは何か」 |

### 入力形式

`list[TableSchema]` を受け取る。テーブル名は DDL の `CREATE TABLE <name>` から一意に決まり TableSchema 自身が保持しているため、dict のキーとの乖離リスクを排除する（SSoT）。テーブル名 → スキーマのマッピングは TableSchemaSet が内部で構築する。

### 不変性

生成後は変更不可（スナップショット）。`config/table_schemas/` の YAML を変更したら作り直す。スコープの概念はない（テーブルスキーマ定義はプロジェクト全体で不変）。

### 生成時バリデーション

| 検証項目 | 挙動 |
|---|---|
| テーブル名の一意性 | エラー |
| FK 参照先テーブルの存在 | エラー |
| FK 参照先カラムの存在 | エラー |
| FK カラムの型一致 | エラー |
| column_descriptions 未記述 | エラーにしない（`staqkit validate` で警告） |

### 公開 API

| 問い合わせ | 返る情報 | 利用者 |
|---|---|---|
| テーブル一覧 | テーブル名群 | DataStore 組み立て、CLI |
| テーブル名 → スキーマ | 該当 TableSchema | DataStore、validate |
| カラム名 → 出現箇所 | テーブル名 + カラムの役割（PK/FK/通常）+ description + FK先 | CLI カラム検索 |
| テーブル → FK 参照先 | (カラム, 参照先テーブル, 参照先カラム) の一覧 | DataStore バリデーション、CLI |
| 全 FK 関係 | テーブル間の参照関係グラフ | validate（FK 整合性）、CLI |

API シグネチャの詳細（戻り値の具体的な型）は CLI 体系再検討のあとで確定する。内部データ構造（FK 関係グラフの事前構築 vs 都度走査等）は実装時判断とする。

### TableSchema のフィールド

DDL パース結果として以下を保持する:

| フィールド | 内容 | 導出元 |
|---|---|---|
| table_name | テーブル名 | DDL `CREATE TABLE <name>` |
| columns | カラム名 → 型のマッピング | DDL カラム定義 |
| primary_key | PK カラム名のリスト | DDL `PRIMARY KEY (...)` |
| foreign_keys | FK 定義のリスト（カラム名, 参照先テーブル, 参照先カラム） | DDL `REFERENCES ...` |
| checks | CHECK 制約式のリスト | DDL `CHECK (...)` |
| unique_constraints | UNIQUE 制約のリスト | DDL `UNIQUE (...)` |
| not_null_columns | NOT NULL 指定カラム名のリスト | DDL `NOT NULL` |
| ddl_raw | 生の DDL 文字列（QueryEngine への投入用） | table_schema YAML の `ddl` フィールド |
| description | テーブルの説明 | table_schema YAML の `description` フィールド |
| catalog | カタログ出力対象か | table_schema YAML の `catalog` フィールド |
| column_descriptions | カラム名 → 説明文字列 | table_schema YAML の `column_descriptions` フィールド |

### バリデーションの責務分担

- **TableSchema**: テーブルスキーマ YAML 単体での成立性（例: `column_descriptions` のキーが DDL のカラム定義に存在するか）
- **TableSchemaSet**: 全体としての整合性（例: FK 参照先テーブル・カラムの存在、型一致）

### テーブル登録・エントリ追加との関係

TableSchemaSet はいずれにも関与しない。

- テーブル定義の登録 = `config/table_schemas/` に YAML ファイルを追加（人間の操作）
- エントリ追加 = DataStore の `write_table()`
- QueryEngine = 読み出し特化（register はファイルを VIEW として読めるようにするだけ）

## コンストラクタ

DataStore は解決済みデータのみを受け取る。config パス・StageInfo・scope パラメータは受け取らない。

```python
class DataStore:
    def __init__(
        self,
        tables: dict[str, list[Path]],      # テーブル名 → Parquet パス群（スコープ解決済み）
        schemas: TableSchemaSet,              # プロジェクト全テーブルスキーマの検証済み集合
        output_paths: dict[str, Path] | None = None,  # テーブル名 → 出力先パス
    ): ...
```

- `tables`: Framework 層がスコープ解決した結果。DataStore はこれを QueryEngine に登録する
- `schemas`: `config/table_schemas/` のパース・検証済みスナップショット。DDL の PK/FK 制約からテーブル間関係を導出する
- `output_paths`: `None` なら `write_table` は利用不可（CLI 等の読み取り専用用途）
- DataStore 自体を context manager として提供（`with DataStore(...) as store:`）

### 接続ライフサイクル

DataStore のライフサイクル = QueryEngine 接続のライフサイクル（1:1）。

- run.py: ステージ実行と 1:1。`run_stage` が生成し、終了後に破棄
- CLI: コマンド実行中のみ生存

## ステージ発見

`stages/**/stage.yaml` を再帰走査してステージ一覧を取得。対応する `data/stages/*/` からファイルを読む。ステージ名は `stages/` からの相対パス。

- 定義あり・データなし → planned 状態
- 定義あり・データあり → 通常ステージ
- dvc.yaml のパースに依存しない（DVC 内部構造への密結合を回避）

## DB 組み立て

各ステージの `stage.yaml` の outs セクションを読み、`add_datastore: true` のエントリを同名ファイル（ステム一致）同士で UNION ALL して VIEW 化する。この組み立てロジックは Framework 層に配置される（Discovery の延長、またはファクトリ関数として提供）。

DataStore に渡す前にスコープ解決が完了している:

- run.py 実行時: `run_stage` が inputs の `source_stage` から上流閉包を算出し、該当ステージの出力のみを `tables` に渡す
- CLI `--up-to`: Framework 側が DAG を辿って `tables` を絞り込んでから DataStore に渡す

## 読み取り API

### 高レベル API（query）

```python
def query(self, table: str, filters: dict[str, Any] | None = None) -> pl.DataFrame:
    """バリデーション付きショートカット（等値/IN フィルタ）"""
```

```python
store = DataStore(...)
df = store.query("timeseries", {"subject_id": [1, 2], "dkey": ["A", "B"]})
```

- `table`: 必須。SQL の FROM 句に相当
- `filters`: dict 形式。等値一致（`=`）/ リスト一致（`IN`）のみ
- 範囲条件・JOIN・集計が必要な場合は `fetch()` で SQL を書く
- query() の役割: DDL 情報（TableSchemaSet）を使ったランタイムバリデーション（テーブル名・キー名・型の検証）+ dict → SQL 変換

### 低レベル API（fetch）

```python
def fetch(self, sql: str) -> pl.DataFrame:
    """SQL の全表現力（SELECT 系のみ）。VIEW 定義済みの状態で実行"""
```

```python
df = store.fetch("""
    SELECT t.uid, t.frame, t.value
    FROM timeseries t
    JOIN dtype d ON t.dkey = d.dkey
    WHERE d.data_group = 'joint'
      AND d.coordinate = 'flexion'
""")
```

- SELECT（CTE、VALUES 含む）のみ許可。INSERT/UPDATE/DELETE/DDL は拒否。この制約は QueryEngine Protocol の責務（`fetch` の契約）
- DuckDB 実装では `read_only=True` の接続オプションでエンジンレベルで保証する。SQL パースによる判定は行わない
- 接続オブジェクトは外部に公開しない（エンジン固有 API への依存を防止）

### 戻り値型

`query()` / `fetch()` の戻り値型は `polars.DataFrame` に統一。

- DuckDB とゼロコピー連携可能
- イミュータブルで staqkit の不変性原則と整合
- pandas が必要な場面では `.to_pandas()` で変換可能
- QueryEngine Protocol の差し替え可能性を維持するため、エンジン固有の型は返さない

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
- **書き込んだデータはその DataStore インスタンスからは読めない**（QueryEngine 内の VIEW を変更しない。DataStore は実行中 immutable）。run.py 内では書き込み前の DataFrame を直接保持しているため、再読み込みの必要はない

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
def tables(self) -> list[str]:
    """登録済みテーブル一覧"""

def columns(self, table: str) -> list[str]:
    """カラム名のリスト。存在しないテーブルは KeyError"""

def schema(self, table: str) -> TableSchema:
    """スキーマ定義全体（DDL パース結果 + description + catalog フラグ）。
    存在しないテーブルは KeyError"""
```

- `columns()` は型情報なし。主用途はクエリ組み立て時のカラム名確認。型の不一致は `write_table()` のバリデーションが検出する
- `schema()` は DDL パース結果の全情報を返す。Framework 内部や将来の拡張用途に対応

## テーブル結合のスキーマ契約

DataStore は同名テーブルを全ステージ分 UNION ALL して1つの VIEW にする。全ステージが同一のカラム定義を持つことが要求されるため、`config/table_schemas/` をコンシューマ側の契約として維持し、プロデューサー側の契約は書き込み時バリデーションで実現する。

スキーマ定義は SQL DDL をそのまま記述する。YAML で DDL のサブセットを再発明するのではなく、DuckDB にそのまま渡せる標準 SQL を正統な形式とする。カタログ等のフレームワーク固有メタデータは YAML フィールドとして併記する。

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

- `ddl`: SQL DDL（CREATE TABLE 文）。DDL はエンジン依存（現在は DuckDB）。CHECK 式にエンジン固有関数が含まれ得ることは既知の制約。エンジン差し替え時には DDL のマイグレーションが必要
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

### 検証レベル（config で制御）

```yaml
validation:
    on_read: constraint | schema | off
    on_write: constraint | off
```

**読み込み時**（DataStore 組み立て時）:

- `off`: 検証なし
- `schema`: カラム名・型が DDL と一致するか + ステージ間 UNION ALL 互換性（メタデータのみ、全行スキャン不要）
- `constraint`: schema に加え NOT NULL / PK / UNIQUE / CHECK / FK を全行スキャンで検証

**書き込み時**（write_table）:

- `off`: 検証なし
- `constraint`: カラム名・型 + 全制約検証。PK 重複・FK は既存 VIEW に対する JOIN で検証

書き込み時に `schema`（カラム名・型のみ、制約スキップ）レベルは提供しない。write_table はステージ出力の最終ゲートであり、制約違反を含むデータが DataStore に混入すると下流全体に波及する。開発中の高速イテレーションでは `off` で検証自体を無効化する。

### 検証クエリの生成

- NOT NULL / PK / UNIQUE / FK: DDL から構造的に抽出 → 検証クエリを機械的に生成
- CHECK: DDL から式を抽出し `WHERE NOT (expr)` として実行（エンジン依存の式はそのまま同一エンジンで実行するため問題なし）

### column_descriptions の検証

DDL に記載のカラムに対応する `column_descriptions` がない場合、`staqkit validate` で警告を出力する。エラーにはしない（TableSchemaSet の組み立て自体は可能）。`column_descriptions` に DDL に存在しないカラム名が含まれる場合は TableSchema 生成時にエラー。

## QueryEngine Protocol

### 責務

- Parquet ファイル群を名前付きでクエリ可能にする（VIEW ベースを前提）
- SELECT 系 SQL の実行（読み取り専用を保証）
- 内部リソース（VIEW・接続）のライフサイクル管理

### 責務外

- DDL のパース・制約検証（DataStore 側）
- メタデータ管理（テーブル一覧・カラム情報）（DataStore 側）
- ファイルパスの解決・走査（Framework 層）
- データの正確性保証（register は渡されたものをそのまま登録するだけ）

### Protocol メソッド

```python
class QueryEngine(Protocol):
    def register(self, name: str, files: list[Path]) -> None:
        """files を結合し name でクエリ可能にする"""

    def fetch(self, sql: str) -> pl.DataFrame:
        """SELECT 系の SQL を実行し結果を返す（読み取り専用を保証）"""

    def close(self) -> None:
        """リソース解放"""
```

- `register`: ファイル群を UNION ALL 相当で結合し、指定名でクエリ可能にする。データの正確性は検証しない。全データのメモリコピーを前提としない
- `fetch`: SELECT（CTE、VALUES 含む）のみ許可。INSERT/UPDATE/DELETE/DDL は拒否
- `close`: 内部リソースの解放。DataStore が context manager として `close` を呼び出す

### VIEW vs TABLE

| 観点            | VIEW             | TABLE                  |
| --------------- | ---------------- | ---------------------- |
| register コスト | 軽（参照のみ）   | 重（全データコピー）   |
| クエリ性能      | Parquet 読み取り | メモリアクセス（高速） |

Protocol は VIEW ベースを前提とする。TABLE 対応は将来のパフォーマンス要件に応じて検討する。

## DataStore の組み立て

DataStore の組み立て（stage.yaml 走査 → ファイル収集 → スコープ絞り込み → インスタンス生成）は Framework 層の責務。

- Core 層の DataStore は解決済みデータのみ受け取る
- 組み立てロジックは Framework 層に配置（Discovery の延長、またはファクトリ関数）
- CLI の `--up-to` も Framework 側が DAG を辿って `tables` を絞り込んでから DataStore に渡す

### 外部データアクセス

外部リポジトリからインポートしたデータ用の DataStore は、Framework 層のファクトリ関数として提供する。DataStore 自体は「データが外部由来かどうか」を知る必要がない。ファクトリが外部ディレクトリを走査して `tables` / `schemas` を組み立て、通常のコンストラクタに渡す。

### 非 Parquet データの発見

バイナリファイル（ML モデル等）を DataStore 経由で発見可能にするパターン: パスを格納した Parquet（`add_datastore: true`）+ バイナリ本体（`add_datastore: false`）。DataStore で「どのモデルがどこにあるか」を検索し、実体はパスで直接アクセス。
