"""MIT License

Copyright (c) 2024-2025 gunyu1019

Multi-account tests for the official chzzkpy package.

One `Client` owns several `UserClient`s (one per Chzzk account). These tests check that
events from every account reach the shared handlers, and that anything sent back
(replies, subscriptions) goes out with the access token of the account it belongs to.

A mock server stands in for both the Chzzk Open API and the session gateway, so the real
`ChzzkOpenAPISession`, `ChzzkGateway` and `ConnectionState` code paths are exercised.
The mock tells accounts apart by the `Authorization` header, and deliberately gives each
session an engine.io sid that differs from its Chzzk session key.
"""

import asyncio
import itertools
import json
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import aiohttp
import pytest
import pytest_asyncio
from aiohttp import web

from chzzkpy import AccessToken, Client, UserClient, UserPermission
from chzzkpy.enums import EnginePacketType, SocketPacketType
from chzzkpy.error import ChatConnectFailed
from chzzkpy.gateway import ChzzkGateway
from chzzkpy.packet import Packet
from chzzkpy.payload import Payload

CLIENT_ID = "client-id"
CLIENT_SECRET = "client-secret"


@dataclass
class MockAccount:
    name: str
    channel_id: str
    access_token: str
    refresh_token: str
    profile_scope: bool = True


@dataclass
class MockSession:
    key: str
    auth: str
    owner: Optional[MockAccount]  # None for a client session
    sid: Optional[str] = None
    ws: Optional[web.WebSocketResponse] = None
    subscriptions: list[tuple[str, str]] = field(default_factory=list)
    pings: int = 0


