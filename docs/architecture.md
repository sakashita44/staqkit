# アーキテクチャ

本文書はツール非依存の設計構造・方針を記述する。各コンポーネントの具体仕様は [components/](components/) に記載するが、DI境界の内側にある部品（QueryEngine等）はインターフェース主体で記述し、具体実装は差し替え可能な選択として扱う。差し替えが現実的でない基盤（Git, DVC）は具体名で直接参照する。

## 概要

staqkit の正体は「規約を強制する CLI アプリ」と「ステージコードが依存する薄いランタイム」の二面を持つ一つの道具である（[distribution.md](distribution.md)）。本文書はその内部構造を扱う。

実装は2層構成を採る。下層の **Core 層** はドメイン非依存の汎用部品群であり、上層の **Project 層** がプロジェクト固有の規約（`stages/`, `config/` 等）を解釈して Core を組み立てる。CLI 層はこの上に乗るエントリポイントである。

```text
src/staqkit/
├── types.py        ← 公開API型（StageInfo, DataStore 等の re-export）
├── core/           ← ドメイン非依存（識別軸定義等の語彙を知らない）
│   ├── models.py
│   ├── table_schema_set.py
│   ├── query_engine.py
│   ├── schema_validator.py
│   ├── provenance.py
│   └── dag_builder.py
├── project/        ← 規約の強制（stages/, config/ 等を解釈）
│   ├── datastore.py
│   ├── stage_info.py
│   ├── run_stage.py
│   ├── layout.py          ← ProjectLayout（パス規約の SSoT）
│   ├── store_factory.py   ← スコープ解決ファクトリ（build_scoped_engine / open_store）
│   ├── generator.py
│   └── discovery.py
└── cli/            ← CLIエントリポイント
    └── main.py
```

- `staqkit.types`: run.py 等の利用者向け公開 API。`from staqkit.types import StageInfo, DataStore` が正規インポートパス。project 層内部のモジュールパスを利用者に露出しない
- `staqkit.run_stage`: トップレベルで re-export。`from staqkit import run_stage`
- 内部層名 `core / project / cli` は実装上の区分であり、利用者向けの公開インポートパスには現れない

### 層の責務

| 層                       | ドメインスキーマへの依存 | 提供する API                                                                                     |
| ------------------------ | ------------------------ | ------------------------------------------------------------------------------------------------ |
| Core 層（QueryEngine等） | なし                     | EngineBuilder: `register(name, files)` / `seal()`、QueryEngine: `fetch(sql, params)` / `close()` |
| Project 層（DataStore）  | あり（設定ファイル経由） | `query(table, filters, columns)` / `fetch(sql, params)` / `write_table(name, df)`                |

Core 層はテーブル名とファイルパスのリストだけを受け取る。識別軸の語彙（`subject_id`, `dkey` 等）を一切知らない。Project 層がプロジェクト設定（`config/table_schemas/`）を読み込み、Core 層を組み立てる。

### スコープ解決ファクトリと依存方向

