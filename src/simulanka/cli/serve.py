from __future__ import annotations

import typer

from simulanka.layout.project import ProjectLayout

serve_app = typer.Typer(
    help="Run the Simulanka HTTP graph server (requires `pip install -e '.[server]'`).",
    invoke_without_command=True,
    no_args_is_help=False,
)


@serve_app.callback()
def serve(
    host: str = typer.Option("127.0.0.1", help="Bind host."),
    port: int = typer.Option(8765, help="Bind port."),
    reload: bool = typer.Option(False, help="Auto-reload on code change."),
) -> None:
    """Start the FastAPI graph server against the current Simulanka project."""
    try:
        import uvicorn
    except ImportError as exc:
        raise typer.BadParameter(
            "uvicorn not installed. Run: pip install -e '.[server]'"
        ) from exc

    layout = ProjectLayout.require()
    typer.echo(f"Serving Simulanka project at {layout.dot_dir} on http://{host}:{port}")

    if reload:
        # Reload mode requires an import string so uvicorn can re-import the app.
        # We use the factory pattern so ProjectLayout is re-discovered each reload.
        uvicorn.run(
            "simulanka.server.app:create_app",
            host=host,
            port=port,
            reload=True,
            factory=True,
        )
    else:
        from simulanka.server.app import create_app

        uvicorn.run(create_app(layout), host=host, port=port)
