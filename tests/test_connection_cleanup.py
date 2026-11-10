"""MIT License

Copyright (c) 2024-2025 gunyu1019

Connection cleanup tests for the official chzzkpy package: what is left of a client
session or a user session after its connection ends by itself (the server closes it or
reading fails), when that races with `disconnect()`, and when a connected user client
connects again. Tests of what remains after a connection ended connect with
`reconnect=False`; reconnecting is tested in `test_reconnect.py`.

The mock Chzzk server and fixtures are shared with `test_multi_account.py`.
"""

import asyncio

import aiohttp
import pytest

from chzzkpy import UserPermission
from chzzkpy.error import ReceiveErrorPacket
from chzzkpy.gateway import ChzzkGateway

from test_multi_account import (  # noqa: F401
    chat_payload,
    client,
    events,
    monitor,
    server,
    wait_until,
)


@pytest.fixture
def session_closes(monkeypatch) -> list[aiohttp.ClientSession]:
    """Records the session of every `aiohttp.ClientSession.close` call.

    Closing takes a moment, so a session is seen open by whoever doesn't wait for it.
    """
    closes = []
    original_close = aiohttp.ClientSession.close

    async def close(self):
        closes.append(self)
        await asyncio.sleep(0.05)
        await original_close(self)

    monkeypatch.setattr(aiohttp.ClientSession, "close", close)
    return closes


async def wait_ended(gateway: ChzzkGateway):
    """Waits until the read task of `gateway` has finished and its done callbacks ran."""
    done, _ = await asyncio.wait({gateway._read_background_loop}, timeout=2.0)
    assert done, "the connection did not end"


async def returned(blocking_connect: asyncio.Future, timeout: float = 3.0):
    """Returns the result of a blocking `connect()` once it returns.

    `asyncio.wait_for` can't be used: on timeout it cancels the blocking `connect()`,
    which closes the connection and makes `connect()` return as if it was released.
    """
    done, _ = await asyncio.wait({blocking_connect}, timeout=timeout)
    assert done, "the blocking connect() is still waiting"
    return blocking_connect.result()


def hide_subscribed_events(monkeypatch, server):
    original_push = server.push

    async def push(session, event, data):
        if event == "SYSTEM" and data["type"] == "subscribed":
            return
        await original_push(session, event, data)

    monkeypatch.setattr(server, "push", push)


def notify_subscribed(monkeypatch, user_client) -> asyncio.Event:
    """Returns an event that is set whenever `user_client.subscribe()` has returned."""
    subscribed = asyncio.Event()
    original_subscribe = user_client.subscribe

    async def subscribe(*args, **kwargs):
        await original_subscribe(*args, **kwargs)
        subscribed.set()

    monkeypatch.setattr(user_client, "subscribe", subscribe)
    return subscribed


def fail_reads(monkeypatch, gateway: ChzzkGateway):
    """Makes the following reads of `gateway` raise a read error."""

    async def failing_read():
        raise ReceiveErrorPacket("websocket", "broken")

    monkeypatch.setattr(gateway, "_read_loop", failing_read)


RACES = ["drop_and_disconnect", "disconnect_and_drop", "disconnect_after_drop"]


async def race_drop_with_disconnect(race, server, mock_session, gateway, disconnect):
    if race == "drop_and_disconnect":
        await asyncio.gather(server.drop(mock_session), disconnect())
    elif race == "disconnect_and_drop":
        await asyncio.gather(disconnect(), server.drop(mock_session))
    else:
        await server.drop(mock_session)
        await wait_ended(gateway)
        await disconnect()


