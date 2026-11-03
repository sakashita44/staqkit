from collections.abc import Iterable, Sequence

import duckdb

from staqkit.schema import ForeignKey, TableSchema

# DuckDB の VIEW と Parquet は DDL の制約を強制しないため、制約は問い合わせで検査する。
_SAMPLE_LIMIT = 5


def quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def quote_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def column_list(columns: Iterable[str], alias: str | None = None) -> str:
    prefix = f"{alias}." if alias else ""
    return ", ".join(prefix + quote(c) for c in columns)


def read_parquet(paths: Sequence[str]) -> str:
    files = ", ".join(quote_literal(p) for p in paths)
    return f"read_parquet([{files}])"


def check_not_null(
    con: duckdb.DuckDBPyConnection, relation: str, schema: TableSchema
) -> list[str]:
    errors: list[str] = []
    for column in schema.columns:
        if column.nullable:
            continue
        row = con.execute(
            f"SELECT count(*) FROM {relation} WHERE {quote(column.name)} IS NULL"
        ).fetchone()
        if row is not None and row[0]:
            errors.append(f"列 {column.name!r} に NULL が {row[0]} 行ある")
    return errors


def find_duplicates(
    con: duckdb.DuckDBPyConnection, relation: str, columns: Sequence[str]
) -> list[tuple[object, ...]]:
    cols = column_list(columns)
    not_null = " AND ".join(f"{quote(c)} IS NOT NULL" for c in columns)
    return con.execute(
        f"SELECT {cols}, count(*) FROM {relation} WHERE {not_null} "
        f"GROUP BY {cols} HAVING count(*) > 1 ORDER BY {cols} LIMIT {_SAMPLE_LIMIT}"
    ).fetchall()


def check_keys(
    con: duckdb.DuckDBPyConnection, relation: str, schema: TableSchema
) -> list[str]:
    errors: list[str] = []
    for label, columns in [("主キー", schema.primary_key)] + [
        ("一意性制約", u) for u in schema.uniques
    ]:
        duplicates = find_duplicates(con, relation, columns)
        if duplicates:
            errors.append(f"{label} {list(columns)} が重複する: {duplicates}")
    return errors


def check_checks(
    con: duckdb.DuckDBPyConnection, relation: str, schema: TableSchema
) -> list[str]:
    errors: list[str] = []
    for expression in schema.checks:
        row = con.execute(
            f"SELECT count(*) FROM {relation} WHERE NOT ({expression})"
        ).fetchone()
        if row is not None and row[0]:
            errors.append(f"CHECK ({expression}) に違反する行が {row[0]} 行ある")
    return errors


def check_foreign_key(
    con: duckdb.DuckDBPyConnection, relation: str, fk: ForeignKey, target: str
) -> list[str]:
    not_null = " AND ".join(f"s.{quote(c)} IS NOT NULL" for c in fk.columns)
    match = " AND ".join(
        f"t.{quote(rc)} = s.{quote(c)}"
        for c, rc in zip(fk.columns, fk.ref_columns, strict=True)
    )
    missing = con.execute(
        f"SELECT DISTINCT {column_list(fk.columns, 's')} FROM {relation} AS s "
        f"WHERE {not_null} AND NOT EXISTS (SELECT 1 FROM {target} AS t WHERE {match}) "
        f"LIMIT {_SAMPLE_LIMIT}"
    ).fetchall()
    if not missing:
        return []
    return [
        f"外部キー {list(fk.columns)} の値が参照先 {fk.ref_table}"
        f"{list(fk.ref_columns)} に存在しない: {missing}"
    ]


def check_table(
    con: duckdb.DuckDBPyConnection,
    relation: str,
    schema: TableSchema,
    fk_targets: dict[str, str],
) -> list[str]:
    errors = check_not_null(con, relation, schema)
    errors += check_keys(con, relation, schema)
    errors += check_checks(con, relation, schema)
    for fk in schema.foreign_keys:
        target = fk_targets.get(fk.ref_table)
        if target is not None:
            errors += check_foreign_key(con, relation, fk, target)
    return errors


def relation_types(con: duckdb.DuckDBPyConnection, relation: str) -> dict[str, str]:
    rel = con.sql(f"SELECT * FROM {relation} LIMIT 0")
    return {name: str(t) for name, t in zip(rel.columns, rel.types, strict=True)}


def check_types(
    con: duckdb.DuckDBPyConnection, relation: str, schema: TableSchema
) -> list[str]:
    actual = relation_types(con, relation)
    expected = {c.name: c.data_type for c in schema.columns}
    if set(actual) != set(expected):
        return [
            f"列の構成が DDL と一致しない: 不足 {sorted(set(expected) - set(actual))}、"
            f"余分 {sorted(set(actual) - set(expected))}"
        ]
    return [
        f"列 {name!r} の型が {actual[name]} で、DDL の {expected[name]} と一致しない"
        for name in schema.column_names
        if actual[name] != expected[name]
    ]