class MockChzzkServer:
    """Mock Chzzk Open API and session gateway (socket.io v2 / engine.io v3)."""

    def __init__(self):
        self.url: Optional[str] = None
        self.accounts: dict[str, MockAccount] = dict()  # access token -> account
        self.sessions: dict[str, MockSession] = dict()  # session key -> session
        self.requests: list[dict[str, Any]] = []

        self.ping_interval_ms = 25000
        self.ping_timeout_ms = 20000
        # Sessions of these accounts are closed right after the upgrade, before "connected".
        self.close_before_ready: set[str] = set()
        # Statuses the next session requests are answered with, one per request, by
        # account name (None for client sessions).
        self.session_errors: dict[Optional[str], list[int]] = dict()
        # A status every session request is answered with, by account name.
        self.reject_sessions: dict[Optional[str], int] = dict()
        # When False, the probe of a websocket upgrade is left unanswered.
        self.answer_probe = True
        self.probes = 0

        self._sessions_by_auth: dict[str, MockSession] = dict()
        self._sessions_by_sid: dict[str, MockSession] = dict()
        self._ids = itertools.count(1)
        self._runner: Optional[web.AppRunner] = None

    # ---- server lifecycle ----

    async def start(self):
        app = web.Application()
        app.router.add_route("*", "/socket.io/", self.handle_engine)
        app.router.add_get("/open/v1/users/me", self.handle_users_me)
        app.router.add_get("/open/v1/sessions/auth", self.handle_user_session)
        app.router.add_get("/open/v1/sessions/auth/client", self.handle_client_session)
        app.router.add_post(
            "/open/v1/sessions/events/subscribe/{event}", self.handle_subscribe
        )
        app.router.add_post(
            "/open/v1/sessions/events/unsubscribe/{event}", self.handle_unsubscribe
        )
        app.router.add_post("/open/v1/chats/send", self.handle_send_chat)
        app.router.add_post("/auth/v1/token", self.handle_token)

        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        self.url = f"http://127.0.0.1:{port}"

    async def stop(self):
        await self._runner.cleanup()

    # ---- helpers for tests ----

    def add_account(self, name: str, profile_scope: bool = True) -> AccessToken:
        account = MockAccount(
            name=name,
            channel_id=f"channel-{name}",
            access_token=f"token-{name}",
            refresh_token=f"refresh-{name}",
            profile_scope=profile_scope,
        )
        self.accounts[account.access_token] = account
        return AccessToken(
            access_token=account.access_token,
            refresh_token=account.refresh_token,
            token_type="Bearer",
            expires_in=86400,
        )

    def session_of(self, owner_name: Optional[str]) -> MockSession:
        """The most recent session issued for an account (None means the client session)."""
        for session in reversed(self.sessions.values()):
            owner = session.owner.name if session.owner is not None else None
            if owner == owner_name:
                return session
        raise AssertionError(f"No session was issued for {owner_name!r}")

    def sessions_of(self, owner_name: Optional[str]) -> list[MockSession]:
        """Every session issued for an account (None means client sessions), oldest first."""
        return [
            session
            for session in self.sessions.values()
            if (session.owner.name if session.owner is not None else None) == owner_name
        ]

    def requests_to(self, path_prefix: str) -> list[dict[str, Any]]:
        return [r for r in self.requests if r["path"].startswith(path_prefix)]

    async def push(self, session: MockSession, event: str, data: dict[str, Any]):
        """Send a socket.io event to one session, the way Chzzk delivers chat/donation."""
        assert (
            session.ws is not None and not session.ws.closed
        ), f"Session {session.key} is not connected"
        packet = Packet(
            EnginePacketType.MESSAGE,
            SocketPacketType.EVENT,
            data=[event, json.dumps(data)],
        )
        await session.ws.send_str(packet.encode())

    async def drop(self, session: MockSession):
        """Close a session from the server side without an engine.io CLOSE packet,
        as happens when the gateway restarts or the network drops."""
        await session.ws.close()

    # ---- open api ----

    @staticmethod
    def _content(content: Any = None, code: int = 200, message: Optional[str] = None):
        return web.json_response(
            {"code": code, "message": message, "content": content}, status=code
        )

    def _account_of(self, request: web.Request) -> Optional[MockAccount]:
        authorization = request.headers.get("Authorization", "")
        token_type, _, token = authorization.partition(" ")
        if token_type != "Bearer":
            return None
        return self.accounts.get(token)

    async def _record(self, request: web.Request) -> dict[str, Any]:
        body = await request.json() if request.can_read_body else None
        record = {
            "method": request.method,
            "path": request.path,
            "query": dict(request.query),
            "token": request.headers.get("Authorization", "").partition(" ")[2],
            "body": body,
            "time": asyncio.get_running_loop().time(),
        }
        self.requests.append(record)
        return record

    def _session_error(self, owner_name: Optional[str]) -> Optional[int]:
        queued = self.session_errors.get(owner_name)
        if queued:
            return queued.pop(0)
        return self.reject_sessions.get(owner_name)

    def _new_session(self, owner: Optional[MockAccount]) -> MockSession:
        number = next(self._ids)
        session = MockSession(
            key=f"session-key-{number}", auth=f"auth-{number}", owner=owner
        )
        self.sessions[session.key] = session
        self._sessions_by_auth[session.auth] = session
        return session

    async def handle_users_me(self, request: web.Request):
        await self._record(request)
        account = self._account_of(request)
        if account is None:
            return self._content(code=401, message="INVALID_TOKEN")
        if not account.profile_scope:
            return self._content(code=403, message="INSUFFICIENT_SCOPE")
        return self._content(
            {"channelId": account.channel_id, "channelName": account.name}
        )

    async def handle_user_session(self, request: web.Request):
        await self._record(request)
        account = self._account_of(request)
        if account is None:
            return self._content(code=401, message="INVALID_TOKEN")
        error = self._session_error(account.name)
        if error is not None:
            return self._content(code=error, message="SESSION_ERROR")
        session = self._new_session(owner=account)
        return self._content({"url": f"{self.url}/?auth={session.auth}"})

    async def handle_client_session(self, request: web.Request):
        await self._record(request)
        if (
            request.headers.get("Client-Id") != CLIENT_ID
            or request.headers.get("Client-Secret") != CLIENT_SECRET
        ):
            return self._content(code=401, message="INVALID_CLIENT")
        error = self._session_error(None)
        if error is not None:
            return self._content(code=error, message="SESSION_ERROR")
        session = self._new_session(owner=None)
        return self._content({"url": f"{self.url}/?auth={session.auth}"})

    async def _handle_subscription_change(self, request: web.Request, subscribe: bool):
        record = await self._record(request)
        account = self._account_of(request)
        if account is None:
            return self._content(code=401, message="INVALID_TOKEN")

        session = self.sessions.get(record["query"].get("sessionKey"))
        if session is None:
            return self._content(
                code=404,
                message=f"Unknown session key: {record['query'].get('sessionKey')}",
            )
        if session.owner is not None and session.owner is not account:
            return self._content(code=403, message="NOT_SESSION_OWNER")

        event = request.match_info["event"]
        if subscribe:
            session.subscriptions.append((event, account.channel_id))
        else:
            session.subscriptions.remove((event, account.channel_id))

        await self.push(
            session,
            "SYSTEM",
            {
                "type": "subscribed" if subscribe else "unsubscribed",
                "data": {"eventType": event.upper(), "channelId": account.channel_id},
            },
        )
        return self._content()

    async def handle_subscribe(self, request: web.Request):
        return await self._handle_subscription_change(request, subscribe=True)

    async def handle_unsubscribe(self, request: web.Request):
        return await self._handle_subscription_change(request, subscribe=False)

    async def handle_send_chat(self, request: web.Request):
        await self._record(request)
        if self._account_of(request) is None:
            return self._content(code=401, message="INVALID_TOKEN")
        return self._content({"messageId": f"message-{next(self._ids)}"})

    async def handle_token(self, request: web.Request):
        record = await self._record(request)
        body = record["body"]
        if body.get("grantType") != "refresh_token":
            return self._content(code=400, message="UNSUPPORTED_GRANT_TYPE")

        for old_token, account in list(self.accounts.items()):
            if account.refresh_token != body.get("refreshToken"):
                continue
            del self.accounts[old_token]
            number = next(self._ids)
            account.access_token = f"token-{account.name}-refreshed-{number}"
            account.refresh_token = f"refresh-{account.name}-refreshed-{number}"
            self.accounts[account.access_token] = account
            return self._content(
                {
                    "accessToken": account.access_token,
                    "refreshToken": account.refresh_token,
                    "tokenType": "Bearer",
                    "expiresIn": 86400,
                }
            )
        return self._content(code=401, message="INVALID_REFRESH_TOKEN")

    # ---- session gateway ----

    async def handle_engine(self, request: web.Request):
        if request.query.get("transport") == "websocket":
            return await self._handle_websocket(request)

        if request.method == "POST":
            await request.read()
            return web.Response(text="ok")

        if request.query.get("sid") is not None:
            payload = Payload(packets=[Packet(EnginePacketType.NOOP)])
            return web.Response(
                body=payload.encode(), content_type="application/octet-stream"
            )

        session = self._sessions_by_auth.get(request.query.get("auth"))
        if session is None:
            return web.Response(status=401)

        session.sid = f"eio-sid-{next(self._ids)}"
        self._sessions_by_sid[session.sid] = session
        open_packet = Packet(
            EnginePacketType.OPEN,
            data={
                "sid": session.sid,
                "upgrades": ["websocket"],
                "pingInterval": self.ping_interval_ms,
                "pingTimeout": self.ping_timeout_ms,
            },
        )
        connect_packet = Packet(EnginePacketType.MESSAGE, SocketPacketType.CONNECT)
        payload = Payload(packets=[open_packet, connect_packet])
        return web.Response(
            body=payload.encode(), content_type="application/octet-stream"
        )

    async def _handle_websocket(self, request: web.Request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)

        session = self._sessions_by_sid.get(request.query.get("sid"))
        if session is None:
            await ws.close()
            return ws

        async for message in ws:
            if message.type != aiohttp.WSMsgType.TEXT:
                break
            packet = Packet.decode(message.data)

            if packet.engine_packet_type == EnginePacketType.PING:
                if packet.data == "probe":
                    self.probes += 1
                    if not self.answer_probe:
                        continue
                else:
                    session.pings += 1
                await ws.send_str(
                    Packet(EnginePacketType.PONG, data=packet.data).encode()
                )
            elif packet.engine_packet_type == EnginePacketType.UPGRADE:
                session.ws = ws
                if (
                    session.owner is not None
                    and session.owner.name in self.close_before_ready
                ):
                    await ws.close()
                    break
                await self.push(
                    session,
                    "SYSTEM",
                    {"type": "connected", "data": {"sessionKey": session.key}},
                )
            elif (
                packet.engine_packet_type == EnginePacketType.MESSAGE
                and packet.socket_packet_type == SocketPacketType.DISCONNECT
            ):
                await ws.send_str(Packet(EnginePacketType.CLOSE).encode())
                await ws.close()
                break
            elif packet.engine_packet_type == EnginePacketType.CLOSE:
                await ws.close()
                break
        return ws


