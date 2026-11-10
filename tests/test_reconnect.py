"""MIT License

Copyright (c) 2024-2025 gunyu1019

Reconnection tests for the official chzzkpy package: when the connection of a user
session or a client session ends by itself, it's connected again with a new session and
the subscribed events are subscribed again. Reconnecting backs off between attempts,
stops when the access token or the client is rejected, and stops at once on
`disconnect()` or when a blocking `connect()` is cancelled, without leaving anything
open. Also covers the `on_disconnect` event and `reconnect=False`.

The mock Chzzk server and fixtures are shared with `test_multi_account.py`. The waits
between reconnection attempts are shortened for the tests.
"""

import asyncio
from typing import Callable, Optional

import aiohttp
import pytest
import pytest_asyncio

import chzzkpy.client
from chzzkpy import UserPermission
from chzzkpy.error import (
    ChatConnectFailed,
    ForbiddenException,
    HTTPException,
    UnauthorizedException,
)
from chzzkpy.gateway import ChzzkGateway
from chzzkpy.state import ConnectionState

from test_multi_account import (  # noqa: F401
    chat_payload,
    client,
    events,
    monitor,
    server,
    wait_until,
)

INITIAL_DELAY = 0.01
MAX_DELAY = 0.04
# Long enough for several reconnection attempts.
SETTLE = 0.1

KINDS = ["user", "client"]
STAGES = ["session_request", "websocket_upgrade", "ready", "subscribe"]
SUBSCRIBE_PATH = "/open/v1/sessions/events/subscribe/"


@pytest.fixture(autouse=True)
def fast_reconnect(monkeypatch):
    monkeypatch.setattr("chzzkpy.client._RECONNECT_INITIAL_DELAY", INITIAL_DELAY)
    monkeypatch.setattr("chzzkpy.client._RECONNECT_MAX_DELAY", MAX_DELAY)


@pytest.fixture
def delays(monkeypatch) -> list[float]:
    """Records the delay, before jitter, of every reconnection attempt."""
    recorded = []
    original = chzzkpy.client._reconnect_delay

    def reconnect_delay(delay: float) -> float:
        recorded.append(delay)
        return original(delay)

    monkeypatch.setattr("chzzkpy.client._reconnect_delay", reconnect_delay)
    return recorded


class SessionEvents:
    """Records `on_connect` and `on_disconnect` in the order they're dispatched."""

    def __init__(self, client):
        self.log: list[tuple[str, str]] = []

        async def on_connect(session_id):
            self.log.append(("connect", session_id))

        async def on_disconnect(session_id):
            self.log.append(("disconnect", session_id))

        client.event(on_connect)
        client.event(on_disconnect)


@pytest.fixture
def session_events(client):
    return SessionEvents(client)


class Connections:
    """Every aiohttp session and websocket created while the fixture is active."""

    def __init__(self):
        self.sessions: list[aiohttp.ClientSession] = []
        self.websockets: list[aiohttp.ClientWebSocketResponse] = []


