"""MIT License

Copyright (c) 2024-2025 gunyu1019

Client session limit tests for the official chzzkpy package: `Client.connect()` allows
at most 10 client sessions, and connections that are still being established count
toward that limit, so concurrent calls can't go over it.

The mock Chzzk server and fixtures are shared with `test_multi_account.py`.
"""

import asyncio
import importlib
from typing import Optional

import pytest

from chzzkpy.error import ChatConnectFailed

from test_multi_account import client, monitor, server, wait_until  # noqa: F401

STAGES = ["session_request", "gateway_connect", "handshake"]
# What a connect() held at the stage raises once the hold is released with an error.
STAGE_ERRORS = {
    "session_request": RuntimeError,
    "gateway_connect": RuntimeError,
    "handshake": ChatConnectFailed,
}


class Hold:
    """Holds the connect() calls that reach one stage of connecting until `release()`."""

    def __init__(self):
        self.arrived = 0
        self.released = False
        self._waiters: list[asyncio.Future] = []

    async def reach(self):
        self.arrived += 1
        if self.released:
            return
        waiter = asyncio.get_running_loop().create_future()
        self._waiters.append(waiter)
        await waiter

    def release(self, error: Optional[Exception] = None):
        """Lets the held calls go on, or fail with `error`. Later calls aren't held."""
        self.released = True
        for waiter in self._waiters:
            if waiter.done():  # the call was cancelled
                continue
            if error is None:
                waiter.set_result(None)
            else:
                waiter.set_exception(error)
        self._waiters.clear()


@pytest.fixture
def hold(monkeypatch, server, client):
    """Returns a function that makes every connect() wait at the given stage."""
    holds = []

    def install(stage: str) -> Hold:
        instance = Hold()
        holds.append(instance)

        if stage == "session_request":
            original = client.http.generate_client_session

            async def generate_client_session(*args, **kwargs):
                await instance.reach()
                return await original(*args, **kwargs)

            monkeypatch.setattr(
                client.http, "generate_client_session", generate_client_session
            )
        elif stage == "gateway_connect":
            original = importlib.import_module("chzzkpy.client")._connect_gateway

            async def connect_gateway(*args, **kwargs):
                await instance.reach()
                return await original(*args, **kwargs)

            monkeypatch.setattr("chzzkpy.client._connect_gateway", connect_gateway)
        else:
            original = server.push

            async def push(session, event, data):
                if event == "SYSTEM" and data["type"] == "connected":
                    try:
                        await instance.reach()
                    except Exception:
                        await session.ws.close()
                        return
                    if session.ws.closed:
                        return
                await original(session, event, data)

            monkeypatch.setattr(server, "push", push)
        return instance

    yield install

    for instance in holds:
        instance.release()


async def connect_sessions(client, count: int) -> list[str]:
    return [await client.connect(addition_connect=True) for _ in range(count)]


def is_max_connection(error: BaseException) -> bool:
    return isinstance(error, ChatConnectFailed) and str(error) == str(
        ChatConnectFailed.max_connection()
    )


async def assert_rejected(client):
    """Asserts that connect() is refused at once, without waiting for any connection."""
    with pytest.raises(ChatConnectFailed) as raised:
        await asyncio.wait_for(client.connect(addition_connect=True), timeout=1.0)
    assert is_max_connection(raised.value)


async def assert_full(client):
    """Asserts that exactly 10 client sessions are connected and no more are allowed."""
    assert len(client._gateway) == 10
    await assert_rejected(client)
    assert len(client._gateway) == 10


async def assert_has_room_for(client, count: int):
    """Asserts that `count` more sessions connect, and the next one is refused."""
    await connect_sessions(client, count)
    await assert_full(client)


@pytest.mark.asyncio
class TestConcurrentConnects:
    async def test_two_concurrent_connects_with_nine_sessions(self, server, client):
        await connect_sessions(client, 9)

        results = await asyncio.gather(
            client.connect(addition_connect=True),
            client.connect(addition_connect=True),
            return_exceptions=True,
        )

        succeeded = [r for r in results if isinstance(r, str)]
        failed = [r for r in results if isinstance(r, BaseException)]
        assert len(succeeded) == 1
        assert len(failed) == 1 and is_max_connection(failed[0])
        assert len(client._gateway) == 10
        # The refused connect() didn't ask for a session.
        assert len(server.sessions) == 10
        await assert_full(client)

    async def test_twelve_concurrent_connects_open_ten_sessions(self, server, client):
        results = await asyncio.gather(
            *(client.connect(addition_connect=True) for _ in range(12)),
            return_exceptions=True,
        )

        succeeded = [r for r in results if isinstance(r, str)]
        failed = [r for r in results if isinstance(r, BaseException)]
        assert len(succeeded) == 10
        assert len(failed) == 2 and all(is_max_connection(r) for r in failed)
        assert sorted(client._gateway) == sorted(succeeded)
        assert len(server.sessions) == 10
        await assert_full(client)

    @pytest.mark.parametrize("registered", [1, 5, 9])
    async def test_concurrent_connects_fill_the_rest(self, server, client, registered):
        await connect_sessions(client, registered)

        results = await asyncio.gather(
            *(client.connect(addition_connect=True) for _ in range(12)),
            return_exceptions=True,
        )

        succeeded = [r for r in results if isinstance(r, str)]
        failed = [r for r in results if isinstance(r, BaseException)]
        assert len(succeeded) == 10 - registered
        assert all(is_max_connection(r) for r in failed)
        assert len(succeeded) + len(failed) == 12
        await assert_full(client)

    @pytest.mark.parametrize("stage", STAGES)
    async def test_connect_in_flight_counts_toward_the_limit(
        self, server, client, hold, stage
    ):
        await connect_sessions(client, 9)
        held = hold(stage)
        pending = asyncio.ensure_future(client.connect(addition_connect=True))
        await wait_until(lambda: held.arrived == 1)

        await assert_rejected(client)
        assert held.arrived == 1

        held.release()
        assert isinstance(await asyncio.wait_for(pending, timeout=3.0), str)
        await assert_full(client)

    async def test_blocking_connects_hold_a_slot_only_until_ready(self, server, client):
        blocking = [asyncio.ensure_future(client.connect()) for _ in range(9)]
        await wait_until(lambda: len(client._gateway) == 9)

        # Nine connections are waiting for responses, but only nine slots are taken.
        await connect_sessions(client, 1)
        await assert_full(client)

        await client.disconnect()
        done, pending = await asyncio.wait(blocking, timeout=3.0)
        assert not pending
        assert all(isinstance(task.result(), str) for task in done)
        await assert_has_room_for(client, 10)


