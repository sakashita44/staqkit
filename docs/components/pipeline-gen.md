# パイプライン生成

`dvc.yaml` は `stages/**/stage.yaml` 群から決定的に生成する派生物。人は `stage.yaml` だけを編集する。`dvc.lock` とともに Git 管理し、DVC 自身の鮮度判定・依存グラフ・再実行へ委譲する。staqkit は独自の変更検知・再実行エンジンを持たない。

## CLI ラッパー

```bash
staqkit repro [stage]   # Generate → 最小限 Validate → dvc repro
staqkit status          # Generate → dvc status
staqkit dag             # stage.yaml から宣言済み artifact 間のつながりを表示
staqkit validate        # 参照・DDL・実データの整合性検査
staqkit clean           # 孤児・inactive データ検出
staqkit catalog         # テーブルカタログ表示
```

## 変換の原則

- **producer stage と dependency artifact は異なる粒度。** 1つの DVC stage が複数 outs を生成しても、consumer は `(stage, out)` で選択したファイルだけに依存する。producer をファイルごとに分割しない。
- `inputs.tables` は、選択した上流 artifact のファイルと、その table の DDL への依存を導出する。DataStore も**同じ入力集合**だけを VIEW に登録する。
- `inputs.files` は選択した上流 artifact のファイルだけを導出する。対応する table schema は、テーブルとして解釈しない限り自動依存に含めない。
- `path_deps` は実ファイル／ディレクトリ／glob を DVC deps に渡す。共有 Python コードなども対象。
- `outs.<key>.table` を持つ producer は、出力を検証・生成するためその table の `ddl` に依存する。
- 同じ物理パスが複数箇所から導出された場合、`deps` は正規化・重複排除する。
- **上流の推移閉包の全 outs を列挙しない。** 依存の推移、DAG、順序は DVC が扱う。

## 導出マッピング

| フィールド | 導出元 |
| --- | --- |
| `stage 名` | `stages/` からの相対ディレクトリ名 |
| `cmd` | `python stages/{name}/run.py` |
| `deps` | ①自ステージの `run.py`、② `inputs.tables` と `inputs.files` の選択 artifact の物理パス、③ `path_deps` の実パス |
| `params` | ① `stage.yaml` の `params` 束縛と `inputs.tables` の選択宣言、②各外部パラメータ `(file,key)`、③入力テーブルと出力テーブルの `config/table_schemas/<name>.yaml: [ddl]` |
| `outs` | `outs.<key>.path` から `data/stages/{name}/{path}` |
| `desc` | `stage.yaml` の `desc` |

`inputs.tables` を宣言側の `params` で追跡するのは、物理 `deps` 集合が不変でも、テーブルとして公開する集合を変更した場合には DataStore の可視範囲が変わるため。リスト並べ替えによる不要な再実行などの粒度は、実装前に小さな DVC 検証で確認する。単なる `inputs.files` のローカル alias 改名は、同じファイルへの依存である限り計算内容の変更としては追跡しない。参照先の実在と `outs.<key>.table` の有無は staqkit の宣言検査で判定する。

`outs` 全体をステージの `params` に加えない。出力パスの変更は生成された DVC `outs` の差、table 指定の変更は DDL の依存関係や宣言整合性から追跡する。artifact key の改名だけで再実行は強制せず、他ステージの参照切れは生成・検証時に報告する。producer `run.py` が旧 key を参照した場合は次の実行時にエラーになる。

### DDL と説明文の分離

table schema YAML はファイル丸ごとの `deps` には登録せず、DVC のキー単位 `params` で `ddl` だけを追跡する。これにより `description` / `column_descriptions` / `catalog` などの編集だけでは再実行しない。単位など処理に必要な意味情報は `dtype` 等の artifact または `params` に明示し、説明文を計算ロジックの隠れた入力として用いない。

