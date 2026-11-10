"""MIT License

Copyright (c) 2024-2025 gunyu1019

Session handling tests for the official chzzkpy package: session keys and readiness of
client sessions, cleanup of failed or disconnected connections, and how a user client
without the "유저 정보 조회" scope learns its channel ID on a client session.

The mock Chzzk server and fixtures are shared with `test_multi_account.py`.
"""

import asyncio
import logging

import pytest

from chzzkpy import UserPermission
from chzzkpy.error import ChatConnectFailed, ReceiveErrorPacket
from chzzkpy.gateway import ChzzkGateway

from test_multi_account import client, monitor, server, wait_until  # noqa: F401


def delay_subscribed_events(server, delay: float, before=()) -> list[asyncio.Task]:
    """Push "subscribed" SYSTEM events `delay` seconds after the subscription request,
    preceded by the SYSTEM events in `before`."""
    original_push = server.push
    tasks = []

    async def push(session, event, data):
        if event != "SYSTEM" or data["type"] != "subscribed":
            await original_push(session, event, data)
            return

        async def push_later():
            await asyncio.sleep(delay)
            for extra in before:
                await original_push(session, "SYSTEM", extra)
            await original_push(session, event, data)

        tasks.append(asyncio.ensure_future(push_later()))

    server.push = push
    return tasks


class RecordingHandler(logging.Handler):
    def __init__(self):
        super().__init__(logging.WARNING)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord):
        self.records.append(record)


@pytest.mark.asyncio
class TestClientSession:
    async def test_concurrent_connects_keep_their_own_session(self, server, client):
        session_ids = await asyncio.wait_for(
            asyncio.gather(*(client.connect(addition_connect=True) for _ in range(3))),
            timeout=3.0,
        )

        assert len(set(session_ids)) == 3
        for session_id in session_ids:
            assert (
                client._gateway[session_id].session_id
                == server.sessions[session_id].sid
            )

    async def test_wait_until_connect_follows_client_sessions(self, client):
        waiter = asyncio.ensure_future(client.wait_until_connect())
        await asyncio.sleep(0.05)
        assert not waiter.done()

        session_id = await client.connect(addition_connect=True)
        await asyncio.wait_for(waiter, timeout=1.0)
        await asyncio.wait_for(client.wait_until_connect(), timeout=1.0)

        await client.disconnect(session_id)
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(client.wait_until_connect(), timeout=0.1)

    async def test_disconnect_closes_connection_sessions(self, client):
        first = await client.connect(addition_connect=True)
        second = await client.connect(addition_connect=True)
        gateways = dict(client._gateway)

        await client.disconnect(first)
        assert gateways[first].session.closed
        assert not gateways[second].session.closed
        assert list(client._gateway) == [second]

        await client.disconnect()
        assert gateways[second].session.closed
        assert client._gateway == {}

    async def test_failed_connect_chains_read_error_and_cleans_up(
        self, monkeypatch, client, monitor
    ):
        async def failing_read(gateway):
            raise ReceiveErrorPacket("websocket", "broken")

        monkeypatch.setattr(ChzzkGateway, "_read_websocket", failing_read)

        with pytest.raises(ChatConnectFailed) as exc_info:
            await asyncio.wait_for(client.connect(addition_connect=True), timeout=3.0)

        assert isinstance(exc_info.value.__cause__, ReceiveErrorPacket)
        assert client._gateway == {}
        assert monitor.gateways[-1].session.closed


@pytest.mark.asyncio
class TestUserSession:
    async def test_disconnect_closes_connection_session(self, server, client):
        alice = await client.get_user_client(server.add_account("alice"))
        await alice.connect(UserPermission(chat=True), addition_connect=True)
        gateway = alice._gateway

        await alice.disconnect()

        assert gateway.session.closed

    async def test_failed_connect_cleans_up(self, server, client, monitor):
        server.close_before_ready.add("alice")
        alice = await client.get_user_client(server.add_account("alice"))

        with pytest.raises(ChatConnectFailed):
            await asyncio.wait_for(
                alice.connect(UserPermission(chat=True), addition_connect=True),
                timeout=3.0,
            )

        assert monitor.gateways[-1].session.closed
        assert alice._gateway is None and alice._session_id is None
        assert not alice.is_connected


@pytest.mark.asyncio
class TestChannelIdOnClientSession:
    async def test_learned_when_subscribing_from_on_connect(self, server, client):
        alice = await client.get_user_client(
            server.add_account("alice", profile_scope=False)
        )

        @client.event
        async def on_connect(session_id):
            await alice.subscribe(UserPermission(chat=True), session_id)

        # The event arrives after the subscription response, so the subscription waits for it.
        delay_subscribed_events(server, 0.1)
        blocking_connect = asyncio.ensure_future(client.connect())

        await wait_until(lambda: alice.channel_id is not None)
        assert alice.channel_id == "channel-alice"
        await client.disconnect()
        await asyncio.wait_for(blocking_connect, timeout=3.0)

    async def test_other_accounts_system_events_are_not_taken(self, server, client):
        alice = await client.get_user_client(
            server.add_account("alice", profile_scope=False)
        )
        bob = await client.get_user_client(server.add_account("bob"))
        session_id = await client.connect(addition_connect=True)

        mallory = {"eventType": "CHAT", "channelId": "channel-mallory"}
        delay_subscribed_events(
            server,
            0.1,
            before=[
                {"type": "revoked", "data": mallory},
                {"type": "unsubscribed", "data": mallory},
                {
                    "type": "subscribed",
                    "data": {"eventType": "CHAT", "channelId": "channel-bob"},
                },
            ],
        )
        await alice.subscribe(UserPermission(chat=True), session_id)

        assert alice.channel_id == "channel-alice"
        assert bob.channel_id == "channel-bob"

    async def test_late_event_is_not_given_to_the_next_account(
        self, monkeypatch, server, client
    ):
        monkeypatch.setattr("chzzkpy.client._SUBSCRIBED_EVENT_TIMEOUT", 0.2)
        handler = RecordingHandler()
        logger = logging.getLogger("chzzkpy.client")
        logger.addHandler(handler)

        try:
            alice = await client.get_user_client(
                server.add_account("alice", profile_scope=False)
            )
            carol = await client.get_user_client(
                server.add_account("carol", profile_scope=False)
            )
            session_id = await client.connect(addition_connect=True)
            pushes = delay_subscribed_events(server, 0.3)

            await alice.subscribe(UserPermission(chat=True), session_id)
            assert alice.channel_id is None
            assert len(handler.records) == 1

            # alice's event arrives while carol's subscription would be waiting.
            await carol.subscribe(UserPermission(chat=True), session_id)
            await asyncio.wait_for(asyncio.gather(*pushes), timeout=2.0)
            await asyncio.sleep(0.05)

            assert carol.channel_id is None
            assert alice.channel_id is None
        finally:
            logger.removeHandler(handler)
