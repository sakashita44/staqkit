from pathlib import Path

import typer

from staqkit.check import check_project
from staqkit.errors import StaqkitError
from staqkit.paths import find_root
from staqkit.pipeline import write_dvc_yaml
from staqkit.project import Project

app = typer.Typer(no_args_is_help=True)


@app.command()
def generate() -> None:
    try:
        path = write_dvc_yaml(Project.load(find_root(Path.cwd())))
    except StaqkitError as e:
        typer.echo(f"staqkit: {e}", err=True)
        raise typer.Exit(1) from e
    typer.echo(f"{path} を生成した")


@app.command()
def check() -> None:
    try:
        check_project(find_root(Path.cwd()))
    except StaqkitError as e:
        typer.echo(f"staqkit: {e}", err=True)
        raise typer.Exit(1) from e
    typer.echo("検査に合格した")
