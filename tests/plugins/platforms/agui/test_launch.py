"""AG-UI launchers are thin, non-interactive, and share argument semantics."""

import os
from pathlib import Path
import subprocess
import sys
import socket
import signal
from unittest.mock import Mock

import pytest


def test_register_shape():
    """One manifest registers both the gateway platform and ``hermes agui``."""
    from gateway.config import PlatformConfig
    from gateway.platform_registry import PlatformEntry
    from plugins.platforms.agui import (
        check_requirements,
        ensure_deps,
        interactive_setup,
        is_connected,
        register,
        validate_config,
    )
    from plugins.platforms.agui import cli
    from plugins.platforms.agui.adapter import AGUIAdapter

    captured = {"platform": {}, "cli": {}}

    class _Ctx:
        def register_platform(self, **kwargs):
            captured["platform"].update(kwargs)

        def register_cli_command(self, **kwargs):
            captured["cli"].update(kwargs)

    register(_Ctx())

    entry = PlatformEntry(**captured["platform"])
    assert entry.name == "agui" and entry.label == "AG-UI"
    assert entry.check_fn is check_requirements
    assert entry.ensure_deps_fn is ensure_deps
    assert entry.validate_config is validate_config
    assert entry.is_connected is is_connected
    assert entry.setup_fn is interactive_setup
    assert entry.required_env == []
    assert entry.install_hint == "hermes pm install --extra agui"
    assert entry.allow_update_command is False
    assert "AG-UI" in entry.platform_hint

    adapter = entry.adapter_factory(PlatformConfig(enabled=True))
    assert isinstance(adapter, AGUIAdapter)
    assert (adapter.host, adapter.port) == ("127.0.0.1", 8000)
    assert adapter.authorization_is_upstream is True

    assert captured["cli"]["name"] == "agui"
    assert captured["cli"]["setup_fn"] is cli.add_arguments
    assert captured["cli"]["handler_fn"] is cli.run


def test_main_parser_routes_agui_to_the_plugin_handler(monkeypatch, capsys):
    """A bare ``hermes agui`` resolves the deferred plugin command."""
    from hermes_cli.main import _build_cli_parser

    monkeypatch.setattr(
        sys,
        "argv",
        ["hermes", "agui", "--host", "127.0.0.1", "--port", "9123", "--token", "fake-token"],
    )

    parser, _ = _build_cli_parser()
    args = parser.parse_args(
        ["agui", "--host", "127.0.0.1", "--port", "9123", "--token", "fake-token"]
    )
    assert args.func is not None
    assert (args.agui_host, args.agui_port, args.agui_token) == (
        "127.0.0.1",
        9123,
        "fake-token",
    )
    assert args.check is False

    # Executing the routed handler in check mode proves the parser picked the
    # AG-UI command, not a chat fallback, and starts no server.
    check = parser.parse_args(["agui", "--check"])
    assert check.func(check) is None
    assert "Hermes AG-UI check OK" in capsys.readouterr().out


def test_cli_run_delegates_to_the_standalone_server(monkeypatch):
    from plugins.platforms.agui import cli, entry

    serve = Mock()
    monkeypatch.setattr(entry, "main", serve)
    args = type(
        "Args",
        (),
        {
            "check": False,
            "agui_host": "127.0.0.1",
            "agui_port": 9123,
            "agui_token": "fake-token",
        },
    )()

    cli.run(args)

    serve.assert_called_once_with(host="127.0.0.1", port=9123, token="fake-token")


@pytest.mark.live_system_guard_bypass
@pytest.mark.parametrize(
    "flag,output", [("--help", "--host"), ("--check", "Hermes AG-UI check OK")]
)
def test_module_flags_exit_without_a_tty_or_server(flag, output):
    result = subprocess.run(
        [sys.executable, "-m", "plugins.platforms.agui", flag],
        cwd=Path(__file__).resolve().parents[4],
        env=os.environ.copy(),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert output in result.stdout
    assert "Starting Hermes AG-UI adapter" not in result.stderr


@pytest.mark.live_system_guard_bypass
@pytest.mark.platforms("posix")
@pytest.mark.parametrize("web_concurrency", [None, "2", "bad"])
def test_headless_module_serves_health_and_enforces_token(web_concurrency):
    import httpx
    from tests.waiting import wait_until

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    token = "r4N7g2V9q5H1c8L6p3S0u9F2d4K7m1W5"
    env = os.environ.copy()
    env.pop("WEB_CONCURRENCY", None)
    if web_concurrency is not None:
        env["WEB_CONCURRENCY"] = web_concurrency
    with subprocess.Popen(
        [
            sys.executable,
            "-m",
            "plugins.platforms.agui",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--token",
            token,
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=Path(__file__).resolve().parents[4],
        env=env,
        text=True,
    ) as process:
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=1) as client:

                def ready():
                    assert process.poll() is None, (
                        "server exited before becoming healthy"
                    )
                    try:
                        return client.get("/health").status_code == 200
                    except httpx.TransportError:
                        return False

                wait_until(ready, timeout=10, what="headless AG-UI health endpoint")
                assert client.post("/", json={}).status_code == 401
                assert (
                    client.post(
                        "/", json={}, headers={"X-Hermes-Session-Token": token}
                    ).status_code
                    == 400
                )
        finally:
            process.terminate()
            try:
                _, stderr = process.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                _, stderr = process.communicate(timeout=5)
        # uvicorn re-raises the captured signal after completing lifespan
        # shutdown. A SIGTERM exit is expected; SIGKILL or a traceback is not.
        assert process.returncode == -signal.SIGTERM, stderr
        assert "Traceback" not in stderr


@pytest.mark.live_system_guard_bypass
def test_network_bind_without_token_fails_before_serving(monkeypatch):
    monkeypatch.delenv("HERMES_AGUI_SESSION_TOKEN", raising=False)
    env = os.environ.copy()
    env.pop("HERMES_AGUI_SESSION_TOKEN", None)
    result = subprocess.run(
        [sys.executable, "-m", "plugins.platforms.agui", "--host", "0.0.0.0"],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        cwd=Path(__file__).resolve().parents[4],
        env=env,
    )
    assert result.returncode == 1
    assert "Refusing to start" in result.stderr


@pytest.mark.parametrize("missing", ["ag_ui", "internal_adapter_bug"])
def test_dependency_errors_do_not_hide_internal_import_failures(
    monkeypatch, capsys, missing
):
    from plugins.platforms.agui import cli

    def unavailable(name):
        raise ModuleNotFoundError(f"No module named {missing!r}", name=missing)

    monkeypatch.setattr(cli.importlib, "import_module", unavailable)
    args = type("Args", (), {"check": True})()
    with pytest.raises(SystemExit if missing == "ag_ui" else ModuleNotFoundError):
        cli.run(args)
    stderr = capsys.readouterr().err
    assert ("hermes pm install --extra agui" in stderr) == (missing == "ag_ui")
