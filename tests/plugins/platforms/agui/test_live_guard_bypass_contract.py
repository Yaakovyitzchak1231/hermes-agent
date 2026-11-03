"""The launcher tests must keep their ``live_system_guard_bypass`` mark.

The autouse ``_live_system_guard`` intercepts ``os.kill`` and classifies a
target pid as own-subtree via a ``psutil`` ancestry walk. Without ``psutil``
it has no ledger and no walk, so every pid — including the test's own
freshly spawned server child — is foreign: ``process.terminate()`` raises
inside the test's ``finally``, the aborted teardown unwinds into
``subprocess.Popen.__exit__``, and its ``self.wait()`` has no timeout —
the whole suite wedges forever while the un-signaled child lives on.

These launcher tests deliver real signals to their own child and nothing
else, so they carry the guard's documented opt-out. Dropping the mark
reintroduces the wedge the first time anyone runs the suite from a venv
without ``psutil``.
"""

from tests.plugins.platforms.agui import test_launch, test_provider_startup


def _assert_marked(name, fn):
    marks = {m.name for m in getattr(fn, "pytestmark", [])}
    assert "live_system_guard_bypass" in marks, (
        f"{name} lost its live_system_guard_bypass mark: without psutil the "
        "live-system guard classifies the test's own spawned server as a "
        "foreign pid, blocks the teardown signal, and the suite wedges in "
        "Popen.__exit__'s unbounded wait()."
    )


def test_launcher_tests_bypass_the_live_system_guard():
    _assert_marked(
        "test_headless_module_serves_health_and_enforces_token",
        test_launch.test_headless_module_serves_health_and_enforces_token,
    )
    _assert_marked(
        "test_module_flags_exit_without_a_tty_or_server",
        test_launch.test_module_flags_exit_without_a_tty_or_server,
    )
    _assert_marked(
        "test_network_bind_without_token_fails_before_serving",
        test_launch.test_network_bind_without_token_fails_before_serving,
    )
    _assert_marked(
        "test_entry_points_use_configured_provider_and_discover_plugin_tools",
        test_provider_startup.test_entry_points_use_configured_provider_and_discover_plugin_tools,
    )