def chat_payload(channel_id: str, content: str) -> dict[str, Any]:
    return {
        "senderChannelId": "viewer-channel",
        "profile": {"nickname": "viewer", "badges": [], "verifiedMark": False},
        "content": content,
        "channelId": channel_id,
        "chatChannelId": f"chat-{channel_id}",
        "messageTime": int(time.time() * 1000),
        "emojis": {},
    }


def donation_payload(channel_id: str) -> dict[str, Any]:
    return {
        "donationType": "CHAT",
        "channelId": channel_id,
        "donatorChannelId": "viewer-channel",
        "donatorNickname": "viewer",
        "payAmount": 1000,
        "donationText": "donation",
    }


def subscription_payload(channel_id: str) -> dict[str, Any]:
    return {
        "channelId": channel_id,
        "subscriberChannelId": "viewer-channel",
        "subscriberNickname": "viewer",
        "tierNo": 1,
        "tierName": "tier 1",
        "month": 3,
    }


async def wait_until(predicate, timeout: float = 2.0):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() > deadline:
            raise AssertionError("Timed out waiting for condition")
        await asyncio.sleep(0.01)


class EventRecorder:
    """Collects events dispatched to the client's `@client.event` handlers."""

    EVENTS = ("chat", "donation", "subscription")

    def __init__(self, client: Client):
        self.queues = {event: asyncio.Queue() for event in self.EVENTS}

        for event in self.EVENTS:
            queue = self.queues[event]

            async def handler(item, _queue=queue):
                await _queue.put(item)

            handler.__name__ = f"on_{event}"
            client.event(handler)

    async def next(self, event: str, timeout: float = 2.0):
        return await asyncio.wait_for(self.queues[event].get(), timeout=timeout)