@pytest.mark.asyncio
class TestClientSessionEnded:
    async def test_dropped_session_is_removed_and_closed(self, server, client):
        first = await client.connect(addition_connect=True, reconnect=False)
        second = await client.connect(addition_connect=True, reconnect=False)
        gateways = dict(client._gateway)

        await server.drop(server.sessions[first])
        await wait_ended(gateways[first])

        assert list(client._gateway) == [second]
        await wait_until(lambda: gateways[first].session.closed)
        assert not gateways[second].session.closed
        await asyncio.wait_for(client.wait_until_connect(), timeout=1.0)

        await server.drop(server.sessions[second])
        await wait_ended(gateways[second])

        assert client._gateway == {}
        await wait_until(lambda: gateways[second].session.closed)
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(client.wait_until_connect(), timeout=0.1)

    async def test_dropped_session_loses_its_ambiguous_mark(
        self, monkeypatch, server, client
    ):
        monkeypatch.setattr("chzzkpy.client._SUBSCRIBED_EVENT_TIMEOUT", 0.1)
        alice = await client.get_user_client(
            server.add_account("alice", profile_scope=False)
        )
        session_id = await client.connect(addition_connect=True)
        gateway = client._gateway[session_id]
        hide_subscribed_events(monkeypatch, server)
        await alice.subscribe(UserPermission(chat=True), session_id)
        assert session_id in client._ambiguous_sessions

        await server.drop(server.sessions[session_id])
        await wait_ended(gateway)

        assert session_id not in client._gateway
        assert session_id not in client._ambiguous_sessions

    async def test_connect_succeeds_after_ten_drops(self, server, client):
        for _ in range(10):
            session_id = await client.connect(addition_connect=True, reconnect=False)
            gateway = client._gateway[session_id]
            await server.drop(server.sessions[session_id])
            await wait_ended(gateway)

        session_id = await asyncio.wait_for(
            client.connect(addition_connect=True), timeout=3.0
        )

        assert list(client._gateway) == [session_id]

    async def test_blocking_connect_returns_after_drop(
        self, server, client, session_closes
    ):
        blocking_connect = asyncio.ensure_future(client.connect(reconnect=False))
        await wait_until(lambda: len(client._gateway) == 1)
        session_id, gateway = next(iter(client._gateway.items()))

        await server.drop(server.sessions[session_id])

        assert await returned(blocking_connect) == session_id
        assert client._gateway == {}
        assert not client._gateway_ready.is_set()
        # The connection is closed by the time connect() returns.
        assert session_closes.count(gateway.session) == 1
        assert gateway.session.closed

    async def test_read_error_ends_blocking_connect_and_cleans_up(
        self, monkeypatch, server, client
    ):
        blocking_connect = asyncio.ensure_future(client.connect(reconnect=False))
        await wait_until(lambda: len(client._gateway) == 1)
        session_id, gateway = next(iter(client._gateway.items()))

        fail_reads(monkeypatch, gateway)
        # Ends the read in progress, so the next one fails.
        await server.push(
            server.sessions[session_id], "CHAT", chat_payload("channel-alice", "hi")
        )

        with pytest.raises(ReceiveErrorPacket):
            await returned(blocking_connect)
        assert client._gateway == {}
        assert gateway.session.closed

    @pytest.mark.parametrize("race", RACES)
    async def test_disconnect_racing_with_drop_closes_once(
        self, race, server, client, session_closes
    ):
        session_id = await client.connect(addition_connect=True)
        gateway = client._gateway[session_id]

        await race_drop_with_disconnect(
            race,
            server,
            server.sessions[session_id],
            gateway,
            lambda: client.disconnect(session_id),
        )

        assert client._gateway == {}
        assert not client._gateway_ready.is_set()
        assert gateway.session.closed
        await asyncio.sleep(0.05)
        assert session_closes.count(gateway.session) == 1


