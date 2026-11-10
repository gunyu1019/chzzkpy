"""MIT License

Copyright (c) 2024-2025 gunyu1019

Subscription tests for the official chzzkpy package: `UserClient.subscribe()` skips the
events a user client has already subscribed on a session, so an `on_connect` handler that
subscribes and the subscriptions restored after reconnecting send one request per event,
whichever comes first. Also covers `UserClient.connect()` closing its connection when
subscribing to its permission fails.

The mock Chzzk server and fixtures are shared with `test_multi_account.py`, and the
reconnection helpers with `test_reconnect.py`.
"""

import asyncio
from collections import Counter

import pytest

from chzzkpy import UserPermission
from chzzkpy.error import ForbiddenException, HTTPException, NotFoundException

from test_multi_account import client, monitor, server, wait_until  # noqa: F401
from test_reconnect import (  # noqa: F401
    INITIAL_DELAY,
    MAX_DELAY,
    SETTLE,
    SUBSCRIBE_PATH,
    Hold,
    alice,
    assert_disconnected,
    assert_nothing_open,
    connections,
    hold,
    reconnected_client,
    reconnected_user,
    session_events,
)

KINDS = ["user", "client"]
CHAT = ("chat", "token-alice")
DONATION = ("donation", "token-alice")
ON_CONNECT_TASK = "chzzk.py: on_connect"


@pytest.fixture(autouse=True)
def fast_reconnect(monkeypatch):
    monkeypatch.setattr("chzzkpy.client._RECONNECT_INITIAL_DELAY", INITIAL_DELAY)
    monkeypatch.setattr("chzzkpy.client._RECONNECT_MAX_DELAY", MAX_DELAY)


def subscribe_requests(server, session_key: str) -> Counter:
    """How many times each (event, token) was requested to be subscribed on `session_key`."""
    return Counter(
        (r["path"].rsplit("/", 1)[1], r["token"])
        for r in server.requests_to(SUBSCRIBE_PATH)
        if r["query"]["sessionKey"] == session_key
    )


async def start(kind: str, client, alice, permission: UserPermission) -> str:
    """Connects a user session of alice, or a client session alice subscribes on."""
    if kind == "user":
        return await alice.connect(permission, addition_connect=True)
    session_id = await client.connect(addition_connect=True)
    await alice.subscribe(permission, session_id)
    return session_id


@pytest.mark.asyncio
class TestSubscribeOnce:
    @pytest.mark.parametrize("kind", KINDS)
    async def test_subscribing_again_sends_no_request(
        self, kind, server, client, alice
    ):
        key = await start(kind, client, alice, UserPermission(chat=True))

        await alice.subscribe(UserPermission(chat=True), key)
        await alice.subscribe(UserPermission(chat=True, donation=True), key)

        assert subscribe_requests(server, key) == Counter({CHAT: 1, DONATION: 1})

    @pytest.mark.parametrize("kind", KINDS)
    async def test_subscribing_after_unsubscribe_sends_again(
        self, kind, server, client, alice
    ):
        key = await start(kind, client, alice, UserPermission(chat=True))

        await alice.unsubscribe(UserPermission(chat=True), key)
        await alice.subscribe(UserPermission(chat=True), key)

        assert subscribe_requests(server, key) == Counter({CHAT: 2})
        assert server.sessions[key].subscriptions == [("chat", "channel-alice")]

    @pytest.mark.parametrize("kind", KINDS)
    async def test_concurrent_subscribes_send_one_request(
        self, kind, server, client, alice
    ):
        key = await start(kind, client, alice, UserPermission(subscription=True))

        await asyncio.gather(
            alice.subscribe(UserPermission(chat=True), key),
            alice.subscribe(UserPermission(chat=True), key),
            alice.subscribe(UserPermission(chat=True, donation=True), key),
        )

        assert subscribe_requests(server, key) == Counter(
            {CHAT: 1, DONATION: 1, ("subscription", "token-alice"): 1}
        )

    @pytest.mark.parametrize("kind", KINDS)
    async def test_waiting_subscribe_requests_again_when_the_first_fails(
        self, monkeypatch, kind, server, client, alice, hold
    ):
        key = await start(kind, client, alice, UserPermission(donation=True))
        original = client.http.subcribe_event
        calls = []

        async def subcribe_event(*args, **kwargs):
            calls.append(kwargs["event"])
            if len(calls) == 1:
                await hold.reach()
                raise HTTPException(500, "SUBSCRIBE_ERROR")
            return await original(*args, **kwargs)

        monkeypatch.setattr(client.http, "subcribe_event", subcribe_event)
        first = asyncio.ensure_future(alice.subscribe(UserPermission(chat=True), key))
        await wait_until(lambda: hold.arrived == 1)
        second = asyncio.ensure_future(alice.subscribe(UserPermission(chat=True), key))
        await asyncio.sleep(0.05)
        # It waits for the request in flight instead of sending another one.
        assert not second.done() and calls == ["chat"]

        hold.release()

        with pytest.raises(HTTPException):
            await asyncio.wait_for(first, timeout=1.0)
        await asyncio.wait_for(second, timeout=1.0)
        assert calls == ["chat", "chat"]
        assert subscribe_requests(server, key)[CHAT] == 1
        await alice.subscribe(UserPermission(chat=True), key)
        assert calls == ["chat", "chat"]