class ReadLoopSpinning(Exception):
    pass


class GatewayMonitor:
    """Tracks gateways created during a test.

    On a closed websocket, `receive()` returns immediately, so a read loop that keeps
    calling it never yields and freezes the whole event loop (every account at once).
    The guard breaks such a loop after `SPIN_LIMIT` reads and records it, turning a
    hang of the test run into a test failure.
    """

    SPIN_LIMIT = 100

    def __init__(self):
        self.gateways: list[ChzzkGateway] = []
        self.spinning: list[ChzzkGateway] = []
        self._closed_reads: dict[int, int] = dict()

    def install(self, monkeypatch):
        original_connect = ChzzkGateway.connect.__func__
        original_read_websocket = ChzzkGateway._read_websocket
        monitor = self

        # Client.connect / UserClient.connect always use TLS; the mock server is plain HTTP.
        async def connect_without_ssl(cls, *args, **kwargs):
            kwargs["ssl"] = False
            gateway = await original_connect(cls, *args, **kwargs)
            monitor.gateways.append(gateway)
            return gateway

        async def guarded_read_websocket(gateway: ChzzkGateway):
            if gateway.websocket is not None and gateway.websocket.closed:
                count = monitor._closed_reads.get(id(gateway), 0) + 1
                monitor._closed_reads[id(gateway)] = count
                if count > monitor.SPIN_LIMIT:
                    monitor.spinning.append(gateway)
                    raise ReadLoopSpinning(
                        f"read loop kept reading a closed websocket {count} times"
                    )
            return await original_read_websocket(gateway)

        monkeypatch.setattr(ChzzkGateway, "connect", classmethod(connect_without_ssl))
        monkeypatch.setattr(ChzzkGateway, "_read_websocket", guarded_read_websocket)

    async def close(self):
        for gateway in self.gateways:
            try:
                await gateway.disconnect()
            except Exception:
                pass  # e.g. writing to a websocket the server already closed
            await gateway.session.close()


@pytest_asyncio.fixture
async def server():
    instance = MockChzzkServer()
    await instance.start()
    yield instance
    await instance.stop()


@pytest_asyncio.fixture
async def monitor(monkeypatch):
    instance = GatewayMonitor()
    instance.install(monkeypatch)
    yield instance
    await instance.close()


@pytest_asyncio.fixture
async def client(server, monitor):
    """A `Client` whose HTTP and gateway traffic goes to the mock server."""
    instance = Client(CLIENT_ID, CLIENT_SECRET)
    await instance._async_setup_hook()
    await instance.http.session.close()
    instance.http.session = aiohttp.ClientSession(server.url)

    yield instance

    # Disconnecting stops reconnecting, so no connection outlives the test. The methods
    # of the class are called, as a test may have replaced them on the instance.
    try:
        await Client.disconnect(instance)
        for user_client in instance.user_client:
            await UserClient.disconnect(user_client)
    finally:
        await instance.http.close()