@pytest.fixture
def connections(monkeypatch) -> Connections:
    instance = Connections()
    original_init = aiohttp.ClientSession.__init__
    original_ws_connect = aiohttp.ClientSession.ws_connect

    def __init__(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        instance.sessions.append(self)

    async def ws_connect(self, *args, **kwargs):
        websocket = await original_ws_connect(self, *args, **kwargs)
        instance.websockets.append(websocket)
        return websocket

    monkeypatch.setattr(aiohttp.ClientSession, "__init__", __init__)
    monkeypatch.setattr(aiohttp.ClientSession, "ws_connect", ws_connect)
    return instance


class Hold:
    """Holds whoever reaches it until `release()`. Later arrivals aren't held."""

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

    def release(self):
        self.released = True
        for waiter in self._waiters:
            if not waiter.done():  # the holder was cancelled
                waiter.set_result(None)
        self._waiters.clear()


@pytest.fixture
def hold(server):
    instance = Hold()
    yield instance
    instance.release()


@pytest_asyncio.fixture
async def alice(server, client):
    return await client.get_user_client(server.add_account("alice"))


def owner_of(kind: str) -> Optional[str]:
    return "alice" if kind == "user" else None


def session_requests(server, owner_name: Optional[str]) -> list[dict]:
    """The session requests of an account (None means client sessions), oldest first."""
    if owner_name is None:
        return server.requests_to("/open/v1/sessions/auth/client")
    return [
        r
        for r in server.requests
        if r["path"] == "/open/v1/sessions/auth"
        and r["token"].startswith(f"token-{owner_name}")
    ]


def subscriptions_on(server, session_key: str) -> set[tuple[str, str]]:
    """(event, token) of every subscription requested on `session_key`."""
    return {
        (r["path"].rsplit("/", 1)[1], r["token"])
        for r in server.requests_to(SUBSCRIBE_PATH)
        if r["query"]["sessionKey"] == session_key
    }


async def reconnected_user(user_client, previous_key: str) -> str:
    """Waits until `user_client` has reconnected and subscribed again; returns the new key."""
    await wait_until(
        lambda: user_client.is_connected
        and user_client._reconnect_task is None
        and user_client._session_id != previous_key
    )
    return user_client._session_id


async def reconnected_client(client, previous_key: str) -> str:
    """Waits until the client session of `previous_key` has reconnected and subscribed
    again; returns the new key."""
    session = client._client_session_of(previous_key)
    assert session is not None
    await wait_until(
        lambda: session.reconnect_task is None
        and session.key != previous_key
        and session.key in client._gateway
    )
    return session.key


async def start(kind: str, client, alice, **kwargs) -> str:
    """Connects a user session of alice, or a client session alice subscribes chat on."""
    if kind == "user":
        return await alice.connect(
            UserPermission(chat=True), addition_connect=True, **kwargs
        )
    session_id = await client.connect(addition_connect=True, **kwargs)
    await alice.subscribe(UserPermission(chat=True), session_id)
    return session_id


def start_blocking(kind: str, client, alice) -> asyncio.Future:
    if kind == "user":
        return asyncio.ensure_future(alice.connect(UserPermission(chat=True)))
    return asyncio.ensure_future(client.connect())


async def connected(kind: str, server, client, alice) -> str:
    """Waits until a blocking connect has connected; returns the session key."""
    if kind == "user":
        await wait_until(lambda: len(server.requests_to(SUBSCRIBE_PATH)) == 1)
        return alice._session_id
    await wait_until(lambda: len(client._gateway) == 1)
    return next(iter(client._gateway))


async def disconnect(kind: str, client, alice):
    if kind == "user":
        await alice.disconnect()
    else:
        await client.disconnect()


def reconnection(
    kind: str, client, alice, key: str
) -> Optional[asyncio.TimerHandle | asyncio.Task]:
    """The timer of the first wait or the task of a reconnection in progress."""
    if kind == "user":
        return alice._reconnect_timer or alice._reconnect_task
    session = client._client_session_of(key)
    if session is None:
        return None
    return session.reconnect_timer or session.reconnect_task


def assert_disconnected(kind: str, client, alice, key: str):
    assert reconnection(kind, client, alice, key) is None
    if kind == "user":
        assert not alice.is_connected and alice._gateway is None
    else:
        assert client._gateway == {}
        assert client._client_sessions == [] and client._session_keys == {}


def assert_nothing_open(client, monitor, connections):
    for gateway in monitor.gateways:
        assert not gateway.is_connected
        assert gateway.session.closed
        assert gateway._read_background_loop.done()
    assert all(websocket.closed for websocket in connections.websockets)
    assert all(
        session.closed
        for session in connections.sessions
        if session is not client.http.session
    )


def hold_stage(
    stage: str, kind: str, monkeypatch, server, client, hold, first_key: str
) -> Callable[[], bool]:
    """Holds the next reconnection attempt at `stage`.
    Returns a predicate telling whether the attempt has reached it."""
    if stage == "session_request":
        name = "generate_user_session" if kind == "user" else "generate_client_session"
        original = getattr(client.http, name)

        async def generate_session(*args, **kwargs):
            await hold.reach()
            return await original(*args, **kwargs)

        monkeypatch.setattr(client.http, name, generate_session)
        return lambda: hold.arrived == 1
    if stage == "websocket_upgrade":
        probes = server.probes
        server.answer_probe = False
        return lambda: server.probes == probes + 1
    if stage == "ready":
        original_push = server.push

        async def push(session, event, data):
            if event == "SYSTEM" and data["type"] == "connected":
                await hold.reach()
                # Released after the client has gone: the server closes its end.
                await session.ws.close()
                return
            await original_push(session, event, data)

        monkeypatch.setattr(server, "push", push)
        return lambda: hold.arrived == 1

    original_subscribe = client.http.subcribe_event

    async def subcribe_event(*args, **kwargs):
        if kwargs["session_key"] != first_key:
            await hold.reach()
        return await original_subscribe(*args, **kwargs)

    monkeypatch.setattr(client.http, "subcribe_event", subcribe_event)
    return lambda: hold.arrived == 1


@pytest.mark.asyncio
class TestUserSessionReconnect:
    async def test_dropped_session_is_reconnected_and_subscribed_again(
        self, server, client, alice, events, session_events
    ):
        first_key = await alice.connect(
            UserPermission(chat=True, donation=True), addition_connect=True
        )

        await server.drop(server.sessions[first_key])
        second_key = await reconnected_user(alice, first_key)

        assert second_key == server.session_of("alice").key != first_key
        assert subscriptions_on(server, second_key) == {
            ("chat", "token-alice"),
            ("donation", "token-alice"),
        }
        await server.push(
            server.sessions[second_key], "CHAT", chat_payload("channel-alice", "again")
        )
        message = await events.next("chat")
        assert message.content == "again"
        await message.send("reply")
        sent = [r["token"] for r in server.requests_to("/open/v1/chats/send")]
        assert sent == ["token-alice"]
        await wait_until(lambda: len(session_events.log) == 3)
        assert session_events.log == [
            ("connect", first_key),
            ("disconnect", first_key),
            ("connect", second_key),
        ]

    async def test_subscriptions_changed_after_connect_are_restored(
        self, server, client, alice
    ):
        first_key = await alice.connect(
            UserPermission(chat=True), addition_connect=True
        )
        await alice.subscribe(UserPermission(donation=True, subscription=True))
        await alice.unsubscribe(UserPermission(chat=True))

        await server.drop(server.sessions[first_key])
        second_key = await reconnected_user(alice, first_key)

        assert subscriptions_on(server, second_key) == {
            ("donation", "token-alice"),
            ("subscription", "token-alice"),
        }

    async def test_blocking_connect_stays_blocked_across_reconnects(
        self, server, client, alice, delays
    ):
        blocking_connect = asyncio.ensure_future(
            alice.connect(UserPermission(chat=True))
        )
        first_key = await connected("user", server, client, alice)

        for _ in range(2):
            previous_key = alice._session_id
            await server.drop(server.sessions[previous_key])
            await reconnected_user(alice, previous_key)
            assert not blocking_connect.done()

        # Each reconnection starts over from the initial delay.
        assert delays == [INITIAL_DELAY, INITIAL_DELAY]
        await alice.disconnect()
        assert await asyncio.wait_for(blocking_connect, timeout=1.0) == first_key

    async def test_rejected_token_is_refreshed_once(
        self, server, client, alice, events
    ):
        first_key = await alice.connect(
            UserPermission(chat=True), addition_connect=True
        )
        server.session_errors["alice"] = [401]

        await server.drop(server.sessions[first_key])
        second_key = await reconnected_user(alice, first_key)

        refreshed = alice.access_token.access_token
        assert refreshed.startswith("token-alice-refreshed-")
        assert len(server.requests_to("/auth/v1/token")) == 1
        assert [r["token"] for r in session_requests(server, "alice")] == [
            "token-alice",
            "token-alice",
            refreshed,
        ]
        assert subscriptions_on(server, second_key) == {("chat", refreshed)}
        await server.push(
            server.sessions[second_key], "CHAT", chat_payload("channel-alice", "hi")
        )
        await (await events.next("chat")).send("reply")
        sent = [r["token"] for r in server.requests_to("/open/v1/chats/send")]
        assert sent == [refreshed]

    @pytest.mark.parametrize(
        "status, error", [(401, UnauthorizedException), (403, ForbiddenException)]
    )
    async def test_reconnecting_stops_when_token_is_still_rejected(
        self, server, client, alice, monitor, connections, status, error
    ):
        blocking_connect = asyncio.ensure_future(
            alice.connect(UserPermission(chat=True))
        )
        first_key = await connected("user", server, client, alice)
        server.reject_sessions["alice"] = status

        await server.drop(server.sessions[first_key])

        with pytest.raises(error):
            await asyncio.wait_for(blocking_connect, timeout=2.0)
        assert len(server.requests_to("/auth/v1/token")) == 1
        # The first session, then one attempt before refreshing and one after.
        assert len(session_requests(server, "alice")) == 3
        assert_disconnected("user", client, alice, first_key)
        assert_nothing_open(client, monitor, connections)
        await asyncio.sleep(SETTLE)
        assert len(session_requests(server, "alice")) == 3

    async def test_connect_during_reconnection_stops_it(
        self, monkeypatch, server, client, alice, hold, monitor, connections
    ):
        first_key = await alice.connect(
            UserPermission(chat=True), addition_connect=True
        )
        original = client.http.generate_user_session

        async def generate_user_session(*args, **kwargs):
            if not hold.released:
                await hold.reach()
            return await original(*args, **kwargs)

        monkeypatch.setattr(client.http, "generate_user_session", generate_user_session)
        await server.drop(server.sessions[first_key])
        await wait_until(lambda: hold.arrived == 1)
        attempt = alice._reconnect_task
        hold.released = True

        second_key = await alice.connect(
            UserPermission(chat=True), addition_connect=True
        )

        assert attempt.done()
        assert alice.is_connected and alice._reconnect_task is None
        assert second_key == server.session_of("alice").key
        await asyncio.sleep(SETTLE)
        assert len(server.sessions_of("alice")) == 2
        assert alice._session_id == second_key


@pytest.mark.asyncio
class TestClientSessionReconnect:
    async def test_dropped_session_is_reconnected_with_every_subscription(
        self, server, client, events, session_events
    ):
        alice = await client.get_user_client(server.add_account("alice"))
        bob = await client.get_user_client(
            server.add_account("bob", profile_scope=False)
        )
        first_key = await client.connect(addition_connect=True)
        await alice.subscribe(UserPermission(chat=True), first_key)
        await bob.subscribe(UserPermission(chat=True, donation=True), first_key)
        assert bob.channel_id == "channel-bob"

        await server.drop(server.sessions[first_key])
        second_key = await reconnected_client(client, first_key)

        assert second_key == server.session_of(None).key != first_key
        assert list(client._gateway) == [second_key]
        assert subscriptions_on(server, second_key) == {
            ("chat", "token-alice"),
            ("chat", "token-bob"),
            ("donation", "token-bob"),
        }
        session = server.sessions[second_key]
        await server.push(session, "CHAT", chat_payload("channel-alice", "to alice"))
        await server.push(session, "CHAT", chat_payload("channel-bob", "to bob"))
        for _ in range(2):
            message = await events.next("chat")
            await message.send(f"reply {message.content}")
        sent = {
            (r["token"], r["body"]["message"])
            for r in server.requests_to("/open/v1/chats/send")
        }
        assert sent == {
            ("token-alice", "reply to alice"),
            ("token-bob", "reply to bob"),
        }
        await wait_until(lambda: len(session_events.log) == 3)
        assert session_events.log == [
            ("connect", first_key),
            ("disconnect", first_key),
            ("connect", second_key),
        ]

    async def test_channel_id_is_learned_on_the_reconnected_session(
        self, monkeypatch, server, client
    ):
        monkeypatch.setattr("chzzkpy.client._SUBSCRIBED_EVENT_TIMEOUT", 0.1)
        bob = await client.get_user_client(
            server.add_account("bob", profile_scope=False)
        )
        first_key = await client.connect(addition_connect=True)
        hidden = {first_key}
        original_push = server.push

        async def push(session, event, data):
            if (
                session.key in hidden
                and event == "SYSTEM"
                and data["type"] == "subscribed"
            ):
                return
            await original_push(session, event, data)

        monkeypatch.setattr(server, "push", push)
        await bob.subscribe(UserPermission(chat=True), first_key)
        assert bob.channel_id is None
        assert first_key in client._ambiguous_sessions

        await server.drop(server.sessions[first_key])
        second_key = await reconnected_client(client, first_key)

        assert bob.channel_id == "channel-bob"
        assert client._ambiguous_sessions == set()
        assert subscriptions_on(server, second_key) == {("chat", "token-bob")}

    async def test_old_session_key_keeps_working(
        self, server, client, alice, session_events
    ):
        first_key = await client.connect(addition_connect=True)
        await alice.subscribe(UserPermission(chat=True, donation=True), first_key)
        await alice.unsubscribe(UserPermission(donation=True), first_key)

        await server.drop(server.sessions[first_key])
        second_key = await reconnected_client(client, first_key)

        assert subscriptions_on(server, second_key) == {("chat", "token-alice")}
        await alice.subscribe(UserPermission(subscription=True), first_key)
        assert ("subscription", "token-alice") in subscriptions_on(server, second_key)

        gateway = client._gateway[second_key]
        await client.disconnect(first_key)

        assert client._gateway == {}
        assert client._client_sessions == [] and client._session_keys == {}
        assert not gateway.is_connected and gateway.session.closed
        await wait_until(lambda: server.sessions[second_key].ws.closed)
        await wait_until(lambda: len(session_events.log) == 4)
        assert session_events.log[-1] == ("disconnect", second_key)

    async def test_reconnecting_session_keeps_its_slot(
        self, monkeypatch, server, client, hold
    ):
        session_ids = [await client.connect(addition_connect=True) for _ in range(10)]
        original = client.http.generate_client_session

        async def generate_client_session(*args, **kwargs):
            await hold.reach()
            return await original(*args, **kwargs)

        monkeypatch.setattr(
            client.http, "generate_client_session", generate_client_session
        )
        await server.drop(server.sessions[session_ids[0]])
        await wait_until(lambda: hold.arrived == 1)

        assert len(client._gateway) == 9
        with pytest.raises(ChatConnectFailed) as raised:
            await asyncio.wait_for(client.connect(addition_connect=True), timeout=1.0)
        assert str(raised.value) == str(ChatConnectFailed.max_connection())
        assert hold.arrived == 1

        hold.release()
        second_key = await reconnected_client(client, session_ids[0])

        assert len(client._gateway) == 10
        with pytest.raises(ChatConnectFailed):
            await asyncio.wait_for(client.connect(addition_connect=True), timeout=1.0)
        await client.disconnect(session_ids[0])
        assert len(client._gateway) == 9 and second_key not in client._gateway
        assert isinstance(await client.connect(addition_connect=True), str)

    async def test_rejected_token_of_a_user_client_is_refreshed(
        self, server, client, alice
    ):
        bob = await client.get_user_client(server.add_account("bob"))
        first_key = await client.connect(addition_connect=True)
        await alice.subscribe(UserPermission(chat=True), first_key)
        await bob.subscribe(UserPermission(chat=True), first_key)
        # bob's access token stops working; its refresh token still does.
        account = server.accounts.pop("token-bob")
        account.access_token = "token-bob-revoked"
        server.accounts[account.access_token] = account

        await server.drop(server.sessions[first_key])
        second_key = await reconnected_client(client, first_key)

        refreshed = bob.access_token.access_token
        assert refreshed.startswith("token-bob-refreshed-")
        assert ("chat", refreshed) in subscriptions_on(server, second_key)
        assert sorted(server.sessions[second_key].subscriptions) == [
            ("chat", "channel-alice"),
            ("chat", "channel-bob"),
        ]

    async def test_user_client_still_rejected_is_not_subscribed_again(
        self, server, client, alice
    ):
        bob = await client.get_user_client(server.add_account("bob"))
        first_key = await client.connect(addition_connect=True)
        await alice.subscribe(UserPermission(chat=True), first_key)
        await bob.subscribe(UserPermission(chat=True), first_key)
        # Neither the access token nor the refresh token of bob works any more.
        del server.accounts["token-bob"]

        await server.drop(server.sessions[first_key])
        second_key = await reconnected_client(client, first_key)

        assert server.sessions[second_key].subscriptions == [("chat", "channel-alice")]
        assert len(server.requests_to("/auth/v1/token")) == 1
        session = client._client_session_of(second_key)
        assert list(session.subscriptions) == [alice]
        # The other user clients keep their events.
        assert list(client._gateway) == [second_key]

    @pytest.mark.parametrize(
        "status, error", [(401, UnauthorizedException), (403, ForbiddenException)]
    )
    async def test_reconnecting_stops_when_session_is_rejected(
        self, server, client, alice, monitor, connections, status, error
    ):
        blocking_connect = asyncio.ensure_future(client.connect())
        first_key = await connected("client", server, client, alice)
        server.reject_sessions[None] = status

        await server.drop(server.sessions[first_key])

        with pytest.raises(error):
            await asyncio.wait_for(blocking_connect, timeout=2.0)
        assert len(session_requests(server, None)) == 2
        assert_disconnected("client", client, alice, first_key)
        assert_nothing_open(client, monitor, connections)
        await asyncio.sleep(SETTLE)
        assert len(session_requests(server, None)) == 2

        # The session doesn't take a slot any more.
        del server.reject_sessions[None]
        for _ in range(10):
            await client.connect(addition_connect=True)


@pytest.mark.asyncio
class TestRetry:
    @pytest.mark.parametrize("kind", KINDS)
    async def test_failed_attempts_are_retried_with_growing_delay(
        self, kind, server, client, alice, delays
    ):
        first_key = await start(kind, client, alice)
        server.session_errors[owner_of(kind)] = [500] * 4

        await server.drop(server.sessions[first_key])
        if kind == "user":
            second_key = await reconnected_user(alice, first_key)
        else:
            second_key = await reconnected_client(client, first_key)

        assert delays == [0.01, 0.02, 0.04, 0.04, 0.04]
        # The first session, four failed attempts and the one that succeeded.
        requests = session_requests(server, owner_of(kind))
        assert len(requests) == 6
        for earlier, later, delay in zip(requests[1:], requests[2:], delays[1:]):
            assert later["time"] - earlier["time"] >= delay / 2
        assert subscriptions_on(server, second_key) == {("chat", "token-alice")}

    @pytest.mark.parametrize("kind", KINDS)
    async def test_session_is_connected_again_when_subscribing_again_fails(
        self, monkeypatch, kind, server, client, alice, session_events
    ):
        first_key = await start(kind, client, alice)
        original = client.http.subcribe_event
        failed = []

        async def subcribe_event(*args, **kwargs):
            if not failed:
                failed.append(kwargs["session_key"])
                raise HTTPException(500, "SUBSCRIBE_ERROR")
            return await original(*args, **kwargs)

        monkeypatch.setattr(client.http, "subcribe_event", subcribe_event)

        await server.drop(server.sessions[first_key])
        if kind == "user":
            third_key = await reconnected_user(alice, first_key)
        else:
            third_key = await reconnected_client(client, first_key)

        # The session whose subscription failed was closed, and another one was made.
        second_key = failed[0]
        assert second_key not in (first_key, third_key)
        await wait_until(lambda: server.sessions[second_key].ws.closed)
        assert subscriptions_on(server, third_key) == {("chat", "token-alice")}
        await wait_until(lambda: len(session_events.log) == 5)
        assert session_events.log == [
            ("connect", first_key),
            ("disconnect", first_key),
            ("connect", second_key),
            ("disconnect", second_key),
            ("connect", third_key),
        ]
        if kind == "client":
            assert list(client._gateway) == [third_key]
            await client.disconnect(second_key)
            assert client._gateway == {}


def test_delay_has_jitter_within_the_delay():
    waits = [chzzkpy.client._reconnect_delay(1.0) for _ in range(200)]

    assert all(0.5 <= wait <= 1.0 for wait in waits)
    assert len(set(waits)) > 1


@pytest.mark.asyncio
class TestStopReconnecting:
    @pytest.mark.parametrize("wait", ["first", "after_failed_attempt"])
    @pytest.mark.parametrize("kind", KINDS)
    async def test_disconnect_during_backoff_stops_reconnecting(
        self, monkeypatch, kind, wait, server, client, alice, monitor, connections
    ):
        # The wait under test lasts seconds.
        waits = [10.0] if wait == "first" else [0.0, 10.0]
        monkeypatch.setattr("chzzkpy.client._reconnect_delay", lambda _: waits.pop(0))
        first_key = await start(kind, client, alice)
        requests = 1 if wait == "first" else 2
        if wait == "after_failed_attempt":
            server.reject_sessions[owner_of(kind)] = 500

        await server.drop(server.sessions[first_key])
        await wait_until(lambda: not waits)
        await asyncio.sleep(0.05)
        waiting = reconnection(kind, client, alice, first_key)
        assert waiting is not None
        assert len(session_requests(server, owner_of(kind))) == requests

        await asyncio.wait_for(disconnect(kind, client, alice), timeout=1.0)

        if wait == "first":
            assert waiting.cancelled()
        else:
            assert waiting.done()
        assert_disconnected(kind, client, alice, first_key)
        assert_nothing_open(client, monitor, connections)
        await asyncio.sleep(SETTLE)
        assert len(session_requests(server, owner_of(kind))) == requests

    @pytest.mark.parametrize("stage", STAGES)
    @pytest.mark.parametrize("kind", KINDS)
    async def test_disconnect_during_attempt_leaves_nothing_open(
        self,
        monkeypatch,
        kind,
        stage,
        server,
        client,
        alice,
        hold,
        monitor,
        connections,
    ):
        first_key = await start(kind, client, alice)
        reached = hold_stage(stage, kind, monkeypatch, server, client, hold, first_key)
        await server.drop(server.sessions[first_key])
        await wait_until(reached)
        attempt = reconnection(kind, client, alice, first_key)

        await asyncio.wait_for(disconnect(kind, client, alice), timeout=2.0)

        assert attempt.done()
        assert_disconnected(kind, client, alice, first_key)
        assert_nothing_open(client, monitor, connections)
        requests = len(session_requests(server, owner_of(kind)))
        hold.release()
        server.answer_probe = True
        await asyncio.sleep(SETTLE)
        assert len(session_requests(server, owner_of(kind))) == requests
        assert_disconnected(kind, client, alice, first_key)

    @pytest.mark.parametrize("kind", KINDS)
    async def test_cancelling_blocking_connect_raises_and_cleans_up(
        self, kind, server, client, alice, monitor, connections, session_events
    ):
        blocking_connect = start_blocking(kind, client, alice)
        first_key = await connected(kind, server, client, alice)

        blocking_connect.cancel()

        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(blocking_connect, timeout=1.0)
        assert_disconnected(kind, client, alice, first_key)
        assert_nothing_open(client, monitor, connections)
        await wait_until(lambda: server.sessions[first_key].ws.closed)
        await asyncio.sleep(SETTLE)
        assert len(server.sessions_of(owner_of(kind))) == 1
        assert session_events.log == [("connect", first_key), ("disconnect", first_key)]

    @pytest.mark.parametrize("kind", KINDS)
    async def test_wait_for_on_blocking_connect_raises_timeout_error(
        self, kind, server, client, alice, monitor, connections
    ):
        if kind == "user":
            blocking_connect = alice.connect(UserPermission(chat=True))
        else:
            blocking_connect = client.connect()

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(blocking_connect, timeout=0.2)

        session = server.session_of(owner_of(kind))
        assert_disconnected(kind, client, alice, session.key)
        assert_nothing_open(client, monitor, connections)
        await asyncio.sleep(SETTLE)
        assert len(server.sessions_of(owner_of(kind))) == 1

    @pytest.mark.parametrize("kind", KINDS)
    async def test_cancelling_blocking_connect_during_reconnection(
        self, kind, server, client, alice, monitor, connections
    ):
        blocking_connect = start_blocking(kind, client, alice)
        first_key = await connected(kind, server, client, alice)
        server.reject_sessions[owner_of(kind)] = 500
        await server.drop(server.sessions[first_key])
        await wait_until(lambda: len(session_requests(server, owner_of(kind))) >= 3)

        blocking_connect.cancel()

        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(blocking_connect, timeout=1.0)
        assert_disconnected(kind, client, alice, first_key)
        assert_nothing_open(client, monitor, connections)
        requests = len(session_requests(server, owner_of(kind)))
        await asyncio.sleep(SETTLE)
        assert len(session_requests(server, owner_of(kind))) == requests

    async def test_aexit_stops_reconnecting(
        self, server, client, alice, monitor, connections
    ):
        bob = await client.get_user_client(server.add_account("bob"))
        alice_key = await alice.connect(
            UserPermission(chat=True), addition_connect=True
        )
        client_key = await client.connect(addition_connect=True)
        await bob.subscribe(UserPermission(chat=True), client_key)
        server.reject_sessions["alice"] = 500
        server.reject_sessions[None] = 500
        await server.drop(server.sessions[alice_key])
        await server.drop(server.sessions[client_key])
        await wait_until(
            lambda: len(session_requests(server, "alice")) >= 2
            and len(session_requests(server, None)) >= 2
        )

        await asyncio.wait_for(client.__aexit__(None, None, None), timeout=2.0)

        assert_disconnected("user", client, alice, alice_key)
        assert_disconnected("client", client, alice, client_key)
        assert_nothing_open(client, monitor, connections)
        requests = len(server.requests)
        await asyncio.sleep(SETTLE)
        assert len(server.requests) == requests


@pytest.mark.asyncio
class TestReconnectDisabled:
    async def test_user_session_is_not_reconnected(
        self, server, client, alice, session_events
    ):
        first_key = await alice.connect(
            UserPermission(chat=True), addition_connect=True, reconnect=False
        )
        gateway = alice._gateway

        await server.drop(server.sessions[first_key])
        await wait_until(lambda: gateway.session.closed)
        await asyncio.sleep(SETTLE)

        assert_disconnected("user", client, alice, first_key)
        assert len(server.sessions_of("alice")) == 1
        assert session_events.log == [("connect", first_key), ("disconnect", first_key)]

    async def test_client_session_is_not_reconnected(
        self, server, client, session_events
    ):
        first_key = await client.connect(addition_connect=True, reconnect=False)
        gateway = client._gateway[first_key]

        await server.drop(server.sessions[first_key])
        await wait_until(lambda: gateway.session.closed)
        await asyncio.sleep(SETTLE)

        assert client._gateway == {}
        assert client._client_sessions == [] and client._session_keys == {}
        assert len(server.sessions_of(None)) == 1
        assert session_events.log == [("connect", first_key), ("disconnect", first_key)]


@pytest.mark.asyncio
class TestDisconnectEvent:
    @pytest.mark.parametrize("kind", KINDS)
    async def test_dispatched_when_disconnect_ends_the_session(
        self, kind, server, client, alice, session_events
    ):
        first_key = await start(kind, client, alice)

        await disconnect(kind, client, alice)
        # Nothing is left to disconnect.
        await disconnect(kind, client, alice)

        await wait_until(lambda: len(session_events.log) == 2)
        await asyncio.sleep(0.05)
        assert session_events.log == [("connect", first_key), ("disconnect", first_key)]


@pytest.mark.asyncio
class TestPendingSubscription:
    @pytest.mark.parametrize("reconnect", [True, False])
    async def test_drop_ends_the_wait_for_the_subscribed_event(
        self, monkeypatch, server, client, reconnect
    ):
        alice = await client.get_user_client(
            server.add_account("alice", profile_scope=False)
        )
        first_key = await client.connect(addition_connect=True, reconnect=reconnect)
        original_push = server.push

        async def push(session, event, data):
            if event == "SYSTEM" and data["type"] == "subscribed":
                return
            await original_push(session, event, data)

        monkeypatch.setattr(server, "push", push)
        requested = asyncio.Event()
        original_subscribe_events = alice._subscribe_events

        async def subscribe_events(*args, **kwargs):
            result = await original_subscribe_events(*args, **kwargs)
            requested.set()
            return result

        monkeypatch.setattr(alice, "_subscribe_events", subscribe_events)
        subscribing = asyncio.ensure_future(
            alice.subscribe(UserPermission(chat=True), first_key)
        )
        await asyncio.wait_for(requested.wait(), timeout=2.0)
        # It's waiting for the "subscribed" event now.
        assert not subscribing.done()

        await server.drop(server.sessions[first_key])

        # Without stopping, it waits for the event for 10 seconds.
        await asyncio.wait_for(subscribing, timeout=2.0)
        assert first_key not in client._ambiguous_sessions
        assert alice.channel_id is None


@pytest.mark.asyncio
class TestMultiAccount:
    async def test_other_account_keeps_receiving_while_one_reconnects(
        self, monkeypatch, server, client, events, hold
    ):
        alice = await client.get_user_client(server.add_account("alice"))
        bob = await client.get_user_client(server.add_account("bob"))
        alice_key = await alice.connect(
            UserPermission(chat=True), addition_connect=True
        )
        bob_key = await bob.connect(UserPermission(chat=True), addition_connect=True)
        original = client.http.generate_user_session

        async def generate_user_session(*args, **kwargs):
            if kwargs["token"].access_token == "token-alice":
                await hold.reach()
            return await original(*args, **kwargs)

        monkeypatch.setattr(client.http, "generate_user_session", generate_user_session)

        await server.drop(server.sessions[alice_key])
        await wait_until(lambda: hold.arrived == 1)
        for index in range(3):
            await server.push(
                server.sessions[bob_key],
                "CHAT",
                chat_payload("channel-bob", f"bob-{index}"),
            )
            assert (await events.next("chat")).content == f"bob-{index}"
            await asyncio.sleep(INITIAL_DELAY)

        hold.release()
        alice_key = await reconnected_user(alice, alice_key)

        await server.push(
            server.sessions[alice_key], "CHAT", chat_payload("channel-alice", "alice")
        )
        await server.push(
            server.sessions[bob_key], "CHAT", chat_payload("channel-bob", "bob")
        )
        received = {(await events.next("chat")).content for _ in range(2)}
        assert received == {"alice", "bob"}
        assert bob.is_connected and bob._session_id == bob_key
        assert server.sessions_of("bob") == [server.sessions[bob_key]]


@pytest.mark.asyncio
class TestHandshakeCancellation:
    async def test_cancelled_upgrade_closes_the_websocket(self, server, connections):
        server.answer_probe = False
        session = server._new_session(owner=None)
        state = ConnectionState(dispatch=lambda *args: None, handler={}, http=None)

        async with aiohttp.ClientSession() as http_session:
            connecting = asyncio.ensure_future(
                ChzzkGateway.connect(
                    f"{server.url}/?auth={session.auth}",
                    state,
                    asyncio.get_running_loop(),
                    http_session,
                    ssl=False,
                )
            )
            await wait_until(lambda: server.probes == 1)

            connecting.cancel()

            with pytest.raises(asyncio.CancelledError):
                await connecting
            assert len(connections.websockets) == 1
            assert connections.websockets[0].closed
