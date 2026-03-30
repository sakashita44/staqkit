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
        # 4. dkey 重複チェック
        # 5. テーブルスキーマに基づくバリデーション

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

```python
con = store.connection()  # クエリエンジン接続（VIEW設定済み）
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
store.write_table("dtype", dtype_df, stage=stage)
```

- `stage` 引数（StageInfo）から出力先パスと outs 宣言を解決
- StageInfo は frozen dataclass であり、書き込み側が実行文脈を改変するリスクはない
- バリデーション戦略は config で制御: `validation: on_write: strict|warn|off`

### バリデーション（書き込み時）

- **スキーマ整合性**: `config/table_schemas/` の定義とカラム名・型が一致するか
- **dkey 整合性**: 出力データの dkey が dtype.parquet の定義と一致するか
- **record_key 整合性**: uid 等のレコードキーが record 定義と整合するか
- **NULL・型チェック**: required カラムの NULL 欠損、型不一致

### バリデーション（読み込み時）

DataStore コンストラクタでVIEW組み立て時に検証:

- 同名テーブルのカラムスキーマがステージ間で一致するか（UNION ALL 互換性）
- `config/table_schemas/` の定義と実ファイルのカラムが一致するか

## テーブル結合のスキーマ契約

DataStoreは同名テーブルを全ステージ分 UNION ALL して1つの VIEW にする。全ステージが同一のカラム定義を持つことが要求されるため、`config/table_schemas/` をコンシューマ側の契約として維持し、プロデューサー側の契約は書き込み時バリデーションで実現する。

- `config/table_schemas/` がテーブルごとのカラム名・型・制約を定義
- 書き込みラッパーが出力前にスキーマとの整合性を検証するため、UNION ALL 互換性チェックに到達する前に捕捉可能
- 「ステージXがテーブルYにカラムZを提供する」という明示的な宣言は存在しない。stage.yaml の outs セクション（`add_datastore: true` のエントリ）が暗黙的に担う

## 外部データアクセス

外部リポジトリからimportしたデータへのアクセスは `DataStore.from_external()` で独立したインスタンスを生成する。自DAGのDataStoreとは完全に分離し、テーブル統合やnamespace衝突の問題を回避する。

### 非Parquetデータの発見

バイナリファイル（MLモデル等）をDataStore経由で発見可能にするパターン: パスを格納したParquet（`add_datastore: true`）+ バイナリ本体（`add_datastore: false`）。DataStoreで「どのモデルがどこにあるか」を検索し、実体はパスで直接アクセス。