@pytest.fixture
def events(client):
    return EventRecorder(client)


@pytest.mark.asyncio
class TestMultiAccountUserSession:
    """Several accounts, each connected through its own user session (README pattern)."""

    async def test_each_account_gets_its_own_session_and_subscription(
        self, server, client
    ):
        alice = await client.get_user_client(server.add_account("alice"))
        bob = await client.get_user_client(server.add_account("bob"))

        await alice.connect(UserPermission.all(), addition_connect=True)
        await bob.connect(UserPermission(chat=True), addition_connect=True)

        alice_session = server.session_of("alice")
        bob_session = server.session_of("bob")
        assert alice_session.key != bob_session.key
        assert alice.is_connected and bob.is_connected

        subscribes = server.requests_to("/open/v1/sessions/events/subscribe/")
        alice_subscribes = {
            (r["path"].rsplit("/", 1)[1], r["query"]["sessionKey"])
            for r in subscribes
            if r["token"] == "token-alice"
        }
        bob_subscribes = {
            (r["path"].rsplit("/", 1)[1], r["query"]["sessionKey"])
            for r in subscribes
            if r["token"] == "token-bob"
        }
        assert alice_subscribes == {
            ("chat", alice_session.key),
            ("donation", alice_session.key),
            ("subscription", alice_session.key),
        }
        assert bob_subscribes == {("chat", bob_session.key)}

    async def test_chat_from_every_account_reaches_shared_handler(
        self, server, client, events
    ):
        alice = await client.get_user_client(server.add_account("alice"))
        bob = await client.get_user_client(server.add_account("bob"))
        await alice.connect(UserPermission(chat=True), addition_connect=True)
        await bob.connect(UserPermission(chat=True), addition_connect=True)

        await server.push(
            server.session_of("alice"),
            "CHAT",
            chat_payload("channel-alice", "hi alice"),
        )
        await server.push(
            server.session_of("bob"), "CHAT", chat_payload("channel-bob", "hi bob")
        )

        received = {(await events.next("chat")).content for _ in range(2)}
        assert received == {"hi alice", "hi bob"}

    async def test_reply_goes_out_with_receiving_account_token(
        self, server, client, events
    ):
        alice = await client.get_user_client(server.add_account("alice"))
        bob = await client.get_user_client(server.add_account("bob"))
        await alice.connect(UserPermission(chat=True), addition_connect=True)
        await bob.connect(UserPermission(chat=True), addition_connect=True)

        await server.push(
            server.session_of("bob"), "CHAT", chat_payload("channel-bob", "to bob")
        )
        message = await events.next("chat")
        await message.send("reply from bob")

        await server.push(
            server.session_of("alice"),
            "CHAT",
            chat_payload("channel-alice", "to alice"),
        )
        message = await events.next("chat")
        await message.send("reply from alice")

        sent = [
            (r["token"], r["body"]["message"])
            for r in server.requests_to("/open/v1/chats/send")
        ]
        assert sent == [
            ("token-bob", "reply from bob"),
            ("token-alice", "reply from alice"),
        ]

    async def test_concurrent_replies_keep_tokens_separate(
        self, server, client, events
    ):
        alice = await client.get_user_client(server.add_account("alice"))
        bob = await client.get_user_client(server.add_account("bob"))
        await alice.connect(UserPermission(chat=True), addition_connect=True)
        await bob.connect(UserPermission(chat=True), addition_connect=True)

        await server.push(
            server.session_of("alice"), "CHAT", chat_payload("channel-alice", "a")
        )
        await server.push(
            server.session_of("bob"), "CHAT", chat_payload("channel-bob", "b")
        )
        messages = {}
        for _ in range(2):
            message = await events.next("chat")
            messages[message.channel] = message

        await asyncio.gather(
            *(
                messages[f"channel-{name}"].send(f"{name}-{index}")
                for index in range(10)
                for name in ("alice", "bob")
            )
        )

        sent = server.requests_to("/open/v1/chats/send")
        assert len(sent) == 20
        for request in sent:
            name = request["body"]["message"].split("-")[0]
            assert request["token"] == f"token-{name}"

    async def test_donation_and_subscription_carry_receiving_account_token(
        self, server, client, events
    ):
        alice = await client.get_user_client(server.add_account("alice"))
        bob = await client.get_user_client(server.add_account("bob"))
        await alice.connect(UserPermission.all(), addition_connect=True)
        await bob.connect(UserPermission.all(), addition_connect=True)

        await server.push(
            server.session_of("alice"), "DONATION", donation_payload("channel-alice")
        )
        donation = await events.next("donation")
        await donation.send("thanks for the donation")

        await server.push(
            server.session_of("bob"),
            "SUBSCRIPTION",
            subscription_payload("channel-bob"),
        )
        subscription = await events.next("subscription")
        await subscription.send("thanks for subscribing")

        assert donation.channel == "channel-alice"
        assert subscription.channel == "channel-bob"
        sent = [
            (r["token"], r["body"]["message"])
            for r in server.requests_to("/open/v1/chats/send")
        ]
        assert sent == [
            ("token-alice", "thanks for the donation"),
            ("token-bob", "thanks for subscribing"),
        ]

    async def test_disconnecting_one_account_keeps_the_other_receiving(
        self, server, client, events
    ):
        alice = await client.get_user_client(server.add_account("alice"))
        bob = await client.get_user_client(server.add_account("bob"))
        await alice.connect(UserPermission(chat=True), addition_connect=True)
        await bob.connect(UserPermission(chat=True), addition_connect=True)

        await alice.disconnect()

        assert not alice.is_connected
        assert bob.is_connected
        await server.push(
            server.session_of("bob"), "CHAT", chat_payload("channel-bob", "still here")
        )
        message = await events.next("chat")
        assert message.content == "still here"

    async def test_unsubscribe_defaults_to_the_subscribed_session_key(
        self, server, client
    ):
        alice = await client.get_user_client(server.add_account("alice"))
        await alice.connect(UserPermission(chat=True), addition_connect=True)

        await alice.unsubscribe(UserPermission(chat=True))

        unsubscribes = server.requests_to("/open/v1/sessions/events/unsubscribe/")
        assert [r["query"]["sessionKey"] for r in unsubscribes] == [
            server.session_of("alice").key
        ]

    async def test_refresh_only_changes_that_accounts_token(
        self, server, client, events
    ):
        alice = await client.get_user_client(server.add_account("alice"))
        bob = await client.get_user_client(server.add_account("bob"))
        await alice.connect(UserPermission(chat=True), addition_connect=True)
        await bob.connect(UserPermission(chat=True), addition_connect=True)

        await alice.refresh()

        assert alice.access_token.access_token.startswith("token-alice-refreshed-")
        assert bob.access_token.access_token == "token-bob"

        await server.push(
            server.session_of("alice"),
            "CHAT",
            chat_payload("channel-alice", "after refresh"),
        )
        message = await events.next("chat")
        await message.send("reply after refresh")

        await server.push(
            server.session_of("bob"), "CHAT", chat_payload("channel-bob", "bob")
        )
        message = await events.next("chat")
        await message.send("reply from bob")

        sent = [r["token"] for r in server.requests_to("/open/v1/chats/send")]
        assert sent == [alice.access_token.access_token, "token-bob"]

    async def test_blocking_connect_returns_after_disconnect(
        self, server, client, events
    ):
        alice = await client.get_user_client(server.add_account("alice"))
        bob = await client.get_user_client(server.add_account("bob"))

        await alice.connect(UserPermission(chat=True), addition_connect=True)
        blocking_connect = asyncio.create_task(bob.connect(UserPermission(chat=True)))
        await wait_until(
            lambda: any(
                r["token"] == "token-bob"
                for r in server.requests_to("/open/v1/sessions/events/subscribe/")
            )
        )
        assert not blocking_connect.done()

        await server.push(
            server.session_of("alice"), "CHAT", chat_payload("channel-alice", "a")
        )
        await server.push(
            server.session_of("bob"), "CHAT", chat_payload("channel-bob", "b")
        )
        received = {(await events.next("chat")).content for _ in range(2)}
        assert received == {"a", "b"}

        await alice.disconnect()
        await bob.disconnect()
        await asyncio.wait_for(blocking_connect, timeout=3.0)

    async def test_channel_id_learned_from_subscribed_event_without_profile_scope(
        self, server, client
    ):
        alice = await client.get_user_client(
            server.add_account("alice", profile_scope=False)
        )
        assert alice.channel_id is None

        await alice.connect(UserPermission(chat=True), addition_connect=True)

        await wait_until(lambda: alice.channel_id is not None)
        assert alice.channel_id == "channel-alice"
        assert client.get_user_client_cached("channel-alice") is alice


