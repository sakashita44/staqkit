from pathlib import Path

from staqkit.paths import DVC_YAML
from staqkit.project import Project, StagePlan
from staqkit.yamlio import YamlValue, dump_yaml


def stage_entry(project: Project, plan: StagePlan) -> dict[str, YamlValue]:
    decl = plan.decl
    deps = sorted(
        {decl.run_path}
        | {a.path for a in plan.input_artifacts}
        | set(plan.input_files.values())
        | set(decl.path_deps)
        | set(plan.key_files)
    )
    # DVC は deps の削除と、参照先の集合を変えない対応の入れ替えを検知しない。
    # stage.yaml の inputs と params を params 依存にして、これらの変更でも再実行させる。
    params: dict[str, set[str]] = {decl.yaml_path: {"inputs", "params"}}
    for binding in decl.params.values():
        params.setdefault(binding.file, set()).add(binding.key)
    # テーブル定義の説明文の編集では再実行させないよう、ddl キーだけを params 依存にする。
    for table in sorted(set(plan.data_tables) | set(plan.key_tables)):
        params.setdefault(project.schemas[table].path, set()).add("ddl")
    entry: dict[str, YamlValue] = {
        "cmd": f"python {decl.run_path}",
        "deps": list[YamlValue](deps),
        "params": [
            {file: list[YamlValue](sorted(keys))}
            for file, keys in sorted(params.items())
        ],
    }
    outs = sorted(decl.out_path(key) for key in decl.outs)
    if outs:
        entry["outs"] = list[YamlValue](outs)
    return entry


def generate(project: Project) -> str:
    stages: dict[str, YamlValue] = {
        name: stage_entry(project, project.plans[name])
        for name in sorted(project.plans)
    }
    return dump_yaml({"stages": stages})


def write_dvc_yaml(project: Project) -> Path:
    path = project.root / DVC_YAML
    path.write_text(generate(project), encoding="utf-8", newline="\n")
    return path