@pytest.mark.asyncio
class TestSlotRelease:
    @pytest.mark.parametrize("stage", STAGES)
    async def test_failed_connect_frees_its_slot(self, server, client, hold, stage):
        await connect_sessions(client, 9)
        held = hold(stage)
        pending = asyncio.ensure_future(client.connect(addition_connect=True))
        await wait_until(lambda: held.arrived == 1)
        await assert_rejected(client)

        held.release(RuntimeError("failed"))
        with pytest.raises(STAGE_ERRORS[stage]):
            await asyncio.wait_for(pending, timeout=3.0)

        assert len(client._gateway) == 9
        await assert_has_room_for(client, 1)

    @pytest.mark.parametrize("stage", STAGES)
    async def test_cancelled_connect_frees_its_slot(self, server, client, hold, stage):
        await connect_sessions(client, 9)
        held = hold(stage)
        pending = asyncio.ensure_future(client.connect(addition_connect=True))
        await wait_until(lambda: held.arrived == 1)
        await assert_rejected(client)

        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending

        held.release()
        assert len(client._gateway) == 9
        await assert_has_room_for(client, 1)

    async def test_connect_cancelled_by_timeout_frees_its_slot(
        self, server, client, hold
    ):
        await connect_sessions(client, 9)
        held = hold("handshake")
        timed = asyncio.ensure_future(
            asyncio.wait_for(client.connect(addition_connect=True), timeout=0.3)
        )
        await wait_until(lambda: held.arrived == 1)
        await assert_rejected(client)

        with pytest.raises(asyncio.TimeoutError):
            await timed

        held.release()
        assert len(client._gateway) == 9
        await assert_has_room_for(client, 1)

    @pytest.mark.parametrize("stage", STAGES)
    async def test_failed_connects_free_all_their_slots(
        self, server, client, hold, stage
    ):
        held = hold(stage)
        tasks = [
            asyncio.ensure_future(client.connect(addition_connect=True))
            for _ in range(12)
        ]
        await wait_until(
            lambda: held.arrived + sum(task.done() for task in tasks) >= 12
        )
        assert held.arrived == 10
        assert all(is_max_connection(task.exception()) for task in tasks if task.done())

        held.release(RuntimeError("failed"))
        results = await asyncio.gather(*tasks, return_exceptions=True)

        assert all(isinstance(r, BaseException) for r in results)
        assert client._gateway == {}
        await assert_has_room_for(client, 10)

    async def test_disconnect_frees_slots(self, server, client):
        session_ids = await connect_sessions(client, 10)
        await assert_full(client)

        await client.disconnect(session_ids[3])
        assert len(client._gateway) == 9
        await assert_has_room_for(client, 1)

        await client.disconnect()
        assert client._gateway == {}
        await assert_has_room_for(client, 10)

    async def test_session_ended_by_itself_frees_a_slot(self, server, client):
        await connect_sessions(client, 10)
        await assert_full(client)

        await server.drop(server.session_of(None))
        await wait_until(lambda: len(client._gateway) == 9)

        await assert_has_room_for(client, 1)

    async def test_ended_session_frees_one_slot_while_connect_in_flight(
        self, server, client, hold
    ):
        session_ids = await connect_sessions(client, 9)
        held = hold("handshake")
        first = asyncio.ensure_future(client.connect(addition_connect=True))
        await wait_until(lambda: held.arrived == 1)
        await assert_rejected(client)

        await server.drop(server.sessions[session_ids[0]])
        await wait_until(lambda: len(client._gateway) == 8)

        # 8 connected and 1 in flight leaves exactly one slot.
        second = asyncio.ensure_future(client.connect(addition_connect=True))
        await wait_until(lambda: held.arrived == 2)
        await assert_rejected(client)

        held.release()
        assert isinstance(await asyncio.wait_for(first, timeout=3.0), str)
        assert isinstance(await asyncio.wait_for(second, timeout=3.0), str)
        await assert_full(client)
