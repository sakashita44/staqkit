# DataStore

データアクセスの唯一のエントリポイント。全ステージのファイルをインメモリクエリエンジン上に VIEW（実データを参照する仮想テーブル）として結合し、SQLまたは高レベルAPIでクエリする。クエリエンジンはProtocolとして定義されており、現在の実装はDuckDB（`:memory:` モード）。

## axes.yaml: 識別軸定義

`config/axes.yaml` でデータの識別軸構造をプロジェクトごとに定義する。フレームワークコードはこの定義を読み込んで動的に動作し、`uid`（レコード一意識別子）や `dkey`（データ種別キー）といった文字列をハードコードしない。

```yaml
# config/axes.yaml

# データテーブルの主キーを構成する識別軸
record:
    key: uid
    hierarchy:
        - name: subject
          key: subject_id
        - name: trial
          key: trial_id

# データ種別の識別軸
data_descriptor:
    key: dkey
    attributes:
        - data_group
        - coordinate
        - body_side
        - unit
        - quantity_type
    meta_table: dtype # dkey の属性定義を格納するテーブル名
```

フレームワークは `config.axes["record"].key → "uid"` のように参照する。

## ステージ発見

`stages/**/stage.yaml` を再帰走査してステージ一覧を取得。対応する `data/stages/*/` からファイルを読む。ステージ名は `stages/` からの相対パス。

- 定義あり・データなし → planned 状態
- 定義あり・データあり → 通常ステージ
- dvc.yaml のパースに依存しない（DVC内部構造への密結合を回避）

## DB組み立て

各ステージの `stage.yaml` の outs セクションを読み、`add_datastore: true` のエントリを同名ファイル（ステム一致）同士で UNION ALL して VIEW 化する。

```python
class DataStore:
    def __init__(self, config_path: str):
        self._engine: QueryEngine = ...  # Protocol経由で注入
        # 1. config/ からテーブルスキーマ定義を読み込み
        # 2. 全ステージの stage.yaml の outs を走査
        # 3. add_datastore: true のエントリを収集し、同名テーブルを UNION ALL で VIEW 化
        # 4. DDL に基づくスキーマバリデーション
        # 5. DDL 制約検証（UNION ALL 後のキー一意性等）

    def scoped(self, up_to: list[str]) -> "DataStore":
        """スコープ付き読み取り専用ビューインスタンスを返す。
        指定ステージからDAGを遡って到達可能な全ステージ（上流閉包）の
        出力のみを VIEW 化する。"""
        ...

    @classmethod
    def from_external(cls, package_path: str) -> "DataStore":
        """外部リポジトリからimportしたデータ用の独立インスタンスを生成"""
        ...
```

- `scoped()` は読み取り専用。書き込み API は利用不可
- run.py では通常 scope なし（deps から自動解決）、CLI では `--up-to` 指定で利用

## 読み取りAPI

### 高レベルAPI（query）

```python
store = DataStore("config/project.yaml")
df = store.query(
    subject_id=[1, 2, 3, 4, 5],
    dkey=["A", "B", "X"],
    stage="normalized"
)
```

頻出パターンのショートカット。SQLを知らなくてもアクセス可能。

### 低レベルAPI（connection）

`connection()` はクエリエンジンへの直接接続を返す。VIEW 設定済みの状態で取得できるため、任意の SQL を実行可能。

```python
con = store.connection()

df = con.sql("""
    SELECT t.uid, t.frame, t.value
    FROM timeseries t
    JOIN dtype d ON t.dkey = d.dkey
    JOIN record r ON t.uid = r.uid
    WHERE d.data_group = 'joint'
      AND d.coordinate = 'flexion'
      AND r.subject_id IN (1, 2, 3, 4, 5)
      AND t.stage = 'normalized'
""").fetchdf()
```

SQLの全表現力が使える（GROUP BY, WINDOW関数, サブクエリ等）。

## 書き込み

`write_table` で StageInfo から出力先パス解決・バリデーション文脈を受け取り、自ステージの宣言済み outs にファイルを配置する。既存データの mutation ではなく、新規ファイル配置のみ。他ステージの成果物を変更する API は存在しない（不変性の構造的保証）。

```python
store.write_table("timeseries", result, stage=stage)
```

- `stage` 引数（StageInfo）から出力先パスと outs 宣言を解決
- StageInfo は frozen dataclass であり、書き込み側が実行文脈を改変するリスクはない
- バリデーション戦略は config で制御: `validation: on_write: strict|warn|off`

### バリデーション（書き込み時）

- **DDL 整合性**: `config/table_schemas/` の DDL 定義とカラム名・型が一致するか
- **制約検証**: DDL で宣言された制約（PRIMARY KEY, UNIQUE, CHECK, FOREIGN KEY, NOT NULL）に違反するデータがないか

### バリデーション（読み込み時）

DataStore コンストラクタでVIEW組み立て時に検証:

- 同名テーブルのカラムスキーマがステージ間で一致するか（UNION ALL 互換性）
- `config/table_schemas/` の DDL 定義と実ファイルのカラムが一致するか

## テーブル結合のスキーマ契約

DataStoreは同名テーブルを全ステージ分 UNION ALL して1つの VIEW にする。全ステージが同一のカラム定義を持つことが要求されるため、`config/table_schemas/` をコンシューマ側の契約として維持し、プロデューサー側の契約は書き込み時バリデーションで実現する。

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
```

- `ddl`: SQL DDL（CREATE TABLE 文）。DuckDB にそのまま渡してスキーマ定義・制約検証に使用。NOT NULL, PRIMARY KEY, UNIQUE, CHECK, FOREIGN KEY 等の制約を表現力の上限なく記述可能
- `description`: テーブルの説明（カタログ出力に使用）
- `catalog`: `staqkit catalog` の出力対象とするか（デフォルト: false）。CLI で `--table` を明示指定した場合はそちらが優先
- 書き込みラッパーが出力前にスキーマとの整合性を検証するため、UNION ALL 互換性チェックに到達する前に捕捉可能
- 「ステージXがテーブルYにカラムZを提供する」という明示的な宣言は存在しない。stage.yaml の outs セクション（`add_datastore: true` のエントリ）が暗黙的に担う

## 外部データアクセス

外部リポジトリからimportしたデータへのアクセスは `DataStore.from_external()` で独立したインスタンスを生成する。自DAGのDataStoreとは完全に分離し、テーブル統合やnamespace衝突の問題を回避する。

### 非Parquetデータの発見

バイナリファイル（MLモデル等）をDataStore経由で発見可能にするパターン: パスを格納したParquet（`add_datastore: true`）+ バイナリ本体（`add_datastore: false`）。DataStoreで「どのモデルがどこにあるか」を検索し、実体はパスで直接アクセス。
