# パイプライン生成

dvc.yaml は `stages/*/stage.yaml` 群から生成される派生物であり、`dvc.lock` と対で Git 管理する。ルートに単一の dvc.yaml を生成する。stage.yaml が SSoT であり、dvc.yaml は手編集の対象としない（再生成で上書きされる）。

`dvc.lock` は各ステージの実行時パラメータ・入出力ハッシュを commit 単位で記録するため、来歴追跡（T1）の源泉も兼ねる。`staqkit provenance` / `staqkit history` は `dvc.lock` と git 履歴からチェーンを導出する（[stage.md](stage.md#来歴の所在)）。

## CLIラッパー

パイプライン関連の主要コマンド。全コマンドの詳細は [CLI リファレンス](cli.md) を参照。

```bash
staqkit repro [stage]       # 1. Generate → 2. Validate(最小限) → 3. dvc repro
staqkit status              # 1. Generate → 2. dvc status
staqkit dag                 # stage.yaml から直接生成（dvc.yaml 不要）
staqkit validate            # フルチェック（参照整合性 + スキーマ検証全般）
staqkit clean               # 孤児・inactive データ検出（--remove で削除）
staqkit catalog             # テーブルカタログ出力（→ stdout）
```

## 導出マッピング

| dvc.yaml フィールド | 導出元                                                                                                                                                                                                                                                                                                    |
| ------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| stage 名            | stages/ からの相対ディレクトリパス                                                                                                                                                                                                                                                                        |
| cmd                 | `python stages/{name}/run.py`                                                                                                                                                                                                                                                                             |
| deps                | ① `stages/{name}/run.py`（自身のコード）② inputs の source_stage 群とその全上流ステージの outs ファイル（推移的に展開）③ 自ステージの outs テーブル名に対応する table_schema の実ファイルパス（`config/table_schemas/**/*.yaml` からテーブル名で解決。サブディレクトリ配置を許容）④ extra_deps の各 value |
| params              | `stage.yaml` の `params`・`inputs` キー（`stages/{name}/stage.yaml: [params, inputs]`）で束縛宣言自体を追跡。加えて `params` の各束縛の右辺 `(file, key)` を `file` 単位にまとめ、`<file>: [<key>, ...]` として展開する（[stage.md](stage.md#params外部ファイル参照)）                                    |
| outs                | stage.yaml の outs の各 path から `data/stages/{name}/{path}` を生成                                                                                                                                                                                                                                      |
| desc                | stage.yaml の desc                                                                                                                                                                                                                                                                                        |

② の範囲は `open_store` がステージへ与える読み取りスコープ（inputs 由来の上流閉包）と一致する（[datastore.md](datastore.md#スコープ解決ファクトリ)）。ステージは上流閉包内の同名テーブルを UNION ALL した VIEW を引くため、祖先ステージの出力も直接の入力となる。

## 再実行範囲の粒度

DVC は deps に並ぶ各パスのハッシュを `dvc.lock` と突き合わせ、差のあるステージを再実行する。下流への伝搬もハッシュを経由し、再実行された上流の出力ハッシュが変化したときに下流が対象となる。

deps に並ぶ上流ステージの outs（[導出マッピング](#導出マッピング)）は source_stage 群とその全上流の出力全体であり、下流が読まない出力も含む。したがって、図や付随ファイルのように下流の処理に入らない出力のハッシュが変化した場合も、下流ステージは再実行の対象になる。この挙動は仕様として受容する。

params はキー単位、table_schemas はファイル単位、extra_deps は宣言した値の単位（ファイルまたはディレクトリ）で追跡される。ステージ単位に丸まるのは inputs 由来の deps である。

## ステージ包含ルール

- **active**: dvc.yaml に含める
- **planned**: dvc.yaml に含めない（DAG可視化は stage.yaml ベースで別途生成）
- **inactive**: dvc.yaml に含めない。下流も再帰的に除外

active ステージが inputs で planned ステージを参照する場合、参照先 outs は dvc.yaml に存在せず実行できない。`staqkit validate` は警告に留め、`staqkit repro` は `ReferenceIntegrityError` で停止する（[stage.md](stage.md#active-が-planned-を参照した場合)）。検査は実行対象（effective-active）にのみ発火するため、planned から planned への参照は対象外。

## 生成の決定性

同一の stage.yaml 群と同一の staqkit バージョンからは、バイト単位で同一の dvc.yaml を生成する。ステージの列挙順・キー順・フォーマットを正規化し、生成に環境依存の要素を含めない。整合検査はこの決定性を前提とする。

## 整合性の維持

stage.yaml と dvc.yaml の同期点を二つ置く。

- 変更時: パイプライン状態を進めるコマンド（repro / add-stage）は dvc.yaml を再生成し、変更があれば `git add` まで行う。add の対象は各コマンドが書き換えたパイプラインファイルに限る（repro は dvc.yaml と dvc.lock、add-stage は dvc.yaml と新規ステージの生成物）
- 利用時: dvc をラップするコマンド（repro / status）は dvc 呼び出しの前に必ず再生成する。dvc が古い dvc.yaml を参照して動く経路を staqkit コマンド上に残さない。status は再生成で dvc.yaml が変化した場合その旨を出力に含め、`git add` は行わない

`staqkit validate` は dvc.yaml が stage.yaml 群からの生成結果と一致することを検査する。比較はパース後の意味比較（ステージ集合・cmd・deps・params・outs・desc）で行う。バイト比較を避けるのは、staqkit バージョン間のフォーマット差が過去スナップショットの検査で偽陽性になることを防ぐためである。

この構成での整合保証は次のとおり。staqkit コマンドを経由した操作では乖離は発生しない。staqkit を経由しない変更（stage.yaml の手編集後の直接コミット、merge による書き換え等）で乖離したコミットが生じた場合も、任意のスナップショットに対する `staqkit validate` で検出できる。コミット時の自動検査（pre-commit フック）と CI での validate 実行は雛形が提供する（[distribution.md](../distribution.md#雛形と改善の伝播)）。これらの有効化は利用者の設定（`pre-commit install`、ブランチ保護）に依る。

## バリデーション

| 検査項目                                           | validate（フル） | repro（最小限）               |
| -------------------------------------------------- | ---------------- | ----------------------------- |
| dvc.yaml と stage.yaml の整合                      | YES              | ---（実行前再生成で常に成立） |
| 参照整合性（source_stage 実在・循環検出）          | YES              | YES                           |
| active が planned を inputs 参照                   | YES（警告）      | YES（エラー）                 |
| extra_deps の glob が 0 件マッチ                   | YES（エラー）    | YES（エラー）                 |
| スキーマ整合性（parquet vs config/table_schemas/） | YES              | ---                           |
| TableSchemaSet 整合性（FK 参照先・型一致）         | YES              | ---                           |
| column_descriptions 未記述                         | YES（警告）      | ---                           |

`staqkit validate` の各検査群は `--target schema|references|descriptions` で個別実行でき、編集ループ中の部分検証に使える（[cli.md](cli.md#staqkit-validate)）。

## 生成例

stage.yaml:

```yaml
# stages/normalize/stage.yaml
desc: "生データの正規化"
status: active
outs:
    timeseries:
        path: timeseries.parquet
        add_datastore: true
    dtype:
        path: dtype.parquet
        add_datastore: true
params:
    method: { file: params/normalize.yaml, key: method }
    sampling_rate: { file: params/motion.yaml, key: sampling_rate }
inputs:
    - source_stage: import
```

生成される dvc.yaml:

```yaml
stages:
    normalize:
        cmd: python stages/normalize/run.py
        deps:
            - stages/normalize/run.py
            - data/stages/import/timeseries.parquet
            - data/stages/import/dtype.parquet
            - data/stages/import/record.parquet
            - config/table_schemas/timeseries.yaml
            - config/table_schemas/dtype.yaml
        params:
            - stages/normalize/stage.yaml:
                  - params
                  - inputs
            - params/normalize.yaml:
                  - method
            - params/motion.yaml:
                  - sampling_rate
        outs:
            - data/stages/normalize/timeseries.parquet
            - data/stages/normalize/dtype.parquet
        desc: "生データの正規化"
```
