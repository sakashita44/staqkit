from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import cast

import duckdb

from staqkit.errors import ConfigError
from staqkit.paths import TABLE_SCHEMAS_DIR, discover, rel_posix
from staqkit.yamlio import expect_mapping, expect_str, load_yaml


class TableRole(StrEnum):
    DATA = "data"
    KEYS = "keys"


@dataclass(frozen=True)
class Column:
    name: str
    data_type: str
    nullable: bool
    default: str | None


@dataclass(frozen=True)
class ForeignKey:
    columns: tuple[str, ...]
    ref_table: str
    ref_columns: tuple[str, ...]


@dataclass(frozen=True)
class TableSchema:
    name: str
    path: str
    role: TableRole
    ddl: str
    columns: tuple[Column, ...]
    primary_key: tuple[str, ...]
    uniques: tuple[tuple[str, ...], ...]
    foreign_keys: tuple[ForeignKey, ...]
    checks: tuple[str, ...]

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.columns)


_ALLOWED_KEYS = {"ddl", "description", "column_descriptions", "catalog", "role"}


@dataclass(frozen=True)
class _RawSchema:
    name: str
    path: str
    role: TableRole
    ddl: str


def load_table_schemas(root: Path) -> dict[str, TableSchema]:
    raws: dict[str, _RawSchema] = {}
    folded: dict[str, str] = {}
    for file in discover(root, TABLE_SCHEMAS_DIR, "*.yaml"):
        raw = _read_schema_file(file, root)
        other = folded.get(raw.name.casefold())
        if other is not None:
            raise ConfigError(
                f"{raw.path}: テーブル名 {raw.name!r} が {raws[other].path} と重複する"
            )
        folded[raw.name.casefold()] = raw.name
        raws[raw.name] = raw
    return _interpret_ddl(raws)


def _read_schema_file(file: Path, root: Path) -> _RawSchema:
    where = rel_posix(file, root)
    data = expect_mapping(
        load_yaml(file), where, required={"ddl"}, optional=_ALLOWED_KEYS - {"ddl"}
    )
    ddl = expect_str(data["ddl"], f"{where}: ddl")
    if "description" in data and not isinstance(data["description"], str):
        raise ConfigError(f"{where}: description は文字列でなければならない")
    if "column_descriptions" in data:
        descriptions = expect_mapping(
            data["column_descriptions"], f"{where}: column_descriptions"
        )
        if not all(isinstance(v, str) for v in descriptions.values()):
            raise ConfigError(f"{where}: column_descriptions の値は文字列とすること")
    if "catalog" in data and not isinstance(data["catalog"], bool):
        raise ConfigError(f"{where}: catalog は真偽値でなければならない")
    role_value = data.get("role", TableRole.DATA.value)
    if role_value not in {r.value for r in TableRole}:
        raise ConfigError(
            f"{where}: role は {[r.value for r in TableRole]} のいずれかとすること"
        )
    return _RawSchema(file.stem, where, TableRole(role_value), ddl)


def _interpret_ddl(raws: dict[str, _RawSchema]) -> dict[str, TableSchema]:
    con = duckdb.connect()
    try:
        for raw in raws.values():
            statements = con.extract_statements(raw.ddl)
            if len(statements) != 1 or statements[0].type.name != "CREATE":
                raise ConfigError(
                    f"{raw.path}: ddl は CREATE TABLE の 1 文でなければならない"
                )
        # DuckDB は外部キーの参照先テーブルが存在しないと CREATE TABLE を CatalogException で拒否する。
        # 参照先が作成されるまで、その DDL の実行を後回しにする。
        pending = list(raws.values())
        while pending:
            postponed: list[tuple[_RawSchema, duckdb.CatalogException]] = []
            for raw in pending:
                before = _table_names(con)
                try:
                    con.execute(raw.ddl)
                except duckdb.CatalogException as e:
                    postponed.append((raw, e))
                    continue
                except duckdb.Error as e:
                    raise ConfigError(f"{raw.path}: ddl を実行できない: {e}") from e
                created = _table_names(con) - before
                if created != {raw.name}:
                    raise ConfigError(
                        f"{raw.path}: ddl はテーブル {raw.name!r}（ファイル名）を"
                        f"作成しなければならない（作成されたもの: {sorted(created)}）"
                    )
            if len(postponed) == len(pending):
                details = "; ".join(f"{r.path}: {e}" for r, e in postponed)
                raise ConfigError(
                    f"外部キーの参照先が未定義か、循環参照がある: {details}"
                )
            pending = [r for r, _ in postponed]
        return {name: _read_catalog(con, raw) for name, raw in raws.items()}
    finally:
        con.close()


def _table_names(con: duckdb.DuckDBPyConnection) -> set[str]:
    rows = con.execute("SELECT table_name FROM duckdb_tables()").fetchall()
    return {cast(str, r[0]) for r in rows}


def _read_catalog(con: duckdb.DuckDBPyConnection, raw: _RawSchema) -> TableSchema:
    column_rows = con.execute(
        "SELECT column_name, data_type, is_nullable, column_default "
        "FROM duckdb_columns() WHERE table_name = ? ORDER BY column_index",
        [raw.name],
    ).fetchall()
    columns = tuple(
        Column(
            name=cast(str, r[0]),
            data_type=cast(str, r[1]),
            nullable=cast(bool, r[2]),
            default=cast(str | None, r[3]),
        )
        for r in column_rows
    )
    constraint_rows = con.execute(
        "SELECT constraint_type, constraint_column_names, expression, "
        "referenced_table, referenced_column_names "
        "FROM duckdb_constraints() WHERE table_name = ? ORDER BY constraint_index",
        [raw.name],
    ).fetchall()
    primary_key: tuple[str, ...] = ()
    uniques: list[tuple[str, ...]] = []
    foreign_keys: list[ForeignKey] = []
    checks: list[str] = []
    for r in constraint_rows:
        kind = cast(str, r[0])
        cols = tuple(cast(list[str], r[1]))
        if kind == "PRIMARY KEY":
            primary_key = cols
        elif kind == "UNIQUE":
            uniques.append(cols)
        elif kind == "FOREIGN KEY":
            foreign_keys.append(
                ForeignKey(cols, cast(str, r[3]), tuple(cast(list[str], r[4])))
            )
        elif kind == "CHECK":
            checks.append(cast(str, r[2]))
    if not primary_key:
        raise ConfigError(f"{raw.path}: テーブル {raw.name!r} に主キーがない")
    return TableSchema(
        name=raw.name,
        path=raw.path,
        role=raw.role,
        ddl=raw.ddl,
        columns=columns,
        primary_key=primary_key,
        uniques=tuple(uniques),
        foreign_keys=tuple(foreign_keys),
        checks=tuple(checks),
    )