@pytest.mark.asyncio
class TestUserSessionEnded:
    async def test_dropped_session_resets_user_client(self, server, client, events):
        alice = await client.get_user_client(server.add_account("alice"))
        await alice.connect(
            UserPermission(chat=True), addition_connect=True, reconnect=False
        )
        gateway = alice._gateway
        dropped = server.session_of("alice")

        await server.drop(dropped)
        await wait_ended(gateway)

        assert alice._gateway is None
        assert alice._gateway_id is None
        assert alice._session_id is None
        assert not alice._gateway_ready.is_set()
        assert not alice.is_connected
        await wait_until(lambda: gateway.session.closed)

        session_id = await alice.connect(
            UserPermission(chat=True), addition_connect=True
        )
        assert session_id == server.session_of("alice").key != dropped.key
        assert alice.is_connected
        await server.push(
            server.session_of("alice"), "CHAT", chat_payload("channel-alice", "again")
        )
        assert (await events.next("chat")).content == "again"

    async def test_blocking_connect_returns_after_drop(
        self, monkeypatch, server, client, session_closes
    ):
        alice = await client.get_user_client(server.add_account("alice"))
        subscribed = notify_subscribed(monkeypatch, alice)
        blocking_connect = asyncio.ensure_future(
            alice.connect(UserPermission(chat=True), reconnect=False)
        )
        await asyncio.wait_for(subscribed.wait(), timeout=2.0)
        gateway = alice._gateway

        await server.drop(server.session_of("alice"))

        assert await returned(blocking_connect) == server.session_of("alice").key
        assert alice._gateway is None and not alice.is_connected
        # The connection is closed by the time connect() returns.
        assert session_closes.count(gateway.session) == 1
        assert gateway.session.closed

    async def test_connect_while_connected_closes_previous_connection(
        self, server, client, events, session_closes
    ):
        alice = await client.get_user_client(server.add_account("alice"))
        await alice.connect(UserPermission(chat=True), addition_connect=True)
        previous_gateway = alice._gateway
        previous = server.session_of("alice")

        session_id = await alice.connect(
            UserPermission(chat=True), addition_connect=True
        )

        assert not previous_gateway.is_connected
        assert previous_gateway.session.closed
        await wait_until(lambda: previous.ws.closed)
        current = server.session_of("alice")
        assert session_id == current.key != previous.key
        assert alice._gateway is not previous_gateway and alice.is_connected

        await server.push(current, "CHAT", chat_payload("channel-alice", "new"))
        assert (await events.next("chat")).content == "new"
        assert alice.is_connected
        assert session_closes.count(previous_gateway.session) == 1

    async def test_connect_while_connected_releases_blocking_connect(
        self, monkeypatch, server, client
    ):
        alice = await client.get_user_client(server.add_account("alice"))
        subscribed = notify_subscribed(monkeypatch, alice)
        blocking_connect = asyncio.ensure_future(
            alice.connect(UserPermission(chat=True))
        )
        await asyncio.wait_for(subscribed.wait(), timeout=2.0)
        previous_key = alice._session_id

        await alice.connect(UserPermission(chat=True), addition_connect=True)

        assert await returned(blocking_connect) == previous_key
        assert alice.is_connected
        assert alice._session_id == server.session_of("alice").key != previous_key

    async def test_concurrent_connects_leave_one_connection(
        self, server, client, monitor
    ):
        alice = await client.get_user_client(server.add_account("alice"))

        session_ids = await asyncio.wait_for(
            asyncio.gather(
                *(
                    alice.connect(UserPermission(chat=True), addition_connect=True)
                    for _ in range(2)
                )
            ),
            timeout=3.0,
        )

        assert alice.is_connected
        assert alice._session_id == session_ids[-1]
        previous = [g for g in monitor.gateways if g is not alice._gateway]
        assert len(previous) == 1
        assert not previous[0].is_connected and previous[0].session.closed

    @pytest.mark.parametrize("race", RACES)
    async def test_disconnect_racing_with_drop_closes_once(
        self, race, server, client, session_closes
    ):
        alice = await client.get_user_client(server.add_account("alice"))
        await alice.connect(UserPermission(chat=True), addition_connect=True)
        gateway = alice._gateway

        await race_drop_with_disconnect(
            race, server, server.session_of("alice"), gateway, alice.disconnect
        )

        assert alice._gateway is None and not alice.is_connected
        assert gateway.session.closed
        await asyncio.sleep(0.05)
        assert session_closes.count(gateway.session) == 1
