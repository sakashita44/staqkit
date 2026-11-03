import re
from pathlib import Path, PurePosixPath, PureWindowsPath

from staqkit.errors import ConfigError

STAGES_DIR = "stages"
TABLE_SCHEMAS_DIR = "config/table_schemas"
KEYS_DIR = "config/keys"
DATA_STAGES_DIR = "data/stages"
DVC_YAML = "dvc.yaml"
DVC_LOCK = "dvc.lock"

# DVC は @ を foreach の展開名に用い、: を <ファイル>:<stage> の指定に用いるため、stage 名には使わない。
_STAGE_SEGMENT = re.compile(r"[A-Za-z0-9_-]+")


def find_root(start: Path) -> Path:
    current = start.resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".dvc").is_dir():
            return candidate
    raise ConfigError(f"{start}: .dvc/ を含むプロジェクトのルートが見つからない")


def check_rel_path(value: str, where: str) -> str:
    posix = PurePosixPath(value)
    invalid = (
        not value
        or "\\" in value
        or posix.is_absolute()
        or PureWindowsPath(value).drive != ""
        or posix.as_posix() != value
        or any(part in (".", "..") for part in value.split("/"))
    )
    if invalid:
        raise ConfigError(
            f"{where}: パス {value!r} は '/' 区切りの正規形の相対パスでなければならない"
        )
    return value


def check_stage_name(name: str, where: str) -> str:
    segments = name.split("/")
    if not all(_STAGE_SEGMENT.fullmatch(s) for s in segments):
        raise ConfigError(
            f"{where}: stage 名 {name!r} の各区切りは [A-Za-z0-9_-]+ でなければならない"
        )
    return name


def rel_posix(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def discover(root: Path, directory: str, pattern: str) -> list[Path]:
    base = root / directory
    if not base.is_dir():
        return []
    return sorted(base.rglob(pattern), key=lambda p: rel_posix(p, root))
