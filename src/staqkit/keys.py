import datetime
import re
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path

import duckdb

from staqkit.checks import check_table, column_list, quote, quote_literal
from staqkit.errors import ConfigError
from staqkit.paths import KEYS_DIR, discover, rel_posix
from staqkit.schema import Column, TableRole, TableSchema
from staqkit.yamlio import YamlValue, expect_list, expect_mapping, load_yaml

FILE_COLUMN = "__staqkit_file"

_INTEGER_TYPES = {
    "TINYINT",
    "SMALLINT",
    "INTEGER",
    "BIGINT",
    "HUGEINT",
    "UTINYINT",
    "USMALLINT",
    "UINTEGER",
    "UBIGINT",
    "UHUGEINT",
}
_FLOAT_TYPES = {"FLOAT", "DOUBLE"}
_DECIMAL = re.compile(r"DECIMAL\(\d+,\d+\)")


@dataclass(frozen=True)
class KeyFile:
    path: str
    table: str
    rows: tuple[dict[str, YamlValue], ...]


def raw_table(table: str) -> str:
    return quote(f"__staqkit_keys_{table}")


def load_key_files(root: Path, schemas: dict[str, TableSchema]) -> dict[str, KeyFile]:
    files: dict[str, KeyFile] = {}
    for file in discover(root, KEYS_DIR, "*.yaml"):
        where = rel_posix(file, root)
        files[where] = _read_key_file(file, where, schemas)
    return files


def _read_key_file(file: Path, where: str, schemas: dict[str, TableSchema]) -> KeyFile:
    data = expect_mapping(load_yaml(file), where, required={"table", "rows"})
    table = data["table"]
    schema = schemas.get(table) if isinstance(table, str) else None
    if schema is None or not isinstance(table, str):
        raise ConfigError(f"{where}: table {table!r} のテーブル定義がない")
    if schema.role is not TableRole.KEYS:
        raise ConfigError(
            f"{where}: テーブル {table!r} はキーを定義するテーブル（role: keys）でない"
        )
    columns = {c.name: c for c in schema.columns}
    rows: list[dict[str, YamlValue]] = []
    for i, item in enumerate(expect_list(data["rows"], f"{where}: rows")):
        row_where = f"{where}: rows[{i}]"
        row = expect_mapping(item, row_where)
        unknown = sorted(set(row) - set(columns))
        if unknown:
            raise ConfigError(f"{row_where}: テーブル {table!r} にない列 {unknown}")
        for name, value in row.items():
            _check_value_type(value, columns[name], f"{row_where}.{name}")
        rows.append(row)
    return KeyFile(where, table, tuple(rows))


def _check_value_type(value: YamlValue, column: Column, where: str) -> None:
    if value is None:
        return
    data_type = column.data_type
    if data_type == "VARCHAR":
        ok = isinstance(value, str)
    elif data_type == "BOOLEAN":
        ok = isinstance(value, bool)
    elif data_type in _INTEGER_TYPES:
        ok = isinstance(value, int) and not isinstance(value, bool)
    elif data_type in _FLOAT_TYPES or _DECIMAL.fullmatch(data_type):
        ok = isinstance(value, int | float) and not isinstance(value, bool)
    elif data_type == "DATE":
        ok = isinstance(value, datetime.date) and not isinstance(
            value, datetime.datetime
        )
    elif data_type == "TIMESTAMP":
        ok = isinstance(value, datetime.datetime)
    else:
        raise ConfigError(
            f"{where}: キーの宣言ファイルは {data_type} 型の列に対応しない"
        )
    if not ok:
        hint = "。文字列は引用符で囲むこと" if data_type == "VARCHAR" else ""
        raise ConfigError(
            f"{where}: 値 {value!r}（{type(value).__name__}）は {data_type} 型の列に"
            f"記述できない{hint}"
        )


def materialize(
    con: duckdb.DuckDBPyConnection,
    schemas: dict[str, TableSchema],
    key_files: dict[str, KeyFile],
) -> None:
    for schema in schemas.values():
        if schema.role is not TableRole.KEYS:
            continue
        if FILE_COLUMN in schema.column_names:
            raise ConfigError(f"{schema.path}: 列名 {FILE_COLUMN!r} は使用できない")
        definitions = [f"{quote(FILE_COLUMN)} VARCHAR"]
        for c in schema.columns:
            default = f" DEFAULT {c.default}" if c.default is not None else ""
            definitions.append(f"{quote(c.name)} {c.data_type}{default}")
        con.execute(f"CREATE TABLE {raw_table(schema.name)} ({', '.join(definitions)})")
    for key_file in key_files.values():
        for row in key_file.rows:
            names = [FILE_COLUMN, *row]
            placeholders = ", ".join("?" for _ in names)
            con.execute(
                f"INSERT INTO {raw_table(key_file.table)} ({column_list(names)}) "
                f"VALUES ({placeholders})",
                [key_file.path, *row.values()],
            )


def create_views(
    con: duckdb.DuckDBPyConnection,
    schemas: dict[str, TableSchema],
    tables: Collection[str],
    files: Collection[str] | None,
    prefix: str = "",
) -> dict[str, str]:
    views: dict[str, str] = {}
    for table in sorted(tables):
        schema = schemas[table]
        name = quote(prefix + table)
        where = ""
        if files is not None:
            listed = ", ".join(quote_literal(f) for f in sorted(files))
            where = f" WHERE list_contains([{listed}]::VARCHAR[], {quote(FILE_COLUMN)})"
        con.execute(
            f"CREATE VIEW {name} AS SELECT {column_list(schema.column_names)} "
            f"FROM {raw_table(table)}{where}"
        )
        views[table] = name
    return views


def validate_keys(
    schemas: dict[str, TableSchema], key_files: dict[str, KeyFile]
) -> None:
    con = duckdb.connect()
    try:
        materialize(con, schemas, key_files)
        key_tables = [s.name for s in schemas.values() if s.role is TableRole.KEYS]
        views = create_views(con, schemas, key_tables, None, prefix="__all_")
        for table in key_tables:
            schema = schemas[table]
            for fk in schema.foreign_keys:
                if schemas[fk.ref_table].role is not TableRole.KEYS:
                    raise ConfigError(
                        f"{schema.path}: キーを定義するテーブルは、データを格納する"
                        f"テーブル {fk.ref_table!r} を参照できない"
                    )
            errors = check_table(con, views[table], schema, views)
            if errors:
                raise ConfigError(
                    f"キーを定義するテーブル {table!r} の宣言ファイルが制約に違反する: "
                    + "; ".join(errors)
                )
    finally:
        con.close()


def resolve_used_files(
    con: duckdb.DuckDBPyConnection,
    schemas: dict[str, TableSchema],
    start: Collection[str],
) -> set[str]:
    used = set(start)
    key_tables = [s for s in schemas.values() if s.role is TableRole.KEYS]
    while True:
        found: set[str] = set()
        for schema in key_tables:
            for fk in schema.foreign_keys:
                match = " AND ".join(
                    f"t.{quote(rc)} = s.{quote(c)}"
                    for c, rc in zip(fk.columns, fk.ref_columns, strict=True)
                )
                rows = con.execute(
                    f"SELECT DISTINCT t.{quote(FILE_COLUMN)} "
                    f"FROM {raw_table(fk.ref_table)} AS t "
                    f"JOIN {raw_table(schema.name)} AS s ON {match} "
                    f"WHERE list_contains(?::VARCHAR[], s.{quote(FILE_COLUMN)})",
                    [sorted(used)],
                ).fetchall()
                found.update(str(r[0]) for r in rows)
        if found <= used:
            return used
        used |= found
