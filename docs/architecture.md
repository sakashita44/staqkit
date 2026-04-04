# アーキテクチャ

本文書はツール非依存の設計構造・方針を記述する。各コンポーネントの具体仕様は [components/](components/) に記載するが、DI境界の内側にある部品（QueryEngine等）はインターフェース主体で記述し、具体実装は差し替え可能な選択として扱う。差し替えが現実的でない基盤（Git, DVC）は具体名で直接参照する。

## 概要

staqkit は2層構成を採る。下層の **Core Library** はドメイン非依存の汎用部品群であり、上層の **Framework** がプロジェクト固有の規約を解釈して Core を組み立てる。

```text
src/staqkit/
├── types.py        ← 公開API型（StageInfo, DataStore 等の re-export）
├── core/           ← ドメイン非依存（識別軸定義等の語彙を知らない）
│   ├── models.py
│   ├── query_engine.py
│   ├── schema_validator.py
│   ├── provenance.py
│   └── dag_builder.py
├── framework/      ← 規約の強制（stages/, config/ 等を解釈）
│   ├── datastore.py
│   ├── stage_info.py
│   ├── run_stage.py
│   ├── generator.py
│   └── discovery.py
└── cli/            ← CLIエントリポイント
    └── main.py
```

- `staqkit.types`: run.py 等の利用者向け公開 API。`from staqkit.types import StageInfo, DataStore` が正規インポートパス。framework 内部のモジュールパスを利用者に露出しない
- `staqkit.run_stage`: トップレベルで re-export。`from staqkit import run_stage`

### 層の責務

| 層                            | ドメインスキーマへの依存 | 提供する API                                                     |
| ----------------------------- | ------------------------ | ---------------------------------------------------------------- |
| Core Library（QueryEngine等） | なし                     | `register(name, files)` / `fetch(sql)` / `close()`               |
| Framework（DataStore）        | あり（設定ファイル経由） | `query(table, filters)` / `fetch(sql)` / `write_table(name, df)` |

Core Library はテーブル名とファイルパスのリストだけを受け取る。識別軸の語彙（`subject_id`, `dkey` 等）を一切知らない。Framework 層がプロジェクト設定（`config/axes.yaml`）を読み込み、Core Library を組み立てるファサードとして機能する。

ドメインスキーマ非依存で動く経路（`fetch()` による直接 SQL）を常に提供し、高レベル API を使わない選択肢を公式にサポートする。

### DI境界

QueryEngine は Protocol として定義し、DuckDB実装はその1つの実装である。テスト時のモック差し替えや将来の実装変更に対応する。

## スコープ

### ドメイン依存の局所化

要求I-2（多軸スライス）はフレームワークがドメインの識別軸構造を知ることを要求するが、ドメイン知識への依存は汎用性を損なう。この問題に対し、ドメイン依存をFramework層に局所化し、Core層をドメイン非依存に保つ。設定の最小構成は識別軸定義2行（レコードキー名 + データ種別キー名）で動作する状態を保証する。

### 管理境界

研究データ解析にはパイプラインモデルと本質的にミスマッチする探索的プロセスが不可欠である。フレームワークはこの探索自体を管理しようとせず、管理下（DAGで表現されるデータ）と管理外（notebook等）の境界を明示的に設定する。フレームワークの価値は「探索の結果を信頼できる形で固定し、再現可能にすること」であり、管理境界IF（I-6）の実装品質が持続的利用を決定する。

### フレームワーク固定 vs プロジェクト設定

