"""Configuration resolution for the AG-UI platform plugin.

Behavioral settings live under ``platforms.agui`` in ``config.yaml`` so they
follow the same per-profile rules as every other gateway platform::

    platforms:
      agui:
        enabled: true
        host: 127.0.0.1
        port: 8000
        toolsets: [hermes-acp]

Two older spellings are still read as fallbacks, in order:
``gateway.platforms.agui`` and a top-level ``agui:`` block (the pre-plugin
adapter's layout). Secrets never live here - the session token is
``HERMES_AGUI_SESSION_TOKEN`` in the profile's secret scope.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000

# Behavioral defaults shared by ``AgentConfig`` and the lifecycle readers.
DEFAULTS: dict[str, Any] = {
    "host": DEFAULT_HOST,
    "port": DEFAULT_PORT,
    "toolsets": ["hermes-acp"],
    "frontend_tool_timeout": 60,
    "max_conversations": 16,
    "conversation_idle_timeout": 1800,
}

# Newest spelling first. The top-level block is a migration aid only.
_SECTION_PATHS: tuple[tuple[str, ...], ...] = (
    ("platforms", "agui"),
    ("gateway", "platforms", "agui"),
    ("agui",),
)


def _nested(config: Any, path: tuple[str, ...]) -> Optional[dict]:
    node = config
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node if isinstance(node, dict) else None


def load_settings() -> dict:
    """Return the effective AG-UI settings block (empty dict if unavailable).

    A missing or invalid config is non-fatal: callers fall back to
    :data:`DEFAULTS`. Read through ``load_config`` (never ``os.environ``) so a
    secondary multiplex profile sees its own section, not the launcher's.
    """
    try:
        from hermes_cli.config import load_config

        config = load_config()
    except Exception:
        logger.debug("load_config() failed for platforms.agui; using defaults", exc_info=True)
        return {}
    for path in _SECTION_PATHS:
        section = _nested(config, path)
        if section is not None:
            return dict(section)
    return {}


def merged(extra: Any = None) -> dict:
    """Config-file settings overlaid with an adapter's ``PlatformConfig.extra``.

    ``extra`` is already the per-profile platform block (``PlatformConfig``
    promotes every non-typed key), so it wins on a clash.
    """
    settings = load_settings()
    if isinstance(extra, dict):
        settings.update(extra)
    return settings


def _listener_value(key: str, value: Any) -> Any:
    if key == "host":
        if not isinstance(value, str) or not value.strip():
            raise ValueError("platforms.agui.host must be a nonempty string.")
        return value
    message = "platforms.agui.port must be an integer from 0 to 65535."
    if isinstance(value, str):
        try:
            value = int(value)
        except ValueError:
            raise ValueError(message) from None
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 65535:
        raise ValueError(message)
    return value


def listener(settings: dict) -> tuple[str, int]:
    """Resolve ``(host, port)`` from *settings*, warning and defaulting on bad values."""
    resolved = {"host": DEFAULT_HOST, "port": DEFAULT_PORT}
    for key, default in resolved.items():
        try:
            resolved[key] = _listener_value(key, settings.get(key, default))
        except ValueError as exc:
            logger.warning("%s Using %r.", exc, default)
    return resolved["host"], resolved["port"]


def listener_strict(settings: dict) -> tuple[str, int]:
    """Like :func:`listener` but raises ``ValueError`` for an invalid override."""
    return (
        _listener_value("host", settings.get("host", DEFAULT_HOST)),
        _listener_value("port", settings.get("port", DEFAULT_PORT)),
    )


def session_token() -> Optional[str]:
    """The profile-scoped ``HERMES_AGUI_SESSION_TOKEN`` secret, if set."""
    from agent.secret_scope import get_secret

    return get_secret("HERMES_AGUI_SESSION_TOKEN") or None