スコープ解決（stage.yaml 走査・ファイル収集・スコープ絞り込み・VIEW 登録・DDL 検証）は Project 層の **スコープ解決ファクトリ**に集約する。これは DataStore と CLI が共有する土台であり、クラスではなく関数群として、組み立てフローの各ステップを独立した単位で提供する（具体仕様は [datastore.md](components/datastore.md#スコープ解決ファクトリ)）。利用者向けの入口は二段に分かれる。

- `build_scoped_engine(scope, layout, schemas) -> QueryEngine`: 解決済みスコープから read-only の QueryEngine を返す低レベル入口
- `open_store(stage, schemas, *, writable) -> DataStore`: run.py 向けの高レベル入口。`StageInfo` 一つから読み取りスコープ（inputs 由来）と書き込み対象（outs 由来）を導出し、内部で `build_scoped_engine` を用いる

依存方向は次のとおりに引く。**CLI のデータ参照コマンド（catalog / validate）は DataStore ファサードに依存せず、スコープ解決ファクトリ（+ Core の SchemaValidator）に依存する**。DataStore は run.py / notebook 向けの祝福されたメイン経路であり、CLI はランタイムのファサードを介さず同じ土台を直接使う。両者はファサードを共有しないため、データ参照のために CLI が DataStore を import することはない。

ドメインスキーマ非依存で動く経路（`fetch()` による直接 SQL）を常に提供する。これは祝福されたメイン経路（`query()`）に対する無保証の抜け道であり、詳細は[設計方針](#守る契約とアクセス経路の保証グラデーション)に従う。

### ProjectLayout

プロジェクトのディレクトリ規約（`stages/`, `config/table_schemas/`, `data/stages/` 等の配置と命名）は ProjectLayout が単一の出所として保持する。パスを構築する処理（スコープ解決ファクトリ・パイプライン生成・StageInfo）はパスを直接組み立てず、すべて ProjectLayout に委譲する。これによりディレクトリ規約の変更が一箇所に閉じる。

ProjectLayout は frozen dataclass であり、プロジェクトルートから各種パスを導出する。

- `root`: プロジェクトルート
- `stages_dir` / `table_schemas_dir` / `data_stages_dir` 等: 規約上の固定ディレクトリ（root からの導出）
- `stage_data_dir(stage_name)`: 当該ステージの出力ディレクトリ（`data/stages/<stage_name>/`）
- `out_abs_path(stage_name, outs_path)`: outs の相対パスから絶対出力パスを解決

テスト時は `ProjectLayout(root=tmp_path)` を与えることで、実ディレクトリに依存せず組み立て・パス解決を検証できる。

### エンジン差し替え性の二分割

差し替え性は二つの異なるものに分けて扱う。

- **ユーザ契約としての差し替え性**: 採らない。DuckDB を staqkit の IF=契約として固定する。staqkit は DuckDB をデータ格納先ではなくクエリ IF としてのみ用いる（データ実体は parquet、エンジンは `:memory:`）ため、IF を契約として固定することに無理はない。
- **保守者アフォーダンスとしての差し替え性**: 残す。将来の保守者（自分を含む）が限定された労力でエンジンや戻り値ライブラリを置換できる構造を保つ。保証ではなく「差し替えやすさ」である。

この方針に従い、QueryEngine は Protocol として定義する。目的は「利用者が DuckDB に依存しないようにする」ことではなく、「保守者がエンジンを置換できる継ぎ目を一箇所に集める」ことである。テスト時のモック差し替えも同じ継ぎ目で行う。戻り値の Polars も同様に継ぎ目を局所化し、将来より良いライブラリへ移行する場合のコストを bounded に保つ。

### migration surface

エンジン置換時に触れる必要がある箇所を migration surface として明示する。差し替え性は best-effort であり、これらの存在は矛盾ではなく「置換時の作業範囲」を意味する。

- DDL（table_schemas の `ddl`）は DuckDB SQL であり、CHECK 式にエンジン固有関数を含みうる。置換時は DDL のマイグレーションを伴う
- `fetch()` に渡される SQL の方言
- QueryEngine Protocol の実装本体と、戻り値 Polars への変換

## スコープ

### ドメイン依存の局所化

要求 U2（多軸クエリ面）はstaqkit がドメインの識別軸構造を知ることを要求するが、ドメイン知識への依存は汎用性を損なう。この問題に対し、ドメイン依存を Project 層に局所化し、Core 層をドメイン非依存に保つ。識別軸の構造は DDL の PK/FK 制約から導出し、staqkit がドメイン固有の語彙を予約語として持たない設計とする。

### 管理境界

研究データ解析にはパイプラインモデルと本質的にミスマッチする探索的プロセスが不可欠である。staqkit はこの探索自体を管理しようとせず、管理下（DAGで表現されるデータ）と管理外（notebook等）の境界を明示的に設定する。staqkit の価値は「探索の結果を信頼できる形で固定し、再現可能にすること」であり、管理境界インターフェースの実装品質が持続的利用を決定する。

### staqkit 固定 vs プロジェクト設定

| 区分             | 内容                                                                                                                                                                                                                                                    |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| staqkit 固定     | [outs 統一スキーマ](components/stage.md#outs-統一スキーマ)（path + add_datastore）、[分散テーブル統合](components/stage.md#分散テーブルの統合)（UNION ALL + DDL 制約検証）、stage の概念、DuckDB over files クエリエンジン、DataStore クラスの query IF |
| プロジェクト設定 | [テーブルスキーマ定義](components/datastore.md#テーブル結合のスキーマ契約)（config/table_schemas/、PK/FK で識別軸の階層構造を表現）、stage 名、ファイル配置規約                                                                                         |

### 不変性の保証

不変性は設計原則として掲げるが、Pythonの制約上、構造的強制は採用しない。[DataStore の書き込み](components/datastore.md#書き込み)対象を自ステージの宣言済み outs に限定し、[run_stage エピローグでの検証](components/stage.md#post-run-検証)（期待外変更検出 + エラー報告）+ DVC復元で保証する。

## 概念モデル

要求定義の基盤モデル（データ依存DAG）を具体化するモデル。

| 概念                 | DAG上の位置                    | 性質                                                                                                                               |
| -------------------- | ------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------- |
| **ノード**           | データ（全て等質）             | valid/invalid/plannedの3状態。ソースノード（生データ）も例外ではない。「中間」「最終」の区別はなく、端か否かは構造的位置に過ぎない |
| **辺**               | 処理ステップ                   | 純粋関数 `f(入力, パラメータ) → 出力`                                                                                              |
| **パラメータ**       | 辺に付随（ノードではない）     | 処理の振る舞い制御値。上流ノードの知識なしに記述可能。変更→下流無効化                                                              |
| **データ利用範囲**   | 辺に付随（パラメータとは独立） | 辺が上流ノードのどの属性範囲を参照するかを属性語彙で記述。上流ノードの属性構造に依存する                                           |
| **出力IF**           | ノードの属性                   | データ形式定義。実体に先行して定義可能。IF変更時の影響は直後の辺までに局所化                                                       |
| **スナップショット** | DAG全体の状態記録              | ある時点での全ノードの有効性状態 + 全辺のパラメータ値。いつ切るかはワークフロー側の判断                                            |

探索もDAG内の操作として表現される。「探索」= 仮説的なノードと辺を作る操作、「確定」= 実データを生成してvalid状態にする操作。正式/仮の二分法ではなく状態遷移で表現。

## 設計方針

### 守る契約とアクセス経路の保証グラデーション

staqkit が後方互換を守る対象は段階づけられる。強制ではなく保証を目的とする。よく分かっていない利用者（引き継いだ後輩等）が通るメイン経路には保証を付け、それ以外の経路は使えるが保証しない。

- **ファイル形式・CLI**: 硬い契約。stage.yaml・table_schemas の DDL・ディレクトリ規約・CLI コマンドは壊さない。第三者が内部を読まずに再現・理解・拡張するとき実際に触れるのはこの面である（信頼・理解・独立の三柱の読み手はファイルと CLI を見る）
- **DataStore の祝福された API（`query` / `write_table`）**: 柔らかい契約。run.py / notebook のメイン経路として best-effort で安定を保つ
- **`fetch()` の生 SQL**: 動くが無保証。`query()` の契約検証は失うが、スコープ安全と read-only は維持される（抜け道に降りても重要な保証は残る）
- **コネクション直結**: staqkit 実装内では開けない。スコープ安全が崩れ、保守者の差し替え性も損なうため。最深の抜け道は `fetch()` までとする

再現性はこの API 安定性からではなく、バージョン固定（`uv.lock`）から得られる。スナップショットは記録された staqkit バージョンで再実行されるため、API が将来変化しても固定済みスナップショットは再現する。

### 機能配置の規則

新機能の所属を次の規則で判断し、ランタイム面の肥大を防ぐ。

- プロセス内クエリに触れる機能 → DataStore（およびスコープ解決ファクトリ）
- リポジトリ操作（メタデータ・dvc/git 呼び出し）→ CLI サブコマンド

### 横断パラメータ

複数ステージが同じ値を用いる場合、値を各 stage.yaml に重複記述せず、定義元（最初にその値を用いる上流ステージ）の param を下流が `params` の値として参照する（`{ from: <上流ステージ> }`、[stage.md](components/stage.md#params-の上流参照横断パラメータ)）。共有専用の置き場所も専用セクションも設けない。これは stage.yaml 自身が既に DVC の params ファイルとして参照されている構造の延長であり、値の SSoT を定義元に一本化しつつ、参照側に依存の明示性を残す。使われない値は定義されない（最初に使うステージで定義される）ため、どのステージにも属さない宙に浮いた共有定数は生じない。

### 状態モデル

staqkit 内の状態は一方向の導出関係に従う。stage.yaml の status がSSoTであり、dvc.yaml は stage.yaml から生成される派生物、実行時の鮮度（dvc status）はさらにその導出である。下流が上流を変更することはない。

| 問い                                       | 回答の源泉                            | 性質                               |
| ------------------------------------------ | ------------------------------------- | ---------------------------------- |
| このステージはパイプラインに含まれるか     | stage.yaml status + inactive伝搬      | 設計時（人間が宣言）               |
| このステージの出力は最新か                 | dvc status（deps/outsのハッシュ比較） | 実行時（ツールが導出）             |
| このステージは何のパラメータで実行されたか | dvc.lock（params）+ git 履歴          | 実行時（DVC が commit 単位で記録） |

### パイプライン定義の扱い

dvc.yaml は stage.yaml から常に導出可能なため、Git管理対象外とする。DVCネイティブツール（`dvc dag` 等）が直接使えないトレードオフを受容し、SSoTの一元性を優先する。

### 実験追跡

DVC Experimentsは現時点では採用しない。来歴追跡（`dvc.lock` + git 履歴からの導出）とは関心の層が異なり、dvc.yaml 非Git管理方針との整合性からも現時点では利用不可。後から追加可能な設計を維持する。

### バリデーション

独自実装に明示的な理由がない限り既存ライブラリを優先する。

- **DataFrame スキーマ検証**: DDL パース（sqlglot）+ QueryEngine による検証クエリ。DDL が制約定義の SSoT であり、CHECK 式に DuckDB 固有関数を許容するため、同一エンジンで検査する
- **YAML 設定バリデーション**: Pydantic（stage.yaml, table_schemas/\*.yaml の外形検証）
- **データクラスバリデーション**: Pydantic dataclasses（StageDefinition, TableSchema 等）
- **DAG 構築・循環検出**: networkx

### エラーハンドリング

staqkit の例外は単一の基底 `StaqkitError` から派生し、失敗の性質で4系統に分ける。系統は[アクセス経路の保証グラデーション](#守る契約とアクセス経路の保証グラデーション)と対応し、利用者・CLI は系統単位で捕捉できる。本階層は実行を止める例外の分類であり、検査が報告する警告（`column_descriptions` 未記述、active が planned を参照する等）は例外を投げず[人間向けエラー報告](#人間向けエラー報告)の警告チャネルで扱う。パラメータ整合（stage.yaml の params と実行時実値の乖離）はどの系統にも割り当てない。params 編集による鮮度低下は、params を決定的に追跡する `dvc status`（[状態モデル](#状態モデル)）が担う。来歴（実行時パラメータ・入出力ハッシュ・実行系譜）は `dvc.lock` + git 履歴を源泉とし、独立した実行記録ファイルを持たないため、記録と実体が乖離して検証を要する事態自体が生じない（[stage.md](components/stage.md#専用の実行記録を持たない理由)）。

| 系統                  | 何の失敗か                                          | 主な発生源                              |
| --------------------- | --------------------------------------------------- | --------------------------------------- |
| `ConfigError`         | 設定ファイルの構造的誤り（データ実体不問・設計時）  | table_schemas/ の DDL、stage.yaml、参照 |
| `ValidationError`     | データ実体がスキーマ契約に反する                    | DataStore の read/write 検証            |
| `AccessError`         | アクセス経路の保証（スコープ安全・read-only）の違反 | DataStore の query/fetch/write_table    |
| `StageExecutionError` | ステージ実行後検証の失敗                            | run_stage エピローグ                    |

系統の第一の判別軸は失敗が判明する時点である。設定の読み込み・グラフ構築時（`load_schema_set` / `discover_stages` / パイプライン生成）に判明する誤りは `ConfigError`、データへの問い合わせ・書き込みの実行時に判明する違反は `ValidationError` / `AccessError` となる。

各系統の代表的な具体型は次のとおり。

- `ConfigError`
    - `SchemaDefinitionError`: DDL パース失敗、table_schema YAML 単体の外形違反（`column_descriptions` が DDL 不在カラムを参照する等）
    - `StageDefinitionError`: stage.yaml の外形違反、outs key 重複、add_datastore クロス検証違反
    - `ReferenceIntegrityError`: 参照の解決可能性一般の失敗。source_stage 不在、FK 参照先テーブル・カラム不在、DAG 循環、active が planned を参照（[stage.md](components/stage.md#active-が-planned-を参照した場合)）、外部取り込みポインタ（repo.url + rev_lock）の構造的不整合（記録の欠落・不正形式）。remote への runtime 到達性・解決は DVC/Git の責務でこの階層の対象外（[external-data.md](components/external-data.md#上流dag理解)）
- `ValidationError`
    - `SchemaMismatchError`: カラム名・型不一致、ステージ間 UNION ALL 非互換
    - `ConstraintViolationError`: NOT NULL / PK / UNIQUE / CHECK / FK 違反
- `AccessError`
    - `ScopeError`: スコープ外（未登録 VIEW）テーブルの参照、query() の不正テーブル名
    - `WriteError`: read-only インスタンスへの write、自ステージ outs 外への write
- `StageExecutionError`: post-run 検証で未生成ファイル（declared − actual）を検出した場合等

層配置は依存方向（Project → Core）に従う。基底 `StaqkitError` と系統基底 `ConfigError` / `ValidationError` / `AccessError` は Core 層に置く。`StageExecutionError` は run_stage（Project）だけが送出するため Project 層に置く。具体型は送出箇所の層に置き、対応する系統基底を継承する。ただし複数の層から送出される具体型は、すべての送出元が参照できるよう最下層（Core）に置く。これにより `SchemaDefinitionError`・`ValidationError` 系・`ScopeError`・`ReferenceIntegrityError` は Core、`StageDefinitionError`・`WriteError` は Project となる。`ReferenceIntegrityError` は DAG 循環・FK 参照先不在を Core（DAGBuilder / TableSchemaSet）が、source_stage 不在・active が planned を参照・外部取り込みポインタの構造的不整合を Project（Discovery / Generator）が送出する両層またがりの型のため、双方から参照できる Core 側に置く。Project の具体型が Core の系統基底を継承するのは依存方向に沿う。系統基底（性質の分類）と送出層（実装上の所在）は独立であり、たとえば `ConfigError` は Core に置くが具体型 `StageDefinitionError` は Project が送出する。利用者が捕捉する公開面は `staqkit.errors` に re-export する。

#### 人間向けエラー報告

`staqkit validate` / `staqkit repro` は機械可読な例外を、解析者が直せる形に整形して報告する。

- 失敗を源泉（`config/` / `stages/` / `data/`）でグループ化する
- 各項目に「場所（ファイルパスや stage 名）・原因・直し方」を併記する
- エラーと警告を区別し、末尾にサマリ行（件数）を出して非ゼロ終了する（警告のみなら 0 終了）

```text
$ staqkit validate
config/table_schemas/
  error  timeseries.yaml: FK 参照先テーブル 'dtype' が存在しない
         直し方: config/table_schemas/dtype.yaml を作成するか REFERENCES 先を修正
stages/
  error  normalize: source_stage 'import' が存在しない (stages/normalize/stage.yaml)
         直し方: inputs.source_stage を実在するステージ名に修正
  warn   analyze: 依存先 'preprocess' は planned（データ未生成）
         直し方: preprocess を実装するまで analyze は repro できない

2 errors, 1 warning
```

## 設計原則マッピング

| 設計原則         | 実現手段                                                                                             |
| ---------------- | ---------------------------------------------------------------------------------------------------- |
| 設計ファースト   | 実体に先立つ宣言（DDL によるスキーマ宣言、planned ノード、出力 IF 定義）、設定ファイル自身の契約検証 |
| 暗黙依存の外部化 | stage.yaml によるパラメータ・入力の明示化、管理境界の明確な設定                                      |
| データ中心       | DataStore による意味的属性アクセス、データからの来歴到達                                             |

## 要求マッピング

核要求:

| 要求                | 実現手段                                                                                 |
| ------------------- | ---------------------------------------------------------------------------------------- |
| T1 来歴到達性       | git 管理 `dvc.lock`（params・ハッシュ）+ git 履歴からの来歴チェーン導出                  |
| U1 意味的同一性     | 識別軸属性（DDL の PK）の組み合わせによる一意特定                                        |
| U2 多軸クエリ面     | DataStore クラス（唯一の読み取り口）の query() + fetch()                                 |
| U3 カタログ         | スキーマ構造の出力（schema / column）+ 参照テーブルの目録出力（catalog）+ DAG マップ生成 |
| U4 意味到達性       | description 3層構造 + column_descriptions                                                |
| M1 契約強制         | DDL（table_schemas）による契約宣言 + DataStore 読み書き時の検証                          |
| M2 不変性と純粋関数 | 書き込み対象の outs 限定 + run_stage エピローグ検証 + DVC 復元                           |

委譲する関心:

| 関心                   | 実現手段                    |
| ---------------------- | --------------------------- |
| スナップショット再現性 | DVC + Git                   |
| DAG 整合性・鮮度       | DVC deps/outs + dvc status  |
| 部分再生成             | dvc repro（影響部分木のみ） |
| スナップショット分岐   | Git ブランチ + DVC          |

核要求から派生する事項:

| 派生事項                   | 実現手段                                                                                             |
| -------------------------- | ---------------------------------------------------------------------------------------------------- |
| 異質データ共存             | format ディスパッチ（Parquet/CSV/pickle/npy）                                                        |
| 管理境界インターフェース   | [StageInfo + DataStore + run_stage](components/stage.md#実行モデル) が管理下/管理外の境界 API を提供 |
| 拡張性                     | ステージ追加 = ディレクトリ追加                                                                      |
| リポジトリ境界を越えた合成 | dvc import（外部データをソースとして取り込み）+ 取り込みステージによる DataStore 統合                |
| 設計時のステージ状態       | stage.yaml status + inactive 伝搬                                                                    |
| 解析と出力の分離           | ステージ設計による分離                                                                               |

## 情報所在マップ

| 情報                           | SSoT                                      | 格納先                                                                      |
| ------------------------------ | ----------------------------------------- | --------------------------------------------------------------------------- |
| DAG構造                        | dvc.yaml（stages/\*/stage.yaml から生成） | deps / outs                                                                 |
| パラメータ                     | stages/xxx/stage.yaml                     | params セクション                                                           |
| 横断参照パラメータ             | 定義元 stages/xxx/stage.yaml              | 参照側は params 内で `{ from: <上流ステージ> }` として参照                  |
| inputs（依存先ステージ）       | stages/xxx/stage.yaml                     | inputs セクション（source_stage のみ）                                      |
| description（1行）             | stages/xxx/stage.yaml                     | desc フィールド                                                             |
| description（詳細）            | stages/xxx/README.md                      | アルゴリズム説明                                                            |
| planned 状態                   | stages/xxx/stage.yaml                     | status フィールド + data/ の有無                                            |
| 出力宣言（outs）               | stages/xxx/stage.yaml                     | outs セクション                                                             |
| 来歴（params・ハッシュ・系譜） | dvc.lock + git 履歴                       | Git管理の dvc.lock（stage.yaml から生成）を源泉に provenance/history が導出 |
| 外部依存（extra_deps）         | stages/xxx/stage.yaml                     | extra_deps セクション                                                       |
| 処理コード                     | stages/xxx/run.py                         | エントリポイント                                                            |
| テーブルカタログ               | `staqkit catalog` の stdout 出力          | 対象テーブルは table_schemas の `catalog: true` で指定                      |

## 未解決事項

- `staqkit remote` コマンド群の具体設計