| 区分               | 内容                                                                                                                                                                                                                                                    |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| フレームワーク固定 | [outs 統一スキーマ](components/stage.md#outs-統一スキーマ)（path + add_datastore）、[分散テーブル統合](components/stage.md#分散テーブルの統合)（UNION ALL + DDL 制約検証）、stage の概念、DuckDB over files クエリエンジン、DataStore クラスの query IF |
| プロジェクト設定   | record_key 階層、識別軸属性、[テーブルスキーマ定義](components/datastore.md#テーブル結合のスキーマ契約)（config/table_schemas/）、stage 名、ファイル配置規約                                                                                            |

### 不変性の保証

不変性は設計原則として掲げるが、Pythonの制約上、構造的強制は採用しない。[DataStore の書き込み](components/datastore.md#書き込み)対象を自ステージの宣言済み outs に限定し、[run_stage エピローグでの検証](components/stage.md#post-run-検証)（期待外変更検出 + エラー報告）+ DVC復元で保証する。

## 概念モデル

要求定義の設計原則（データ依存DAG）を具体化するモデル。

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

### 状態モデル

フレームワーク内の状態は一方向の導出関係に従う。stage.yaml の status がSSoTであり、dvc.yaml は stage.yaml から生成される派生物、実行時の鮮度（dvc status）はさらにその導出である。下流が上流を変更することはない。

| 問い                                       | 回答の源泉                            | 性質                   |
| ------------------------------------------ | ------------------------------------- | ---------------------- |
| このステージはパイプラインに含まれるか     | stage.yaml status + inactive伝搬      | 設計時（人間が宣言）   |
| このステージの出力は最新か                 | dvc status（deps/outsのハッシュ比較） | 実行時（ツールが導出） |
| このステージは何のパラメータで実行されたか | run_meta.yaml                         | 実行時（自動記録）     |

### パイプライン定義の扱い

dvc.yaml は stage.yaml から常に導出可能なため、Git管理対象外とする。DVCネイティブツール（`dvc dag` 等）が直接使えないトレードオフを受容し、SSoTの一元性を優先する。

### 実験追跡

DVC Experimentsは現時点では採用しない。run_meta.yaml が提供するプロヴェナンスチェーン・出力データ型一覧・行数情報はDVC Experimentsでは代替できず、関心の層が異なる。dvc.yaml非Git管理方針との整合性からも現時点では利用不可。後から追加可能な設計を維持する。

### バリデーション

独自実装に明示的な理由がない限り既存ライブラリを優先する。

- **DataFrame スキーマ検証**: DDL パース（sqlglot）+ QueryEngine による検証クエリ。DDL が制約定義の SSoT であり、CHECK 式に DuckDB 固有関数を許容するため、同一エンジンで検査する
- **YAML 設定バリデーション**: Pydantic（stage.yaml, axes.yaml, table_schemas/\*.yaml の外形検証）
- **データクラスバリデーション**: Pydantic dataclasses（StageDefinition, RunMeta 等）
- **DAG 構築・循環検出**: networkx

## 設計原則マッピング

| 設計原則           | 実現手段                                                        |
| ------------------ | --------------------------------------------------------------- |
| 暗黙依存の外部化   | stage.yaml によるパラメータ・入力の明示化、管理境界の明確な設定 |
| 構造的保証         | 状態の一方向導出、axes.yaml によるスキーマ宣言                  |
| データ中心         | DataStore による意味的属性アクセス                              |
| 不変性と純粋関数性 | 状態の一方向導出、検出+エラー+復元による保証                    |
| データ依存DAG      | DVC deps/outs、networkx による構築・検証                        |

## 要求マッピング

| 要求                        | 実現手段                                                                                           |
| --------------------------- | -------------------------------------------------------------------------------------------------- |
| I-1 単一AP                  | DataStore クラスが唯一のアクセスポイント                                                           |
| I-2 多軸スライス            | DataStore.query() + DataStore.fetch()                                                              |
| I-3 一意参照                | 識別軸属性の組み合わせで一意特定                                                                   |
| I-4 DAG紐づき一覧性         | DAGマップ生成ツール（stage.yaml から生成）                                                         |
| I-5 異質データ共存          | format ディスパッチ（Parquet/CSV/pickle/npy）                                                      |
| I-6 管理境界IF              | [StageInfo + DataStore + run_stage](components/stage.md#実行モデル) が管理下/管理外の境界APIを提供 |
| II-1 DAG整合性              | DVC の deps/outs 追跡                                                                              |
| II-2 スナップショット再現性 | DVC + Git                                                                                          |
| II-3 有効性管理             | dvc status + stage.yaml status + inactive 伝搬                                                     |
| II-4 部分再生成             | dvc repro（影響部分木のみ）                                                                        |
| II-5 パラメータ追跡         | stage.yaml の params + DVC params 追跡 + run_meta                                                  |
| III-1 格納中立性            | format ディスパッチ                                                                                |
| III-2 拡張性                | ステージ追加 = ディレクトリ追加                                                                    |
| III-3 意味到達性            | description 3層構造                                                                                |
| IV-1 スナップショット分岐   | Git ブランチ + DVC                                                                                 |
| IV-2 DAG間合成              | dvc import + Framework 層ファクトリ関数による外部データ用 DataStore 生成                           |
| V-1 プロセス切り出し        | ステージ単位のモジュラリティ                                                                       |
| V-2 解析と出力の分離        | ステージ設計による分離                                                                             |

## 情報所在マップ

| 情報                     | SSoT                                      | 格納先                                                           |
| ------------------------ | ----------------------------------------- | ---------------------------------------------------------------- |
| DAG構造                  | dvc.yaml（stages/\*/stage.yaml から生成） | deps / outs                                                      |
| パラメータ               | stages/xxx/stage.yaml                     | params セクション                                                |
| inputs（依存先ステージ） | stages/xxx/stage.yaml                     | inputs セクション（source_stage のみ）                           |
| description（1行）       | stages/xxx/stage.yaml                     | desc フィールド                                                  |
| description（詳細）      | stages/xxx/README.md                      | アルゴリズム説明                                                 |
| planned 状態             | stages/xxx/stage.yaml                     | status フィールド + data/ の有無                                 |
| 出力宣言（outs）         | stages/xxx/stage.yaml                     | outs セクション                                                  |
| 実行メタ（run_meta）     | stages/xxx/run_meta.yaml                  | Git管理。run_id・deps_runs・パラメータスナップショット・ハッシュ |
| 外部依存（extra_deps）   | stages/xxx/stage.yaml                     | extra_deps セクション                                            |
| 処理コード               | stages/xxx/run.py                         | エントリポイント                                                 |
| テーブルカタログ         | `staqkit catalog` の stdout 出力          | 対象テーブルは table_schemas の `catalog: true` で指定           |

## 未解決事項

- 横断パラメータの扱い: 複数ステージで同じ値を参照するケースに対する設計仕様上の解決策
- `staqkit remote` コマンド群の具体設計
- 外部データ用ファクトリ関数の具体設計
