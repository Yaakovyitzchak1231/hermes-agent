"""CLI entry point for the Hermes AG-UI adapter (HTTP/SSE server).

Usage::

    hermes agui                     # bundled platform plugin subcommand
    python -m plugins.platforms.agui

Configuration:
    Behavioral settings live in the ``platforms.agui`` section of
    ``config.yaml`` (``host``, ``port``, ``toolsets`` + optional ``provider`` /
    ``model`` / ``api_mode`` / ``base_url`` model overrides). See
    ``settings.DEFAULTS`` and ``session.AgentConfig``. The ``hermes agui`` flags
    (``--host`` / ``--port`` / ``--token``) override those per invocation.

Environment (secrets only):
    HERMES_AGUI_SESSION_TOKEN  required off-loopback; optional loopback defense-in-depth
"""

# IMPORTANT: hermes_bootstrap must be the very first import - UTF-8 stdio
# on Windows.  No-op on POSIX.  See hermes_bootstrap.py for full rationale.
try:
    import hermes_bootstrap
except ModuleNotFoundError as exc:
    if exc.name != "hermes_bootstrap":
        raise
    # Graceful fallback when hermes_bootstrap isn't registered in the venv
    # yet - happens during partial ``hermes update`` where git-reset landed
    # new code but ``uv pip install -e .`` didn't finish.  Missing bootstrap
    # means UTF-8 stdio setup is skipped on Windows; POSIX is unaffected.
else:
    # Stop a ``utils/``/``proxy/``/``ui/`` package in the launch directory from
    # shadowing Hermes's own modules - ``hermes agui`` can be started from any
    # cwd, including a project that has same-named packages on its path.
    hermes_bootstrap.harden_import_path()

# No ``from __future__ import annotations`` here: a future statement must
# precede every other import, which would displace hermes_bootstrap and break
# the entry-point contract (tests/test_hermes_bootstrap.py). It is unnecessary
# anyway - requires-python is >=3.11, so PEP 604/585 annotations are native.
# None of the other Hermes entry points carry one either.
import logging
import sys


def _setup_logging() -> None:
    from agent.redact import RedactingFormatter

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        RedactingFormatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%H:%M:%S"
        )
    )
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    for noisy in ("httpx", "httpcore", "openai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def _load_listener_config() -> tuple[str, int]:
    """Resolve (host, port) from the ``platforms.agui`` section of ``config.yaml``.

    Behavioral settings, so they come from config - not the environment. A
    missing/invalid config falls back to the loopback defaults.
    """
    from . import settings

    return settings.listener(settings.load_settings())


def main(
    argv: list[str] | None = None,
    *,
    host: str | None = None,
    port: int | None = None,
    token: str | None = None,
) -> None:
    """Start the AG-UI server.

    ``host`` / ``port`` / ``token`` are the ``hermes agui`` CLI overrides; when
    omitted, host/port come from ``config.yaml`` (``platforms.agui``) and the
    token from the ``HERMES_AGUI_SESSION_TOKEN`` environment variable (a secret).
    """
    _setup_logging()
    from hermes_cli.env_loader import load_hermes_dotenv

    # Unlike `hermes agui`, the module launcher does not pass through
    # main.py's environment bootstrap. Use the same profile-aware loader.
    load_hermes_dotenv()
    import uvicorn

    from agent.secret_scope import get_secret

    from . import settings
    from .auth import require_token_or_refuse
    from .server import create_app

    cfg_host, cfg_port = _load_listener_config()
    try:
        host, port = settings.listener_strict(
            {
                "host": cfg_host if host is None else host,
                "port": cfg_port if port is None else port,
            }
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    token = token or get_secret("HERMES_AGUI_SESSION_TOKEN") or None
    # main() is the authoritative fail-closed guard: it passes the SAME host to both
    # require_token_or_refuse and uvicorn.run below, so a network-accessible bind
    # without a usable token refuses to start. create_app() also re-checks against
    # the bound_host it is GIVEN, but that only protects an embedder that passes a
    # bound_host matching its real serve interface (see create_app's docstring).
    require_token_or_refuse(host, token)
    logging.getLogger(__name__).info(
        "Starting Hermes AG-UI adapter on %s:%d", host, port
    )
    uvicorn.run(
        create_app(session_token=token, bound_host=host),
        host=host,
        port=port,
        workers=1,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
