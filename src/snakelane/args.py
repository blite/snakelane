"""`--app` / `--platform`, identical on every command, and turning them into an app and a platform."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated, Any

import typer

from . import project


def load_app(app_arg: str | None = None) -> tuple[Path, dict[str, Any]]:
    """The app's metadata folder and its parsed snakelane.yml."""
    app = project.resolve_app(app_arg)
    return app.folder, app.config


def resolve_platform(app_config: dict[str, Any], platform: str | None) -> str:
    """`--platform`, else `ios` if the app ships it, else the app's only platform."""
    platforms = app_config.get("platforms", [])
    if platform is None:
        platform = "ios" if "ios" in platforms or len(platforms) != 1 else platforms[0]
    if platform not in platforms:
        raise SystemExit(f"platform {platform!r} is not listed in snakelane.yml's \"platforms\" "
                         f"({platforms}) for {app_config.get('name', '?')}")
    return platform


AppOption = Annotated[str | None, typer.Option(
    "--app", show_default=False,
    help="which app: the <name> of snakelane.<name>.yml or an alias (default: the repo's only app)")]
PlatformOption = Annotated[str | None, typer.Option(
    "--platform", show_default=False,
    help="a platform from the config's \"platforms\" (default: ios, or the app's only platform)")]


def command_app(help: str, no_args_is_help: bool = True) -> typer.Typer:
    """A typer app for one command; `no_args_is_help=False` when the bare form does something."""
    return typer.Typer(help=help, add_completion=False, no_args_is_help=no_args_is_help,
                       context_settings={"help_option_names": ["-h", "--help"]})


def run(app: typer.Typer, argv: list[str] | None, prog: str) -> None:
    """Usage errors exit 2; a clean exit returns, so tests and `cli.py` can both call `main()`.
    An App Store Connect or network failure, from any command, is one line and exit 1."""
    try:
        typer.main.get_command(app).main(args=argv, prog_name=prog)
    except SystemExit as done:
        if done.code:
            raise
    except Exception as error:
        if (message := asc_failure(error)) is None:
            raise
        raise SystemExit(message) from None


def asc_failure(error: Exception) -> str | None:
    if "requests" not in sys.modules:  # nothing networked was loaded, so this is a bug: show the traceback
        return None
    import requests

    from .connect import asc

    if isinstance(error, asc.TransientNetworkError):
        return f"network error: {error}"
    if isinstance(error, asc.ASCError):
        return f"error: {error}"
    if isinstance(error, requests.RequestException):
        return f"network error talking to App Store Connect: {error}"
    return None
