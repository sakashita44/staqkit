import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

import duckdb
import polars as pl

from staqkit.checks import (
    check_foreign_key,
    check_table,
    check_types,
    column_list,
    find_duplicates,
    quote,
    quote_literal,
    read_parquet,
)
from staqkit.errors import AccessError, ConfigError, StaqkitError, ValidationError
from staqkit.keys import create_views, materialize
from staqkit.paths import DVC_YAML, STAGES_DIR, find_root, rel_posix
from staqkit.pipeline import stage_entry
from staqkit.project import Project, StagePlan
from staqkit.schema import TableRole, TableSchema
from staqkit.yamlio import YamlValue, load_yaml

type FilterValue = str | int | float | bool | None
type Filters = Mapping[str, FilterValue | list[FilterValue] | tuple[FilterValue, ...]]


@dataclass(frozen=True)
class StageInfo:
    name: str
    root: Path
    params: dict[str, YamlValue]
    _plan: StagePlan

    def input_path(self, key: str) -> Path:
        path = self._plan.input_files.get(key)
        if path is None:
            raise AccessError(
                f"{self._plan.decl.yaml_path}: inputs.files に {key!r} がない"
                f"（宣言されている入力: {sorted(self._plan.input_files)}）"
            )
        return self.root / path

    def output_path(self, key: str) -> Path:
        decl = self._plan.decl
        candidates = sorted(k for k, o in decl.outs.items() if o.table is None)
        if key not in candidates:
            raise AccessError(
                f"{decl.yaml_path}: outs に非テーブル出力 {key!r} がない"
                f"（非テーブル出力: {candidates}）。テーブル出力は write_table で書き出すこと"
            )
        path = self.root / decl.out_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path


