import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import duckdb

from staqkit.checks import find_duplicates, read_parquet
from staqkit.errors import ValidationError
from staqkit.paths import DVC_LOCK, DVC_YAML
from staqkit.pipeline import generate
from staqkit.project import Project
from staqkit.yamlio import YamlValue, load_yaml


def check_project(root: Path) -> None:
    project = Project.load(root)
    _check_dvc_yaml(project)
    _check_dvc_status(root)
    _check_lock(root)
    _check_primary_keys(project)


def _check_dvc_yaml(project: Project) -> None:
    path = project.root / DVC_YAML
    if not path.is_file():
        raise ValidationError(f"{DVC_YAML} がない。staqkit generate で生成すること")
    current = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    if current != generate(project):
        raise ValidationError(
            f"{DVC_YAML} が宣言から生成した内容と一致しない。"
            "staqkit generate で再生成すること"
        )


# dvc status は変更がある場合も終了コード 0 を返すため、--json の出力で判定する。
def _check_dvc_status(root: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "dvc", "status", "--json"],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode != 0:
        raise ValidationError(
            f"dvc status が終了コード {result.returncode} で失敗した: "
            f"{result.stderr.strip()}"
        )
    try:
        status: object = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise ValidationError(
            f"dvc status の出力を解析できない: {result.stdout!r}"
        ) from e
    if status:
        raise ValidationError(
            "DVC の状態が最新でない。dvc repro で再実行すること: "
            + json.dumps(status, ensure_ascii=False)
        )


def _posix(path: str) -> str:
    return path.replace("\\", "/")


def _pipeline_dependencies(stage: YamlValue) -> tuple[set[str], set[str]]:
    deps: set[str] = set()
    params: set[str] = set()
    if not isinstance(stage, dict):
        return deps, params
    raw_deps = stage.get("deps")
    for dep in raw_deps if isinstance(raw_deps, list) else []:
        if isinstance(dep, str):
            deps.add(_posix(dep))
    raw_params = stage.get("params")
    for entry in raw_params if isinstance(raw_params, list) else []:
        if isinstance(entry, dict):
            for file, keys in entry.items():
                if isinstance(keys, list):
                    params.update(f"{_posix(file)}:{k}" for k in keys)
    return deps, params


def _lock_dependencies(stage: YamlValue) -> tuple[set[str], set[str]]:
    deps: set[str] = set()
    params: set[str] = set()
    if not isinstance(stage, dict):
        return deps, params
    raw_deps = stage.get("deps")
    for dep in raw_deps if isinstance(raw_deps, list) else []:
        if isinstance(dep, dict) and isinstance(dep.get("path"), str):
            deps.add(_posix(str(dep["path"])))
    raw_params = stage.get("params")
    if isinstance(raw_params, dict):
        for file, values in raw_params.items():
            if isinstance(values, dict):
                params.update(f"{_posix(file)}:{k}" for k in values)
    return deps, params


# DVC は dvc.yaml から deps や params を削除しても検知せず、dvc.lock に古い依存が残る。
def _check_lock(root: Path) -> None:
    pipeline = load_yaml(root / DVC_YAML)
    lock_path = root / DVC_LOCK
    lock = load_yaml(lock_path) if lock_path.is_file() else {}
    pipeline_stages = pipeline.get("stages") if isinstance(pipeline, dict) else None
    lock_stages = lock.get("stages") if isinstance(lock, dict) else None
    if not isinstance(pipeline_stages, dict):
        return
    locked = lock_stages if isinstance(lock_stages, dict) else {}
    for name, stage in pipeline_stages.items():
        if _pipeline_dependencies(stage) != _lock_dependencies(locked.get(name)):
            raise ValidationError(
                f"stage {name!r} の {DVC_LOCK} の依存が {DVC_YAML} と一致しない。"
                f"dvc repro --force {name} で再実行すること"
            )


# 互いに依存しない stage の間の主キー重複は、DVC の状態にも stage の実行時の検証にも現れない。
# run cache から復元された出力は実行時の検証も経ないため、実ファイルを直接読んで検査する。
def _check_primary_keys(project: Project) -> None:
    artifacts: dict[str, list[str]] = defaultdict(list)
    for stage in project.stages.values():
        for key, out in stage.outs.items():
            if out.table is not None:
                artifacts[out.table].append(stage.out_path(key))
    con = duckdb.connect()
    try:
        for table, paths in sorted(artifacts.items()):
            if len(paths) < 2:
                continue
            missing = [p for p in paths if not (project.root / p).is_file()]
            if missing:
                raise ValidationError(
                    f"テーブル {table!r} の主キーを検査できない。実体ファイルがない: {missing}"
                )
            schema = project.schemas[table]
            relation = read_parquet(
                [(project.root / p).as_posix() for p in sorted(paths)]
            )
            duplicates = find_duplicates(con, relation, schema.primary_key)
            if duplicates:
                raise ValidationError(
                    f"テーブル {table!r} の主キー {list(schema.primary_key)} が"
                    f" artifact の間で重複する: {duplicates}"
                )
    finally:
        con.close()
