"""Behavior contracts for the AG-UI edit-approval gate.

Core routes ``write_file``/``patch`` through
``acp_adapter.edit_approval.maybe_require_edit_approval`` before dispatch; that
seam only asks when a requester is bound. The AG-UI server binds one for the
duration of a turn, parking the worker on the same interrupt/resume lifecycle as
dangerous commands. These tests prove the gate carries a real diff, honors
approve/deny/timeout, and exists only while a run binds it.
"""

from __future__ import annotations

import concurrent.futures
import json
import threading

import pytest

from acp_adapter import edit_approval
from acp_adapter.edit_approval import EditProposal
from plugins.platforms.agui import approvals
from tests.waiting import wait_until


@pytest.fixture
def registry():
    return approvals.ApprovalRegistry()


def _proposal(path="notes.txt", *, old=None, new="hello\n", tool="write_file", **extra):
    return EditProposal(
        tool, path, old, new, {"path": path, "content": new, **extra}
    )


def _requester(registry, thread_id="t1", timeout=5.0):
    emitted = []
    requester = approvals.make_edit_approval_requester(
        registry=registry,
        thread_id=thread_id,
        emit=emitted.append,
        queue=object(),
        new_id=lambda _: "int-1",
        timeout=timeout,
    )
    return requester, emitted


def _call_in_thread(fn):
    box, done = {}, threading.Event()

    def run():
        try:
            box["value"] = fn()
        except BaseException as exc:  # re-raised by _value() in the test thread
            box["error"] = exc
        finally:
            done.set()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread, box, done


def _value(box):
    if "error" in box:
        raise box["error"]
    return box["value"]


def _park(registry, thread_id="t1"):
    return wait_until(lambda: registry.take(thread_id), what="edit approval parked")


def test_edit_approval_emits_a_diff_interrupt_and_resumes(registry):
    requester, emitted = _requester(registry)
    _thread, box, done = _call_in_thread(
        lambda: requester(_proposal(old="one\ntwo\n", new="one\nthree\n"))
    )
    parked = _park(registry)

    assert emitted[0][0] is approvals.PARK
    interrupt = emitted[0][1]
    assert interrupt.id == "int-1"
    assert interrupt.reason == "tool_call"
    # The write has not been dispatched, so there is no tool call to attach.
    assert interrupt.tool_call_id is None
    assert interrupt.response_schema["properties"]["scope"]["enum"] == ["once"]
    assert "write_file" in interrupt.message
    assert "notes.txt" in interrupt.message
    assert "-two" in interrupt.message
    assert "+three" in interrupt.message

    parked.pending.decision.set_result("once")
    assert done.wait(timeout=5)
    assert _value(box) is True


def test_denied_edit_returns_false(registry):
    requester, _emitted = _requester(registry)
    _thread, box, done = _call_in_thread(lambda: requester(_proposal()))
    parked = _park(registry)

    parked.pending.decision.set_result("deny")
    assert done.wait(timeout=5)
    assert _value(box) is False


def test_edit_approval_timeout_denies(registry):
    requester, emitted = _requester(registry, timeout=0.2)

    assert requester(_proposal()) is False
    assert emitted and emitted[0][0] is approvals.PARK
    assert not registry.is_parked("t1")


def test_edit_approval_denies_when_thread_already_parked(registry):
    other = concurrent.futures.Future()
    registry.register(
        approvals.ParkedRun(
            "t1",
            object(),
            approvals.PendingApproval("i0", "rm -rf a", "d", None, True, other),
        )
    )
    requester, emitted = _requester(registry)

    assert requester(_proposal()) is False
    assert emitted == []  # refused before an interrupt could be emitted
    other.set_result("deny")