class DataStore:
    def __init__(self, project: Project, plan: StagePlan) -> None:
        self._project = project
        self._plan = plan
        self._written: set[str] = set()
        self._con = duckdb.connect()
        materialize(self._con, project.schemas, project.key_files)
        self._key_views = create_views(
            self._con, project.schemas, plan.key_tables, plan.key_files
        )
        self._data_views: dict[str, str] = {}
        for table in plan.input_tables:
            self._data_views[table] = self._register_inputs(table)

    def close(self) -> None:
        self._con.close()

    def _schema(self, table: str) -> TableSchema:
        return self._project.schemas[table]

    def _input_paths(self, table: str) -> list[str]:
        return [
            (self._project.root / a.path).as_posix()
            for a in self._plan.input_artifacts
            if a.table == table
        ]

    def _register_inputs(self, table: str) -> str:
        schema = self._schema(table)
        view = quote(table)
        self._con.execute(
            f"CREATE VIEW {view} AS SELECT {column_list(schema.column_names)} "
            f"FROM {read_parquet(self._input_paths(table))}"
        )
        errors = check_types(self._con, view, schema)
        duplicates = find_duplicates(self._con, view, schema.primary_key)
        if duplicates:
            errors.append(
                f"入力 artifact を統合すると主キー {list(schema.primary_key)} が"
                f"重複する: {duplicates}"
            )
        if errors:
            raise ValidationError(f"入力テーブル {table!r}: " + "; ".join(errors))
        return view

    def query(self, table: str, filters: Filters | None = None) -> pl.DataFrame:
        view = self._data_views.get(table) or self._key_views.get(table)
        if view is None:
            raise AccessError(
                f"テーブル {table!r} は {self._plan.decl.yaml_path} の入力にない"
                f"（参照できるテーブル: {sorted(self._data_views | self._key_views)}）"
            )
        schema = self._schema(table)
        conditions: list[str] = []
        params: list[object] = []
        for column, value in (filters or {}).items():
            if column not in schema.column_names:
                raise AccessError(f"テーブル {table!r} に列 {column!r} がない")
            values = list(value) if isinstance(value, list | tuple) else [value]
            self._check_visible(schema, column, values)
            if not isinstance(value, list | tuple):
                if value is None:
                    conditions.append(f"{quote(column)} IS NULL")
                else:
                    conditions.append(f"{quote(column)} = ?")
                    params.append(value)
            elif values:
                conditions.append(
                    f"{quote(column)} IN ({', '.join('?' for _ in values)})"
                )
                params.extend(values)
            else:
                conditions.append("FALSE")
        if schema.role is TableRole.DATA:
            conditions += self._visibility_conditions(schema)
        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        return self._con.execute(f"SELECT * FROM {view} AS s{where}", params).pl()

    def _visible_key_fks(self, schema: TableSchema):
        return [
            fk
            for fk in schema.foreign_keys
            if self._schema(fk.ref_table).role is TableRole.KEYS
        ]

    def _visibility_conditions(self, schema: TableSchema) -> list[str]:
        conditions: list[str] = []
        for fk in self._visible_key_fks(schema):
            any_null = " OR ".join(f"s.{quote(c)} IS NULL" for c in fk.columns)
            match = " AND ".join(
                f"k.{quote(rc)} = s.{quote(c)}"
                for c, rc in zip(fk.columns, fk.ref_columns, strict=True)
            )
            target = self._key_views[fk.ref_table]
            conditions.append(
                f"({any_null} OR EXISTS (SELECT 1 FROM {target} AS k WHERE {match}))"
            )
        return conditions

    def _check_visible(
        self, schema: TableSchema, column: str, values: list[FilterValue]
    ) -> None:
        if schema.role is not TableRole.DATA:
            return
        for fk in self._visible_key_fks(schema):
            if fk.columns != (column,):
                continue
            target = self._key_views[fk.ref_table]
            ref = quote(fk.ref_columns[0])
            for value in values:
                if value is None:
                    continue
                row = self._con.execute(
                    f"SELECT count(*) FROM {target} WHERE {ref} = ?", [value]
                ).fetchone()
                if row is None or not row[0]:
                    raise AccessError(
                        f"列 {column!r} の絞り込み値 {value!r} は、"
                        f"{self._plan.decl.yaml_path} から見えるキーでない"
                    )

    def write_table(self, key: str, df: pl.DataFrame) -> None:
        decl = self._plan.decl
        candidates = sorted(k for k, o in decl.outs.items() if o.table is not None)
        if key not in candidates:
            raise AccessError(
                f"{decl.yaml_path}: outs にテーブル出力 {key!r} がない"
                f"（テーブル出力: {candidates}）"
            )
        if key in self._written:
            raise AccessError(f"{decl.yaml_path}: outs.{key} は既に書き出されている")
        table = decl.outs[key].table
        assert table is not None
        schema = self._schema(table)
        staged = quote(f"__staqkit_write_{key}")
        self._con.register(f"__staqkit_df_{key}", df)
        try:
            errors = check_types(self._con, quote(f"__staqkit_df_{key}"), schema)
            if errors:
                raise ValidationError(
                    f"{decl.yaml_path}: outs.{key}: " + "; ".join(errors)
                )
            self._con.execute(
                f"CREATE TEMP VIEW {staged} AS SELECT "
                f"{column_list(schema.column_names)} FROM {quote(f'__staqkit_df_{key}')}"
            )
            key_targets = {
                fk.ref_table: self._key_views[fk.ref_table]
                for fk in self._visible_key_fks(schema)
            }
            errors = check_table(self._con, staged, schema, key_targets)
            if errors:
                raise ValidationError(
                    f"{decl.yaml_path}: outs.{key}: " + "; ".join(errors)
                )
            path = self._project.root / decl.out_path(key)
            path.parent.mkdir(parents=True, exist_ok=True)
            # 同じ値の出力をバイト単位で一致させ、DVC が下流を再実行しないよう、主キーの順に並べて書き出す。
            self._con.execute(
                f"COPY (SELECT * FROM {staged} ORDER BY "
                f"{column_list(schema.primary_key)}) "
                f"TO {quote_literal(path.as_posix())} (FORMAT parquet)"
            )
            self._written.add(key)
        finally:
            self._con.unregister(f"__staqkit_df_{key}")

    def epilogue(self) -> None:
        decl = self._plan.decl
        table_outs = {k: o.table for k, o in decl.outs.items() if o.table is not None}
        missing = sorted(set(table_outs) - self._written)
        if missing:
            raise ValidationError(
                f"{decl.yaml_path}: テーブル出力 {missing} が write_table で書き出されていない"
            )
        # stage の成否が DVC の依存グラフ外のファイルに左右されないよう、
        # 検証の範囲を宣言した入力と今回の出力に限る。
        root = self._project.root
        scope: dict[str, str] = dict(self._key_views)
        for table in self._plan.data_tables:
            paths = self._input_paths(table) + [
                (root / decl.out_path(k)).as_posix()
                for k, t in table_outs.items()
                if t == table
            ]
            view = quote(f"__staqkit_scope_{table}")
            self._con.execute(
                f"CREATE TEMP VIEW {view} AS SELECT "
                f"{column_list(self._schema(table).column_names)} FROM {read_parquet(paths)}"
            )
            scope[table] = view
        errors: list[str] = []
        for table in sorted(set(table_outs.values())):
            schema = self._schema(table)
            duplicates = find_duplicates(self._con, scope[table], schema.primary_key)
            if duplicates:
                errors.append(
                    f"テーブル {table!r} の入力と出力の範囲で主キー "
                    f"{list(schema.primary_key)} が重複する: {duplicates}"
                )
        for key, table in sorted(table_outs.items()):
            schema = self._schema(table)
            relation = read_parquet([(root / decl.out_path(key)).as_posix()])
            for fk in schema.foreign_keys:
                if self._schema(fk.ref_table).role is not TableRole.DATA:
                    continue
                errors += [
                    f"outs.{key}: {e}"
                    for e in check_foreign_key(
                        self._con, relation, fk, scope[fk.ref_table]
                    )
                ]
        if errors:
            raise ValidationError(f"{decl.yaml_path}: " + "; ".join(errors))


