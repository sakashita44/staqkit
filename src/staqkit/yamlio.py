import datetime
import io
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from staqkit.errors import ConfigError

type YamlValue = (
    str
    | int
    | float
    | bool
    | None
    | datetime.date
    | datetime.datetime
    | list[YamlValue]
    | dict[str, YamlValue]
)


def load_yaml(path: Path) -> YamlValue:
    yaml = YAML(typ="safe", pure=True)
    try:
        with path.open(encoding="utf-8") as f:
            data: object = yaml.load(f)  # pyright: ignore[reportUnknownMemberType]
    except YAMLError as e:
        raise ConfigError(f"{path}: YAML を解析できない: {e}") from e
    return _check_value(data, path)


def _check_value(value: object, path: Path) -> YamlValue:
    if value is None or isinstance(
        value, str | int | float | bool | datetime.date | datetime.datetime
    ):
        return value
    if isinstance(value, list):
        return [_check_value(v, path) for v in cast(list[object], value)]
    if isinstance(value, dict):
        result: dict[str, YamlValue] = {}
        for k, v in cast(dict[object, object], value).items():
            if not isinstance(k, str):
                raise ConfigError(f"{path}: キー {k!r} が文字列でない")
            result[k] = _check_value(v, path)
        return result
    raise ConfigError(f"{path}: 扱えない値 {value!r}")


def dump_yaml(data: Mapping[str, YamlValue]) -> str:
    yaml = YAML()
    yaml.width = 4096
    yaml.indent(mapping=2, sequence=4, offset=2)
    buf = io.StringIO()
    yaml.dump(data, buf)  # pyright: ignore[reportUnknownMemberType]
    return buf.getvalue()


def expect_mapping(
    value: YamlValue,
    where: str,
    *,
    required: set[str] | None = None,
    optional: set[str] | None = None,
) -> dict[str, YamlValue]:
    if not isinstance(value, dict):
        raise ConfigError(f"{where}: 対応（mapping）でなければならない")
    if required is not None or optional is not None:
        req = required or set()
        allowed = req | (optional or set())
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise ConfigError(
                f"{where}: 許可しないキー {unknown}（許可するキー: {sorted(allowed)}）"
            )
        missing = sorted(req - set(value))
        if missing:
            raise ConfigError(f"{where}: 必須のキー {missing} がない")
    return value


def expect_str(value: YamlValue, where: str) -> str:
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{where}: 空でない文字列でなければならない")
    return value


def expect_list(value: YamlValue, where: str) -> list[YamlValue]:
    if not isinstance(value, list):
        raise ConfigError(f"{where}: リストでなければならない")
    return value