@pytest.mark.asyncio
class TestMultiAccountClientSession:
    """Several accounts subscribed to one client session (`Client.connect`)."""

    async def test_client_connect_returns_session_key(self, server, client):
        session_id = await client.connect(addition_connect=True)

        assert session_id == server.session_of(None).key

    async def test_client_session_routes_each_channel_to_its_account(
        self, server, client, events
    ):
        alice = await client.get_user_client(server.add_account("alice"))
        bob = await client.get_user_client(server.add_account("bob"))
        await client.connect(addition_connect=True)
        session = server.session_of(None)

        await alice.subscribe(UserPermission(chat=True), session.key)
        await bob.subscribe(UserPermission(chat=True), session.key)

        await server.push(session, "CHAT", chat_payload("channel-alice", "to alice"))
        await server.push(session, "CHAT", chat_payload("channel-bob", "to bob"))
        for _ in range(2):
            message = await events.next("chat")
            await message.send(f"reply to {message.content}")

        sent = {
            (r["token"], r["body"]["message"])
            for r in server.requests_to("/open/v1/chats/send")
        }
        assert sent == {
            ("token-alice", "reply to to alice"),
            ("token-bob", "reply to to bob"),
        }

    async def test_client_session_without_profile_scope_still_routes(
        self, server, client, events
    ):
        alice = await client.get_user_client(
            server.add_account("alice", profile_scope=False)
        )
        await client.connect(addition_connect=True)
        session = server.session_of(None)

        await alice.subscribe(UserPermission(chat=True), session.key)
        await server.push(session, "CHAT", chat_payload("channel-alice", "to alice"))
        message = await events.next("chat")
        await message.send("reply")

        sent = [r["token"] for r in server.requests_to("/open/v1/chats/send")]
        assert sent == ["token-alice"]

    async def test_client_session_limit_is_ten(self, server, client):
        for _ in range(10):
            await client.connect(addition_connect=True)

        with pytest.raises(ChatConnectFailed):
            await client.connect(addition_connect=True)


