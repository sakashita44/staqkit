# 位置づけと配布

staqkit の配布形態と改善の伝播を定める。

## 概念

staqkit は、規約を強制する CLI アプリと、ステージコードが依存する薄いランタイムにより、解析者の暗黙的な依存を外部化し、追跡性を構造的に保証することを目指す。再現性の中核は Git と DVC へ委譲する（[requirements.md](requirements.md#委譲する関心とツール)）。利用者は自分の解析リポジトリを staqkit の規約（`stages/`, `config/`, `data/` の構成、stage.yaml、table_schemas の DDL）に沿って構成し、`staqkit` コマンドでそれを検証・実行・調査する。各ステージの run.py は staqkit のランタイム（`run_stage`, `StageInfo`, `DataStore`）を import し、staqkit が文脈を注入する。

## 配布

staqkit は単一の Python パッケージとして配布する。

- **`uv add staqkit`（必須）**: run.py が `import staqkit` する以上、解析プロジェクトの仮想環境に staqkit が存在しなければならない。DVC は `python stages/X/run.py` をこの環境で実行する。これはランタイムとしての staqkit が要求する前提である。
- **`uv tool install staqkit`（任意）**: どのプロジェクトの外でも `uv run` を介さず `staqkit` と打てるようにする利便。CLI エントリポイントは `uv add` でも入るため、これは必須ではない。

ツールとランタイムは独立した二成果物ではなく、CLI エントリポイントと importable ランタイムを兼ねる一パッケージである。Python ランタイムへの依存は DVC 自体が Python 製であることからも避けられず、Python パッケージとする。

## 雛形と改善の伝播

配布の対象を性質の異なる二つに分ける。

- **staqkit 本体（ツール・ランタイムのコード）**: 通常の Python パッケージ。改善の取り込みは `uv lock --upgrade` でのバージョン更新で完了する。
- **プロジェクト雛形（各リポジトリにファイルとして焼かれる初期構成）**: CI 設定、pre-commit 設定、`.gitignore` / `.dvcignore`、stage.yaml のサンプル、空のディレクトリ枠など。pre-commit 設定はコミット時に、CI 設定は push / PR 時に、それぞれ `staqkit validate` を実行して dvc.yaml と stage.yaml の整合検査（[pipeline-gen.md](components/pipeline-gen.md#整合性の維持)）を掛ける。

パッケージのコードはバージョン更新で全プロジェクトに伝播する。生成時に各リポジトリへ焼かれた雛形ファイルは、以後そのリポジトリの一部となり版更新の影響を受けない。この非対称性に沿って、振る舞い（ロジック）は staqkit パッケージに置き、雛形は staqkit パッケージに置けない各プロジェクト固有のボイラープレートに限定する。

最小限の雛形の配布には Copier を用いる。Copier は生成時の回答とテンプレートのバージョンを記録し、`copier update` でテンプレート側の改善を既存プロジェクトにマージ適用できる。

## 初期化とステージ追加の責務分担

雛形伝播（Copier）とステージ scaffold（CLI）は別の軸である。

- **プロジェクト初期化**: `copier copy` でリポジトリ全体の初期構成（CI 設定、`.gitignore` / `.dvcignore`、空のディレクトリ枠、サンプル）を生成する。プロジェクトに一度きり、外側の構造を据える操作。
- **ステージ追加**: `staqkit add-stage` で既存プロジェクト内に新しいステージ（stage.yaml + run.py のボイラープレート）を生成する。何度でも行う、内側の要素を増やす操作。

ステージ scaffold は「振る舞い」であり、雛形に焼かず staqkit パッケージ内の CLI コマンドに置く。これによりバージョン更新だけで scaffold ロジックの改善が全プロジェクトに伝播する。プロジェクト初期化に「`staqkit init` 相当の専用コマンドを設けるか」という論点は、初期化を Copier に委ねることで解消する。

## 関連ドキュメント

- [architecture.md](architecture.md) — 層構造・設計方針
- [toolstack.md](toolstack.md) — ツールスタック（Copier を含む）
