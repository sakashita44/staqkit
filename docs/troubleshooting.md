# トラブルシューティング

staqkit を用いた解析で起きやすい問題について、症状ごとの原因と対処を記す。宣言ファイルや API の仕様は [リファレンス](reference.md) を参照のこと。

## 宣言を変更したのに dvc repro で反映されない

`dvc.yaml` は `staqkit generate` を実行したときにのみ生成される。`outs` や `path_deps` を変更した後に `staqkit generate` を実行しないと、`dvc repro` は古い `dvc.yaml` に従って実行され、変更は検知されない。

宣言を編集した後は `staqkit generate` を実行すること。再生成の漏れは、`staqkit check` で `dvc.yaml` が宣言と一致しないエラーとして検出される。

## query が期待した行を返さない

`DataStore.query` は、stage から見えるキーを参照する行だけを返す。`inputs.keys` を指定した stage では、指定したキーの宣言ファイルにない値のキーを参照する行は返されない。参照先のテーブルのキーの宣言ファイルを 1 つも指定しなかった場合、そのテーブルのキーを参照する行は 1 件も返されない。

読み取る必要のあるキーを含むキーの宣言ファイルを、`inputs.keys` に追加すること。すべてのキーを読み取る場合は、`inputs.keys` を省略すること。

## 依存パッケージを更新すると下流の stage まで再実行される

`write_table` が書き出す Parquet ファイルには、書き出した DuckDB のバージョンが記録される。DuckDB を更新した後に stage を再実行すると、データが同一でも出力のハッシュが変わるため、DVC は下流の stage まで再実行する。

再実行を避ける方法はない。DuckDB の更新は、パイプライン全体の再実行を許容できる時点で行うこと。

## Windows で dvc repro が run cache の保存に失敗する

`LongPathsEnabled` が無効な Windows では、プロジェクトのルートの絶対パスがおよそ 80 文字を超えると、`dvc repro` が run cache の保存に失敗する。

プロジェクトのルートを短いパスに配置するか、Windows の `LongPathsEnabled` を有効にすること。
