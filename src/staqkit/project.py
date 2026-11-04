from dataclasses import dataclass
from pathlib import Path

import duckdb

from staqkit.errors import ConfigError
from staqkit.keys import (
    KeyFile,
    load_key_files,
    materialize,
    resolve_used_files,
    validate_keys,
)
from staqkit.paths import KEYS_DIR
from staqkit.schema import TableRole, TableSchema, load_table_schemas
from staqkit.stage import ArtifactRef, OutDecl, StageDecl, load_stages


@dataclass(frozen=True)
class InputArtifact:
    ref: ArtifactRef
    path: str
    table: str


@dataclass(frozen=True)
class StagePlan:
    decl: StageDecl
    input_artifacts: tuple[InputArtifact, ...]
    input_files: dict[str, str]
    key_files: tuple[str, ...]
    key_tables: tuple[str, ...]
    data_tables: tuple[str, ...]

    @property
    def input_tables(self) -> tuple[str, ...]:
        return tuple(sorted({a.table for a in self.input_artifacts}))

    @property
    def output_tables(self) -> tuple[str, ...]:
        return tuple(sorted({o.table for o in self.decl.outs.values() if o.table}))


@dataclass(frozen=True)
class Project:
    root: Path
    schemas: dict[str, TableSchema]
    key_files: dict[str, KeyFile]
    stages: dict[str, StageDecl]
    plans: dict[str, StagePlan]

    @classmethod
    def load(cls, root: Path) -> "Project":
        schemas = load_table_schemas(root)
        key_files = load_key_files(root, schemas)
        validate_keys(schemas, key_files)
        stages = load_stages(root)
        _check_out_paths(stages)
        con = duckdb.connect()
        try:
            materialize(con, schemas, key_files)
            plans = {
                name: _plan(stage, stages, schemas, key_files, con)
                for name, stage in stages.items()
            }
        finally:
            con.close()
        return cls(root, schemas, key_files, stages, plans)


def _check_out_paths(stages: dict[str, StageDecl]) -> None:
    # 大文字と小文字を区別しないファイルシステム（Windows など）でも衝突しないよう、比較の前に正規化する。
    owners: list[tuple[str, str]] = sorted(
        (stage.out_path(key).casefold() + "/", f"{stage.yaml_path}: outs.{key}")
        for stage in stages.values()
        for key in stage.outs
    )
    for (path, where), (next_path, next_where) in zip(owners, owners[1:], strict=False):
        if next_path.startswith(path):
            raise ConfigError(f"{where} と {next_where} の出力パスが重なる")


def _plan(
    stage: StageDecl,
    stages: dict[str, StageDecl],
    schemas: dict[str, TableSchema],
    key_files: dict[str, KeyFile],
    con: duckdb.DuckDBPyConnection,
) -> StagePlan:
    where = stage.yaml_path
    input_artifacts: list[InputArtifact] = []
    for ref in stage.input_tables:
        out = _resolve_ref(ref, stage, stages, f"{where}: inputs.tables")
        if out.table is None:
            raise ConfigError(
                f"{where}: inputs.tables の {ref.stage}/{ref.out} はテーブル出力でない"
            )
        input_artifacts.append(
            InputArtifact(ref, stages[ref.stage].out_path(ref.out), out.table)
        )
    input_files: dict[str, str] = {}
    for local, ref in stage.input_files.items():
        _resolve_ref(ref, stage, stages, f"{where}: inputs.files.{local}")
        input_files[local] = stages[ref.stage].out_path(ref.out)
    for key, out in stage.outs.items():
        if out.table is None:
            continue
        schema = schemas.get(out.table)
        if schema is None:
            raise ConfigError(
                f"{where}: outs.{key}: テーブル {out.table!r} の定義がない"
            )
        if schema.role is not TableRole.DATA:
            raise ConfigError(
                f"{where}: outs.{key}: キーを定義するテーブル {out.table!r} は出力できない"
            )
    data_tables = sorted(
        {a.table for a in input_artifacts}
        | {o.table for o in stage.outs.values() if o.table}
    )
    _check_data_references(stage, schemas, data_tables)
    direct_key_tables = {
        fk.ref_table
        for table in data_tables
        for fk in schemas[table].foreign_keys
        if schemas[fk.ref_table].role is TableRole.KEYS
    }
    if stage.input_keys is None:
        start = {p for p, f in key_files.items() if f.table in direct_key_tables}
    else:
        for path in stage.input_keys:
            if not path.startswith(KEYS_DIR + "/") or path not in key_files:
                raise ConfigError(
                    f"{where}: inputs.keys の {path} は {KEYS_DIR}/ 配下の"
                    "キーの宣言ファイルでない"
                )
        start = set(stage.input_keys)
    used = resolve_used_files(con, schemas, start)
    key_tables = _key_table_closure(
        schemas, direct_key_tables | {key_files[p].table for p in used}
    )
    return StagePlan(
        decl=stage,
        input_artifacts=tuple(input_artifacts),
        input_files=input_files,
        key_files=tuple(sorted(used)),
        key_tables=tuple(sorted(key_tables)),
        data_tables=tuple(data_tables),
    )


def _resolve_ref(
    ref: ArtifactRef, stage: StageDecl, stages: dict[str, StageDecl], where: str
) -> OutDecl:
    if ref.stage == stage.name:
        raise ConfigError(f"{where}: 自身の出力 {ref.stage}/{ref.out} は入力にできない")
    producer = stages.get(ref.stage)
    if producer is None:
        raise ConfigError(f"{where}: stage {ref.stage!r} がない")
    out = producer.outs.get(ref.out)
    if out is None:
        raise ConfigError(
            f"{where}: stage {ref.stage!r} に出力 {ref.out!r} がない"
            f"（宣言されている出力: {sorted(producer.outs)}）"
        )
    return out


def _check_data_references(
    stage: StageDecl, schemas: dict[str, TableSchema], data_tables: list[str]
) -> None:
    for table in data_tables:
        for fk in schemas[table].foreign_keys:
            target = schemas[fk.ref_table]
            if target.role is TableRole.DATA and fk.ref_table not in data_tables:
                raise ConfigError(
                    f"{stage.yaml_path}: テーブル {table!r} の外部キーが参照する "
                    f"{fk.ref_table!r} を出力する artifact を inputs.tables に宣言すること"
                )


def _key_table_closure(schemas: dict[str, TableSchema], tables: set[str]) -> set[str]:
    result = set(tables)
    pending = list(tables)
    while pending:
        for fk in schemas[pending.pop()].foreign_keys:
            if fk.ref_table not in result:
                result.add(fk.ref_table)
                pending.append(fk.ref_table)
    return result