def _resolve_param(root: Path, file: str, key: str, where: str) -> YamlValue:
    value = load_yaml(root / file)
    for part in key.split("."):
        if not isinstance(value, dict) or part not in value:
            raise ConfigError(f"{where}: {file} にキー {key!r} がない")
        value = value[part]
    return value


# dvc.yaml を再生成せずに実行すると、DataStore から見える範囲と DVC が追跡する依存が食い違う。
def _check_dvc_yaml(project: Project, plan: StagePlan) -> None:
    path = project.root / DVC_YAML
    current = load_yaml(path) if path.is_file() else None
    stages = current.get("stages") if isinstance(current, dict) else None
    entry = stages.get(plan.decl.name) if isinstance(stages, dict) else None
    if entry != stage_entry(project, plan):
        raise ConfigError(
            f"{DVC_YAML} の stage {plan.decl.name!r} が宣言と一致しない。"
            "staqkit generate で再生成すること"
        )


def run_stage(run: Callable[[StageInfo, DataStore], None]) -> None:
    run_file = Path(run.__code__.co_filename).resolve()
    try:
        root = find_root(run_file.parent)
        name = rel_posix(run_file.parent, root / STAGES_DIR)
        project = Project.load(root)
        plan = project.plans.get(name)
        if plan is None:
            raise ConfigError(f"{run_file}: stage {name!r} の stage.yaml がない")
        _check_dvc_yaml(project, plan)
        params = {
            local: _resolve_param(
                root, b.file, b.key, f"{plan.decl.yaml_path}: params.{local}"
            )
            for local, b in plan.decl.params.items()
        }
        stage = StageInfo(name, root, params, plan)
        store = DataStore(project, plan)
        try:
            run(stage, store)
            store.epilogue()
        finally:
            store.close()
    except StaqkitError as e:
        print(f"staqkit: {e}", file=sys.stderr)
        sys.exit(1)