@pytest.mark.asyncio
class TestRestoreAfterReconnect:
    @pytest.mark.parametrize("kind", KINDS)
    async def test_new_session_is_subscribed_again(self, kind, server, client, alice):
        first_key = await start(
            kind, client, alice, UserPermission(chat=True, donation=True)
        )
        await alice.subscribe(UserPermission(chat=True), first_key)

        await server.drop(server.sessions[first_key])
        if kind == "user":
            second_key = await reconnected_user(alice, first_key)
        else:
            second_key = await reconnected_client(client, first_key)

        assert subscribe_requests(server, second_key) == Counter({CHAT: 1, DONATION: 1})
        # Subscribing on the new session again sends nothing.
        await alice.subscribe(UserPermission(chat=True, donation=True), second_key)
        assert subscribe_requests(server, second_key) == Counter({CHAT: 1, DONATION: 1})

    async def test_late_request_on_the_old_session_keeps_the_new_one_tracked(
        self, monkeypatch, server, client, alice, hold
    ):
        first_key = await alice.connect(
            UserPermission(donation=True), addition_connect=True
        )
        original = client.http.subcribe_event

        async def subcribe_event(*args, **kwargs):
            if kwargs["session_key"] == first_key:
                await hold.reach()
                # The old session is gone by the time the request is answered.
                raise NotFoundException("UNKNOWN_SESSION")
            return await original(*args, **kwargs)

        monkeypatch.setattr(client.http, "subcribe_event", subcribe_event)
        on_old_session = [
            asyncio.ensure_future(alice.subscribe(UserPermission(chat=True)))
        ]
        await wait_until(lambda: hold.arrived == 1)
        # It waits for the request in flight on the old session.
        on_old_session.append(
            asyncio.ensure_future(alice.subscribe(UserPermission(chat=True), first_key))
        )

        await server.drop(server.sessions[first_key])
        second_key = await reconnected_user(alice, first_key)
        hold.release()
        await asyncio.wait_for(
            asyncio.gather(*on_old_session, return_exceptions=True), timeout=2.0
        )

        await alice.subscribe(UserPermission(donation=True), second_key)
        assert subscribe_requests(server, second_key) == Counter({DONATION: 1})

    @pytest.mark.parametrize(
        "kind, handler_key",
        [("user", "new"), ("client", "new"), ("client", "old")],
    )
    @pytest.mark.parametrize("order", ["handler_first", "restore_first"])
    async def test_on_connect_handler_and_restore_subscribe_once(
        self, monkeypatch, order, kind, handler_key, server, client, alice
    ):
        permission = UserPermission(chat=True, donation=True)
        first_key = await start(kind, client, alice, permission)
        # Set once the first of the two has begun to subscribe on the new session.
        began = asyncio.Event()
        handled = asyncio.Event()
        callers = []
        original_subscribe = client.http.subcribe_event

        async def subcribe_event(*args, **kwargs):
            if kwargs["session_key"] != first_key:
                task_name = asyncio.current_task().get_name()
                callers.append("handler" if task_name == ON_CONNECT_TASK else "restore")
                began.set()
            return await original_subscribe(*args, **kwargs)

        monkeypatch.setattr(client.http, "subcribe_event", subcribe_event)

        @client.event
        async def on_connect(session_id):
            if session_id == first_key:
                return
            if order == "restore_first":
                await began.wait()
            await alice.subscribe(
                permission, first_key if handler_key == "old" else session_id
            )
            handled.set()

        if order == "handler_first":
            # The restore starts once the handler has begun to subscribe.
            name = "_open_connection" if kind == "user" else "_open_client_session"
            target = alice if kind == "user" else client
            original_open = getattr(target, name)

            async def open_connection(*args, **kwargs):
                result = await original_open(*args, **kwargs)
                await began.wait()
                return result

            monkeypatch.setattr(target, name, open_connection)

        await server.drop(server.sessions[first_key])
        if kind == "user":
            second_key = await reconnected_user(alice, first_key)
        else:
            second_key = await reconnected_client(client, first_key)
        await asyncio.wait_for(handled.wait(), timeout=2.0)

        assert subscribe_requests(server, second_key) == Counter({CHAT: 1, DONATION: 1})
        expected = "handler" if order == "handler_first" else "restore"
        assert callers == [expected, expected]
        assert sorted(server.sessions[second_key].subscriptions) == [
            ("chat", "channel-alice"),
            ("donation", "channel-alice"),
        ]

    async def test_subscription_from_on_connect_of_the_first_session_is_restored(
        self, server, client, alice
    ):
        subscribed = asyncio.Event()

        @client.event
        async def on_connect(session_id):
            if not subscribed.is_set():
                await alice.subscribe(UserPermission(chat=True), session_id)
                subscribed.set()

        blocking_connect = asyncio.ensure_future(client.connect())
        await asyncio.wait_for(subscribed.wait(), timeout=2.0)
        first_key = server.session_of(None).key

        await server.drop(server.sessions[first_key])
        second_key = await reconnected_client(client, first_key)

        assert subscribe_requests(server, second_key) == Counter({CHAT: 1})
        await client.disconnect()
        await asyncio.wait_for(blocking_connect, timeout=1.0)


