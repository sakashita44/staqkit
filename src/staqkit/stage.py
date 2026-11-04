from dataclasses import dataclass
from pathlib import Path

from staqkit.errors import ConfigError
from staqkit.paths import (
    DATA_STAGES_DIR,
    STAGES_DIR,
    check_rel_path,
    check_stage_name,
    discover,
    rel_posix,
)
from staqkit.yamlio import (
    YamlValue,
    expect_list,
    expect_mapping,
    expect_str,
    load_yaml,
)


@dataclass(frozen=True)
class ArtifactRef:
    stage: str
    out: str


@dataclass(frozen=True)
class ParamBinding:
    file: str
    key: str


@dataclass(frozen=True)
class OutDecl:
    path: str
    table: str | None


@dataclass(frozen=True)
class StageDecl:
    name: str
    yaml_path: str
    input_tables: tuple[ArtifactRef, ...]
    input_files: dict[str, ArtifactRef]
    input_keys: tuple[str, ...] | None
    path_deps: tuple[str, ...]
    params: dict[str, ParamBinding]
    outs: dict[str, OutDecl]

    @property
    def run_path(self) -> str:
        return f"{STAGES_DIR}/{self.name}/run.py"

    def out_path(self, key: str) -> str:
        return f"{DATA_STAGES_DIR}/{self.name}/{self.outs[key].path}"


def load_stages(root: Path) -> dict[str, StageDecl]:
    stages: dict[str, StageDecl] = {}
    for file in discover(root, STAGES_DIR, "stage.yaml"):
        where = rel_posix(file, root)
        name = rel_posix(file.parent, root / STAGES_DIR)
        check_stage_name(name, where)
        stages[name] = _read_stage(name, where, load_yaml(file))
    return stages


def _read_stage(name: str, where: str, raw: YamlValue) -> StageDecl:
    # inputs と params は DVC の params 依存の対象になる。DVC は対象のキーがないと実行に失敗し、
    # キーの削除を検知しないため、空の場合も記述を必須とする。
    data = expect_mapping(
        raw, where, required={"inputs", "params"}, optional={"path_deps", "outs"}
    )
    inputs = expect_mapping(
        data["inputs"], f"{where}: inputs", optional={"tables", "files", "keys"}
    )
    input_tables = tuple(
        _artifact_ref(item, f"{where}: inputs.tables[{i}]")
        for i, item in enumerate(
            expect_list(inputs.get("tables", []), f"{where}: inputs.tables")
        )
    )
    input_files = {
        local: _artifact_ref(item, f"{where}: inputs.files.{local}")
        for local, item in expect_mapping(
            inputs.get("files", {}), f"{where}: inputs.files"
        ).items()
    }
    input_keys: tuple[str, ...] | None = None
    if "keys" in inputs:
        input_keys = tuple(
            check_rel_path(
                expect_str(item, f"{where}: inputs.keys[{i}]"),
                f"{where}: inputs.keys[{i}]",
            )
            for i, item in enumerate(
                expect_list(inputs["keys"], f"{where}: inputs.keys")
            )
        )
    path_deps = tuple(
        check_rel_path(
            expect_str(item, f"{where}: path_deps[{i}]"), f"{where}: path_deps[{i}]"
        )
        for i, item in enumerate(
            expect_list(data.get("path_deps", []), f"{where}: path_deps")
        )
    )
    params = {
        local: _param_binding(item, f"{where}: params.{local}")
        for local, item in expect_mapping(data["params"], f"{where}: params").items()
    }
    outs = {
        key: _out_decl(item, f"{where}: outs.{key}")
        for key, item in expect_mapping(data.get("outs", {}), f"{where}: outs").items()
    }
    return StageDecl(
        name=name,
        yaml_path=where,
        input_tables=input_tables,
        input_files=input_files,
        input_keys=input_keys,
        path_deps=path_deps,
        params=params,
        outs=outs,
    )


def _artifact_ref(raw: YamlValue, where: str) -> ArtifactRef:
    data = expect_mapping(raw, where, required={"stage", "out"})
    return ArtifactRef(
        stage=expect_str(data["stage"], f"{where}.stage"),
        out=expect_str(data["out"], f"{where}.out"),
    )


def _param_binding(raw: YamlValue, where: str) -> ParamBinding:
    data = expect_mapping(raw, where, required={"file", "key"})
    return ParamBinding(
        file=check_rel_path(expect_str(data["file"], f"{where}.file"), f"{where}.file"),
        key=expect_str(data["key"], f"{where}.key"),
    )


def _out_decl(raw: YamlValue, where: str) -> OutDecl:
    data = expect_mapping(raw, where, required={"path"}, optional={"table"})
    path = check_rel_path(expect_str(data["path"], f"{where}.path"), f"{where}.path")
    table = None
    if "table" in data:
        table = expect_str(data["table"], f"{where}.table")
        if not path.endswith(".parquet"):
            raise ConfigError(
                f"{where}: table を指定した出力の path は .parquet でなければならない"
            )
    return OutDecl(path=path, table=table)
