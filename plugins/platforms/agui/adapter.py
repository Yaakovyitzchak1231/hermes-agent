"""Gateway lifecycle host for the AG-UI platform plugin.

AG-UI is a *stateless* HTTP/SSE surface: clients POST an AG-UI ``RunAgentInput``
and the FastAPI app in :mod:`plugins.platforms.agui.server` runs its own
``AIAgent`` worker. Nothing is dispatched through the gateway router, so this
adapter owns exactly one thing - the in-process uvicorn server - and reports
its state through the normal platform lifecycle (status, reconnect watcher,
``/platform stop|resume agui``).

Deliberately not a rewrite of the standalone server: ``hermes agui`` (and
``python -m plugins.platforms.agui``) still calls ``create_app`` + blocking
``uvicorn.run``. Hosting it under the gateway instead needs a non-blocking
``uvicorn.Server`` task, a socket bound in ``connect()`` so a port conflict is
a normal adapter failure, and no process-wide env mutation (the gateway owns
``HERMES_EXEC_ASK`` for every other platform).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import socket
from typing import Optional

from gateway.config import Platform
from gateway.platforms.base import BasePlatformAdapter, SendResult
from gateway.platforms.shared_ingress import listener_base_url

from . import settings

logger = logging.getLogger(__name__)

# uvicorn startup is fast (import + lifespan); this only bounds a wedged
# lifespan so ``connect()`` cannot hang the gateway's adapter bring-up.
_STARTUP_TIMEOUT = 15.0
_STARTUP_POLL = 0.05
_SHUTDOWN_TIMEOUT = 10.0


def _bind_socket(host: str, port: int) -> socket.socket:
    """Bind and return a listening TCP socket for ``host:port``.

    ``port=0`` is resolved by the OS and readable via ``getsockname()``.
    Resolution honours every address family ``getaddrinfo`` returns (IPv6
    first on dual-stack hosts), mirroring uvicorn's bind semantics. A bind
    failure raises ``OSError`` *before* uvicorn starts, so the gateway sees a
    normal adapter failure instead of a background task dying later.
    """
    last_error: Optional[OSError] = None
    for family, socktype, proto, _canonname, sockaddr in socket.getaddrinfo(
        host, port, type=socket.SOCK_STREAM
    ):
        sock = socket.socket(family, socktype, proto)
        try:
            if os.name != "nt":
                # Windows SO_REUSEADDR permits hijacking a live listener, which
                # would defeat the pre-bind conflict check; POSIX needs it to
                # rebind past TIME_WAIT (same policy as uvicorn's bind_socket).
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(sockaddr)
            sock.setblocking(False)
            return sock
        except OSError as exc:
            last_error = exc
            sock.close()
    raise last_error or OSError(f"could not bind {host}:{port}")


class AGUIAdapter(BasePlatformAdapter):
    """Own the uvicorn server that serves the AG-UI FastAPI app."""

    # No inbound router traffic and no ``send()`` delivery: a resumed turn must
    # complete rather than be promised an async delivery the adapter cannot make.
    supports_async_delivery = False
    interactive_resume = False

    def __init__(self, config, **kwargs):
        super().__init__(config=config, platform=Platform("agui"))
        extra = getattr(config, "extra", {}) or {}
        self.host, self.port = settings.listener_strict(settings.merged(extra))
        # Secrets come from the profile's scope; ``PlatformConfig.token`` is a
        # compatibility fallback for programmatic embedders (config.yaml is not
        # the documented place to put this credential).
        self._session_token = settings.session_token() or (
            getattr(config, "token", None) or None
        )
        self._server = None
        self._serve_task: Optional[asyncio.Task] = None
        self._socket: Optional[socket.socket] = None
        self._app = None

    @property
    def name(self) -> str:
        return "AG-UI"

    @property
    def authorization_is_upstream(self) -> bool:
        """Requests are authenticated by the AG-UI app's middleware.

        Every non-``/health`` request is 401'd unless it carries the configured
        session token, and a network-accessible bind without one refuses to
        start. The gateway's allowlist would otherwise reject AG-UI clients
        (their identity is not a chat user id). Same delegation as A2A - wrong
        credentials still fail closed.
        """
        return True

    async def connect(self, *, is_reconnect: bool = False) -> bool:
        """Bind the listener and start uvicorn as a background task."""
        if self._serve_task is not None and not self._serve_task.done():
            return True  # already serving (idempotent, like other HTTP adapters)

        from .auth import token_problem

        problem = token_problem(self.host, self._session_token)
        if problem is not None:
            # Config error: retrying the same token/host pair cannot succeed.
            logger.error("%s", problem)
            self._set_fatal_error("agui_token_required", problem, retryable=False)
            return False

        try:
            self._socket = _bind_socket(self.host, self.port)
        except OSError as exc:
            # A port conflict is a configuration error, not a transient blip;
            # retryable=False drops it from the reconnect queue instead of
            # leaking a fresh adapter every backoff cycle (see api_server).
            logger.error(
                "AG-UI: could not bind %s:%s - %s. Set a different port in "
                "config.yaml: platforms.agui.port",
                self.host,
                self.port,
                exc,
            )
            self._set_fatal_error(
                "agui_port_in_use",
                f"Could not bind {self.host}:{self.port}: {exc}. Set "
                f"platforms.agui.port in config.yaml to a different value, then "
                f"`/platform resume agui`.",
                retryable=False,
            )
            return False

        # The OS resolves port 0 at bind time; report the real listener.
        self.port = self._socket.getsockname()[1]

        try:
            import uvicorn

            from .server import create_app

            self._app = create_app(
                session_token=self._session_token,
                bound_host=self.host,
                # The gateway owns HERMES_EXEC_ASK process-wide and other
                # platforms may rely on it; clearing it here would be a global
                # side effect. AG-UI's worker sets its own interactive
                # contextvar + thread-local approval callback instead.
                isolate_process_env=False,
            )
            server = uvicorn.Server(
                uvicorn.Config(
                    self._app,
                    host=self.host,
                    port=self.port,
                    workers=1,
                    log_level="warning",
                )
            )
            # serve() wraps startup in capture_signals(); installing signal
            # handlers from a non-main task would fail (and would steal the
            # gateway's own handlers).
            server.capture_signals = contextlib.nullcontext
            self._server = server
            self._serve_task = asyncio.create_task(
                server.serve(sockets=[self._socket]), name="agui-uvicorn"
            )
            self._background_tasks.add(self._serve_task)
            self._serve_task.add_done_callback(self._background_tasks.discard)
            await self._wait_until_started()
        except asyncio.CancelledError:
            await self._stop_server()
            raise
        except (Exception, SystemExit) as exc:
            await self._stop_server()
            logger.error("AG-UI: server failed to start - %s", exc, exc_info=True)
            self._set_fatal_error(
                "agui_start_failed", f"AG-UI server failed to start: {exc}",
                retryable=True,
            )
            return False

        self._mark_connected(listener_base=listener_base_url(self.host, self.port))
        logger.info(
            "AG-UI: serving on %s (%s)",
            listener_base_url(self.host, self.port),
            "token required" if self._session_token else "loopback only, no token",
        )
        return True

    async def _wait_until_started(self) -> None:
        """Wait for uvicorn's lifespan startup, surfacing a dead server task."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + _STARTUP_TIMEOUT
        while not (self._server and self._server.started):
            if self._serve_task is None or self._serve_task.done():
                exc = None
                if self._serve_task is not None and not self._serve_task.cancelled():
                    exc = self._serve_task.exception()
                raise RuntimeError(
                    f"server task exited before startup completed ({exc!r})"
                )
            if loop.time() >= deadline:
                raise TimeoutError(
                    f"server did not start within {_STARTUP_TIMEOUT:g}s"
                )
            await asyncio.sleep(_STARTUP_POLL)

    async def disconnect(self) -> None:
        """Ask uvicorn to shut down and release the listener."""
        self._mark_disconnected()
        await self._stop_server()
        logger.info("AG-UI: server stopped")

    async def _stop_server(self) -> None:
        server, task, sock = self._server, self._serve_task, self._socket
        self._server = None
        self._serve_task = None
        self._socket = None
        self._app = None

        if server is not None:
            server.should_exit = True
        if task is not None and not task.done():
            try:
                await asyncio.wait_for(task, timeout=_SHUTDOWN_TIMEOUT)
            except TimeoutError:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
            except asyncio.CancelledError:
                # Gateway shutdown cancelled us; wait_for already cancelled the
                # server task, so let the cancellation propagate.
                task.cancel()
                raise
            except Exception:
                logger.warning(
                    "AG-UI: server task failed during shutdown", exc_info=True
                )
        # uvicorn closes the sockets handed to serve(); close defensively when
        # startup never reached that point (idempotent for a closed socket).
        if sock is not None:
            with contextlib.suppress(OSError):
                sock.close()

    async def send(
        self,
        chat_id: str,
        content: str,
        reply_to: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> SendResult:
        """Unused - the AG-UI app delivers over its own HTTP/SSE response."""
        return SendResult(
            success=False, error="AG-UI delivers replies over HTTP/SSE, not send()"
        )

    async def send_typing(self, chat_id: str, metadata=None) -> None:
        return None

    async def get_chat_info(self, chat_id: str) -> dict:
        return {"name": f"agui:{chat_id}", "type": "dm"}