@pytest.mark.asyncio
class TestMultiAccountConcurrency:
    """Two accounts at once: nothing one account does may stall the other."""

    async def test_accounts_connect_concurrently(self, server, client):
        alice = await client.get_user_client(server.add_account("alice"))
        bob = await client.get_user_client(server.add_account("bob"))

        await asyncio.wait_for(
            asyncio.gather(
                alice.connect(UserPermission(chat=True), addition_connect=True),
                bob.connect(UserPermission(chat=True), addition_connect=True),
            ),
            timeout=3.0,
        )

        assert alice.is_connected and bob.is_connected
        assert server.session_of("alice").key != server.session_of("bob").key

    async def test_slow_handler_does_not_block_other_account(self, server, client):
        release = asyncio.Event()
        received = asyncio.Queue()

        @client.event
        async def on_chat(message):
            await received.put(message.content)
            if message.channel == "channel-alice":
                await release.wait()

        alice = await client.get_user_client(server.add_account("alice"))
        bob = await client.get_user_client(server.add_account("bob"))
        await alice.connect(UserPermission(chat=True), addition_connect=True)
        await bob.connect(UserPermission(chat=True), addition_connect=True)

        await server.push(
            server.session_of("alice"), "CHAT", chat_payload("channel-alice", "slow")
        )
        assert await asyncio.wait_for(received.get(), timeout=2.0) == "slow"

        # alice's handler is still blocked; both sessions must keep delivering.
        await server.push(
            server.session_of("bob"), "CHAT", chat_payload("channel-bob", "bob")
        )
        await server.push(
            server.session_of("alice"),
            "CHAT",
            chat_payload("channel-alice", "alice again"),
        )
        received_while_blocked = {
            await asyncio.wait_for(received.get(), timeout=2.0) for _ in range(2)
        }
        assert received_while_blocked == {"bob", "alice again"}
        release.set()

    async def test_heartbeat_keeps_both_sessions_alive(self, server, client, events):
        server.ping_interval_ms = 50
        server.ping_timeout_ms = 500
        alice = await client.get_user_client(server.add_account("alice"))
        bob = await client.get_user_client(server.add_account("bob"))
        await alice.connect(UserPermission(chat=True), addition_connect=True)
        await bob.connect(UserPermission(chat=True), addition_connect=True)

        await asyncio.sleep(1.0)

        for name in ("alice", "bob"):
            assert server.session_of(name).pings >= 10
        for user_client in (alice, bob):
            gateway = user_client._gateway
            assert user_client.is_connected
            assert not gateway._ping_loop_task.done()
            assert not gateway._read_background_loop.done()

        await server.push(
            server.session_of("bob"), "CHAT", chat_payload("channel-bob", "after pings")
        )
        assert (await events.next("chat")).content == "after pings"

    async def test_burst_on_both_sessions_is_fully_delivered(
        self, server, client, events
    ):
        alice = await client.get_user_client(server.add_account("alice"))
        bob = await client.get_user_client(server.add_account("bob"))
        await alice.connect(UserPermission(chat=True), addition_connect=True)
        await bob.connect(UserPermission(chat=True), addition_connect=True)

        await asyncio.gather(
            *(
                server.push(
                    server.session_of(name),
                    "CHAT",
                    chat_payload(f"channel-{name}", f"{name}-{index}"),
                )
                for index in range(50)
                for name in ("alice", "bob")
            )
        )
        messages = [await events.next("chat") for _ in range(100)]
        await asyncio.gather(*(message.send(message.content) for message in messages))

        assert sorted(m.content for m in messages) == sorted(
            f"{name}-{index}" for index in range(50) for name in ("alice", "bob")
        )
        sent = server.requests_to("/open/v1/chats/send")
        assert len(sent) == 100
        for request in sent:
            name = request["body"]["message"].split("-")[0]
            assert request["token"] == f"token-{name}"

    async def test_wait_for_does_not_break_other_accounts(self, server, client, events):
        alice = await client.get_user_client(server.add_account("alice"))
        bob = await client.get_user_client(server.add_account("bob"))
        await alice.connect(UserPermission(chat=True), addition_connect=True)
        await bob.connect(UserPermission(chat=True), addition_connect=True)

        waiter = asyncio.ensure_future(client.wait_for("chat", timeout=2.0))
        await server.push(
            server.session_of("alice"), "CHAT", chat_payload("channel-alice", "first")
        )
        assert (await waiter).content == "first"
        assert (await events.next("chat")).content == "first"

        await server.push(
            server.session_of("bob"), "CHAT", chat_payload("channel-bob", "second")
        )
        try:
            message = await events.next("chat")
        except asyncio.TimeoutError:
            read_loop = bob._gateway._read_background_loop
            reason = read_loop.exception() if read_loop.done() else "still running"
            pytest.fail(
                f"bob's chat was never delivered after alice's wait_for resolved "
                f"(bob's read loop: {reason!r})"
            )
        assert message.content == "second"

    async def test_server_closing_one_session_does_not_freeze_other_account(
        self, server, client, events, monitor
    ):
        alice = await client.get_user_client(server.add_account("alice"))
        bob = await client.get_user_client(server.add_account("bob"))
        await alice.connect(
            UserPermission(chat=True), addition_connect=True, reconnect=False
        )
        await bob.connect(UserPermission(chat=True), addition_connect=True)

        await server.drop(server.session_of("alice"))
        await asyncio.sleep(0.2)

        assert not monitor.spinning, (
            "alice's read loop busy-looped on the closed websocket; without the test "
            "guard this freezes the event loop for every account"
        )
        await server.push(
            server.session_of("bob"), "CHAT", chat_payload("channel-bob", "still here")
        )
        assert (await events.next("chat")).content == "still here"
        assert not alice.is_connected

    async def test_connect_fails_when_session_closes_before_ready(
        self, server, client, monitor
    ):
        server.close_before_ready.add("alice")
        alice = await client.get_user_client(server.add_account("alice"))

        try:
            await asyncio.wait_for(
                alice.connect(UserPermission(chat=True), addition_connect=True),
                timeout=3.0,
            )
        except ChatConnectFailed:
            pass
        except asyncio.TimeoutError:
            pytest.fail(
                "UserClient.connect() was still waiting 3s after the session closed "
                f"(read loop busy-looped: {bool(monitor.spinning)})"
            )
        else:
            pytest.fail("connect() returned although the session never became ready")
