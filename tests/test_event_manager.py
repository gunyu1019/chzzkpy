"""MIT License

Copyright (c) 2024-2025 gunyu1019

Unit tests for chzzkpy.client.BaseEventManager.
Tests wait_for listener bookkeeping and event handler registration.
"""

import asyncio

import pytest

from chzzkpy.client import BaseEventManager


def create_event_manager() -> BaseEventManager:
    return BaseEventManager(asyncio.get_running_loop())


async def run_scheduled_events():
    """Let event handler tasks scheduled by dispatch run to completion."""
    for _ in range(3):
        await asyncio.sleep(0)


@pytest.mark.asyncio
class TestWaitFor:
    """Test wait_for listeners handled by dispatch."""

    async def test_dispatch_after_resolved_wait_for(self):
        """Dispatching again after a wait_for resolved must not raise."""
        manager = create_event_manager()
        received = []

        @manager.event
        async def on_chat(message):
            received.append(message)

        waiter = manager.wait_for("chat")
        manager.dispatch("chat", "first")
        assert await waiter == "first"

        manager.dispatch("chat", "second")
        manager.dispatch("chat", "third")
        await run_scheduled_events()

        assert received == ["first", "second", "third"]
        assert manager._listeners["chat"] == []

    async def test_each_waiter_resolves_once(self):
        """A waiter registered after another resolved gets the next event."""
        manager = create_event_manager()

        first = asyncio.ensure_future(manager.wait_for("chat"))
        manager.dispatch("chat", "first")
        second = asyncio.ensure_future(manager.wait_for("chat"))
        manager.dispatch("chat", "second")

        assert await first == "first"
        assert await second == "second"
        assert manager._listeners["chat"] == []

    async def test_check_filters_events(self):
        """Non-matching events keep the listener; a matching one resolves it."""
        manager = create_event_manager()

        waiter = asyncio.ensure_future(
            manager.wait_for("chat", check=lambda message: message == "target")
        )
        manager.dispatch("chat", "other")
        await asyncio.sleep(0)

        assert not waiter.done()
        assert len(manager._listeners["chat"]) == 1

        manager.dispatch("chat", "target")
        assert await waiter == "target"
        assert manager._listeners["chat"] == []

    async def test_raising_check_fails_only_that_waiter(self):
        """An exception from check is delivered to its waiter, not to dispatch."""
        manager = create_event_manager()

        def broken_check(_):
            raise ValueError("broken check")

        failing = asyncio.ensure_future(manager.wait_for("chat", check=broken_check))
        other = asyncio.ensure_future(manager.wait_for("chat"))
        manager.dispatch("chat", "message")

        with pytest.raises(ValueError, match="broken check"):
            await failing
        assert await other == "message"
        assert manager._listeners["chat"] == []

        # The failed listener is gone, so later dispatches do not touch it.
        manager.dispatch("chat", "after")

    async def test_timed_out_wait_for_is_cleaned_up(self):
        """A timed out waiter is dropped and does not affect later dispatches."""
        manager = create_event_manager()

        with pytest.raises(asyncio.TimeoutError):
            await manager.wait_for("chat", timeout=0.01)

        waiter = asyncio.ensure_future(manager.wait_for("chat"))
        manager.dispatch("chat", "message")

        assert await waiter == "message"
        assert manager._listeners["chat"] == []

    async def test_cancelled_wait_for_is_cleaned_up(self):
        """A cancelled waiter is dropped on the next dispatch."""
        manager = create_event_manager()

        waiter = asyncio.ensure_future(manager.wait_for("chat"))
        await asyncio.sleep(0)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter

        manager.dispatch("chat", "message")
        assert manager._listeners["chat"] == []

    async def test_result_depends_on_argument_count(self):
        """No argument resolves None, one the argument and more a tuple."""
        manager = create_event_manager()

        no_argument = asyncio.ensure_future(manager.wait_for("connect"))
        one_argument = asyncio.ensure_future(manager.wait_for("chat"))
        many_arguments = asyncio.ensure_future(manager.wait_for("donation"))

        manager.dispatch("connect")
        manager.dispatch("chat", "message")
        manager.dispatch("donation", "donation", "token")

        assert await no_argument is None
        assert await one_argument == "message"
        assert await many_arguments == ("donation", "token")

    async def test_event_name_is_case_insensitive(self):
        """wait_for lowercases the event name before registering it."""
        manager = create_event_manager()

        waiter = asyncio.ensure_future(manager.wait_for("CHAT"))
        manager.dispatch("chat", "message")

        assert await waiter == "message"


@pytest.mark.asyncio
class TestEventHandler:
    """Test event handlers registered with the event decorator."""

    async def test_handlers_with_same_name_all_run(self):
        """Registering a second handler keeps the first one."""
        manager = create_event_manager()
        received = []

        @manager.event
        async def on_chat(message):
            received.append(("first", message))

        @manager.event
        async def on_chat(message):  # noqa: F811
            received.append(("second", message))

        manager.dispatch("chat", "message")
        await run_scheduled_events()

        assert sorted(received) == [("first", "message"), ("second", "message")]

    async def test_handler_registered_after_wait_for_runs(self):
        """A pending wait_for does not affect handler registration."""
        manager = create_event_manager()
        received = []

        waiter = asyncio.ensure_future(manager.wait_for("chat"))

        @manager.event
        async def on_chat(message):
            received.append(message)

        manager.dispatch("chat", "message")
        await run_scheduled_events()

        assert await waiter == "message"
        assert received == ["message"]

    async def test_non_coroutine_handler_is_rejected(self):
        """The event decorator only accepts coroutine functions."""
        manager = create_event_manager()

        def on_chat(_):
            pass

        with pytest.raises(TypeError):
            manager.event(on_chat)