def test_write_file_is_gated_through_the_core_seam(registry, tmp_path):
    target = tmp_path / "notes.txt"
    target.write_text("old\n", encoding="utf-8")
    requester, emitted = _requester(registry)

    def worker():
        token = edit_approval.set_edit_approval_requester(requester)
        try:
            return edit_approval.maybe_require_edit_approval(
                "write_file", {"path": str(target), "content": "new\n"}
            )
        finally:
            edit_approval.reset_edit_approval_requester(token)

    _thread, box, done = _call_in_thread(worker)
    parked = _park(registry)

    # The real proposal built from the file reached the requester.
    assert "-old" in emitted[0][1].message
    assert "+new" in emitted[0][1].message
    assert not done.is_set()  # blocked: the write cannot proceed while parked

    parked.pending.decision.set_result("deny")
    assert done.wait(timeout=5)
    blocked = json.loads(_value(box))
    assert "denied" in blocked["error"].lower()
    assert target.read_text(encoding="utf-8") == "old\n"


def test_approved_write_file_proceeds(registry, tmp_path):
    target = tmp_path / "notes.txt"
    target.write_text("old\n", encoding="utf-8")
    requester, _emitted = _requester(registry)

    def worker():
        token = edit_approval.set_edit_approval_requester(requester)
        try:
            return edit_approval.maybe_require_edit_approval(
                "write_file", {"path": str(target), "content": "new\n"}
            )
        finally:
            edit_approval.reset_edit_approval_requester(token)

    _thread, box, done = _call_in_thread(worker)
    parked = _park(registry)

    parked.pending.decision.set_result("once")
    assert done.wait(timeout=5)
    assert _value(box) is None  # dispatch continues


def test_no_requester_leaves_the_gate_open():
    token = edit_approval.set_edit_approval_requester(None)
    try:
        assert (
            edit_approval.maybe_require_edit_approval(
                "write_file", {"path": "does-not-need-to-exist", "content": "x"}
            )
            is None
        )
    finally:
        edit_approval.reset_edit_approval_requester(token)


def test_run_turn_binds_the_edit_requester_and_restores_it(monkeypatch, tmp_path):
    from ag_ui.core import RunAgentInput

    from plugins.platforms.agui import server

    target = tmp_path / "notes.txt"
    target.write_text("old\n", encoding="utf-8")
    seen = {}

    class _FakeAgent:
        def __init__(self):
            for attr in (
                "stream_delta_callback",
                "reasoning_callback",
                "tool_progress_callback",
                "step_callback",
                "thinking_callback",
            ):
                setattr(self, attr, None)

        def run_conversation(self, user_message, conversation_history=None):
            seen["gated"] = edit_approval.maybe_require_edit_approval(
                "write_file", {"path": str(target), "content": "new\n"}
            )
            return {"final_response": "", "messages": []}

    monkeypatch.setattr(server, "build_run_agent", lambda *a, **k: _FakeAgent())

    run_input = RunAgentInput.model_validate(
        {
            "threadId": "t-edit",
            "runId": "r-edit",
            "state": {},
            "messages": [{"id": "m1", "role": "user", "content": "edit it"}],
            "tools": [],
            "context": [],
            "forwardedProps": {},
        }
    )
    server._run_turn(
        run_input,
        server.AgentConfig(),
        server.AGUIEventBridge(lambda _e: None),
        {},
        approval_cb=lambda *a, **k: "deny",
        edit_requester=lambda _proposal: False,
    )

    # The requester was live on the worker thread during the turn...
    assert "denied" in json.loads(seen["gated"])["error"].lower()
    # ...and the binding did not leak to the caller's context.
    assert (
        edit_approval.maybe_require_edit_approval(
            "write_file", {"path": str(target), "content": "new\n"}
        )
        is None
    )


def test_v4a_patch_message_shows_the_exact_patch():
    patch_body = (
        "*** Begin Patch\n*** Update File: a.py\n@@\n-old\n+new\n*** End Patch"
    )
    proposal = EditProposal(
        "patch",
        "a.py, b.py",
        None,
        patch_body,
        {"mode": "patch", "patch": patch_body},
        ("a.py", "b.py"),
    )

    message = approvals.edit_interrupt_message(proposal)

    assert patch_body in message
    assert "--- a/" not in message  # raw V4A, not a synthesized diff


def test_edit_message_truncates_large_diffs():
    new = "x" * (approvals._EDIT_MESSAGE_LIMIT * 2)

    message = approvals.edit_interrupt_message(_proposal(new=new))

    assert "truncated" in message
    assert len(message) < len(new)