管理テーブル Parquet の metadata に書き込む `staqkit.schema_sha256` も `ddl` のみを対象とする（[datastore.md](datastore.md#parquet-metadata-の契約)）。metadata の構造契約と DVC の依存範囲を一致させる。

### 実行環境への委譲

uv / pip 等のパッケージ依存および環境ロックファイルは**デフォルトで `deps` にしない**。依存環境そのものはパッケージ管理ツールと Git で記録する。環境の変更だけでは DVC は自動的にステージを再実行せず、手動の再実行で結果が変わった場合は出力ハッシュの変更として追跡される。このトレードオフを許容する。必要なら利用者が `path_deps` にロックファイル等を明示できる。

## 生成例

```yaml
# stages/normalize/stage.yaml
status: active
outs:
    result: {path: result.parquet, table: timeseries}
    figure: {path: summary.png}
params:
    sampling_rate: {file: params/motion.yaml, key: sampling_rate}
inputs:
    tables:
        - {stage: import, out: joint_angle}
        - {stage: import, out: dtype}
    files:
        calibration: {stage: prepare, out: calibration}
path_deps:
    signal_utils: libs/signal_utils.py
```

```yaml
# 生成された dvc.yaml の該当 stage（例）
stages:
    normalize:
        cmd: python stages/normalize/run.py
        deps:
            - stages/normalize/run.py
            - data/stages/import/joint_angle.parquet
            - data/stages/import/dtype.parquet
            - data/stages/prepare/calibration.pkl
            - libs/signal_utils.py
        params:
            - stages/normalize/stage.yaml:
                - params
                - inputs.tables
            - params/motion.yaml:
                - sampling_rate
            - config/table_schemas/timeseries.yaml:
                - ddl
            - config/table_schemas/dtype.yaml:
                - ddl
        outs:
            - data/stages/normalize/result.parquet
            - data/stages/normalize/summary.png
```

`inputs.files` だけで参照した `calibration` に独自の table schema 追跡は付かない。同じ artifact を `inputs.tables` にも指定する場合、`deps` に同一ファイルを重複出力しない。

## ステージ包含と参照整合性

- **active**: effective-active なものを `dvc.yaml` に含める。
- **planned**: `dvc.yaml` に含めない。宣言・DAG 表示には残す。
- **inactive**: `dvc.yaml` に含めない。artifact 依存関係で到達する下流 active も suppressed。
- active が planned の artifact を参照した場合、`staqkit validate` は警告、`staqkit repro` は `ReferenceIntegrityError`。
- `inputs.tables` が `table` 未宣言の out を指す、参照先 stage／out key が存在しない、あるいは依存が循環する場合は宣言検証でエラー。物理パス依存については DVC の欠落チェックも利用する。
- `path_deps` の glob が0件マッチなら生成時エラー。通常のパス不存在は DVC の deps 不在として検出する。

## 整合性の維持

同一の stage 宣言群と staqkit バージョンからはバイト単位で同一の `dvc.yaml` を生成する。キー順・リスト列挙・物理パスを正規化する。編集すべき SSoT は `stage.yaml` のみ。

- 変更時: `staqkit repro` / `add-stage` は `dvc.yaml` を再生成し、変更に応じて Git index を更新する（index 操作の具体的な境界は [#55](https://github.com/sakashita44/staqkit/issues/55)）。
- 利用時: `staqkit repro` / `status` は DVC の呼び出し前に必ず再生成する。`status` 自体は `git add` しない。
- `staqkit validate` は生成される `dvc.yaml` と現存ファイルのパース後の意味比較（`cmd/deps/params/outs/desc`）を行う。

## バリデーション

| 検査 | validate | repro（実行前） |
| --- | --- | --- |
| 生成済み `dvc.yaml` と宣言の整合 | YES | 再生成 |
| artifact 参照の存在・種類・循環 | YES | YES |
| active → planned artifact 参照 | 警告 | エラー |
| path_deps glob の0件一致 | エラー | エラー |
| TableSchemaSet の FK 定義・型整合性 | YES | 原則省略 |
| Parquet metadata / DDL 適合性 | YES | 読み書き時に runtime が検査 |
| `column_descriptions` 未記述 | 警告 | 省略 |

検証の実行相、同一 stage の outs 間 FK と複数 stage 間 PK のチェックは [#54](https://github.com/sakashita44/staqkit/issues/54) に委ねる。