@pytest.mark.asyncio
class TestInitialSubscribeFails:
    @pytest.mark.parametrize(
        "status, error", [(500, HTTPException), (403, ForbiddenException)]
    )
    @pytest.mark.parametrize("addition_connect", [True, False])
    async def test_connect_closes_the_connection_and_raises(
        self,
        addition_connect,
        status,
        error,
        server,
        client,
        alice,
        monitor,
        connections,
        session_events,
    ):
        server.subscribe_errors = [status]

        with pytest.raises(error):
            await asyncio.wait_for(
                alice.connect(
                    UserPermission(chat=True), addition_connect=addition_connect
                ),
                timeout=2.0,
            )

        key = server.session_of("alice").key
        assert_disconnected("user", client, alice, key)
        assert alice._session_id is None
        assert_nothing_open(client, monitor, connections)
        await wait_until(lambda: server.sessions[key].ws.closed)
        await asyncio.sleep(SETTLE)
        assert len(server.sessions_of("alice")) == 1
        assert session_events.log == [("connect", key), ("disconnect", key)]

        # It connects again as usual.
        second_key = await alice.connect(
            UserPermission(chat=True), addition_connect=True
        )
        assert alice.is_connected
        assert subscribe_requests(server, second_key) == Counter({CHAT: 1})

    async def test_connect_disconnects_the_previous_blocking_connect(
        self, server, client, alice, hold
    ):
        blocking_connect = asyncio.ensure_future(
            alice.connect(UserPermission(chat=True))
        )
        await wait_until(lambda: len(server.requests_to(SUBSCRIBE_PATH)) == 1)
        first_key = alice._session_id
        server.subscribe_errors = [500]

        with pytest.raises(HTTPException):
            await alice.connect(UserPermission(chat=True), addition_connect=True)

        assert await asyncio.wait_for(blocking_connect, timeout=1.0) == first_key
        assert not alice.is_connected
