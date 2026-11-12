"""MIT License

Copyright (c) 2024-2025 gunyu1019

Error-path tests for `Client`, `UserClient` and `BaseEventManager` of the official
chzzkpy package: event handlers that raise, using a client outside of an async context,
refreshing and revoking the access token, creating user clients (also with a token that
lacks the "유저 정보 조회" scope), the OAuth2 login, and the rare branches of
reconnecting and disconnecting sessions.

The mock Chzzk server and fixtures are shared with `test_multi_account.py`; the server
is extended here with the authorization code grant and with failures to inject. The
waits between reconnection attempts are shortened for the tests. Nothing leaves the
machine: HTTP goes to the mock server, and the browser of the login is a `FakeBrowser`.
"""

import asyncio
import contextlib
import datetime
import logging
import types
from typing import Callable, Optional

import ahttp_client
import aiohttp
import pytest
import pytest_asyncio
from aiohttp import web
from aiohttp.test_utils import TestServer
from yarl import URL

import chzzkpy.client
from chzzkpy import AccessToken, Client, UserClient, UserPermission
from chzzkpy.client import BaseEventManager, _Subscriptions
from chzzkpy.error import (
    BadRequestException,
    ForbiddenException,
    HTTPException,
    NotFoundException,
    UnauthorizedException,
)
from chzzkpy.gateway import ChzzkGateway
from chzzkpy.oauth2 import ChzzkOAuth2Client

from test_multi_account import (  # noqa: F401
    CLIENT_ID,
    CLIENT_SECRET,
    MockChzzkServer,
    chat_payload,
    client,
    monitor,
    wait_until,
)
from test_oauth2 import TIMEOUT, FakeBrowser, find_free_port, is_listening
from test_reconnect import (  # noqa: F401
    INITIAL_DELAY,
    KINDS,
    MAX_DELAY,
    SETTLE,
    SUBSCRIBE_PATH,
    alice,
    assert_disconnected,
    assert_nothing_open,
    connected,
    connections,
    disconnect,
    hold,
    hold_stage,
    owner_of,
    reconnected_client,
    reconnected_user,
    reconnection,
    session_events,
    session_requests,
    start,
    start_blocking,
    subscriptions_on,
)

TOKEN_PATH = "/auth/v1/token"
STALE = datetime.timedelta(days=1, seconds=1)


# ---- mock server ----


class OAuthServer(MockChzzkServer):
    """The mock server, extended with the authorization code grant of `/auth/v1/token`
    and with failures to inject. Its routes are bound to the handlers of this class."""

    def __init__(self):
        super().__init__()
        # One-time authorization codes: code -> (account name, state).
        self.codes: dict[str, tuple[str, str]] = dict()
        # Statuses the next token requests are answered with, one per request.
        self.token_errors: list[int] = []
        # A status every request for the user information is answered with.
        self.users_me_status: Optional[int] = None
        # The credentials sent with every token request.
        self.token_headers: list[dict[str, Optional[str]]] = []

    def add_code(self, name: str, code: str, state: str) -> None:
        self.codes[code] = (name, state)

    async def handle_token(self, request: web.Request):
        record = await self._record(request)
        body = record["body"]
        self.token_headers.append(
            {
                name: request.headers.get(name)
                for name in ("Authorization", "Client-Id", "Client-Secret")
            }
        )
        if self.token_errors:
            return self._content(code=self.token_errors.pop(0), message="TOKEN_ERROR")

        if body.get("grantType") == "authorization_code":
            grant = self.codes.get(body.get("code"))
            if (
                grant is None
                or grant[1] != body.get("state")
                or body.get("clientId") != CLIENT_ID
                or body.get("clientSecret") != CLIENT_SECRET
            ):
                return self._content(code=401, message="INVALID_CODE")
            del self.codes[body["code"]]
            account = next(a for a in self.accounts.values() if a.name == grant[0])
            return self._issue_tokens(account, "issued")

        for account in self.accounts.values():
            if account.refresh_token == body.get("refreshToken"):
                return self._issue_tokens(account, "refreshed")
        return self._content(code=401, message="INVALID_REFRESH_TOKEN")

    def _issue_tokens(self, account, label: str):
        """Replaces the tokens of `account`, the way the refresh grant of the base does."""
        number = next(self._ids)
        self.accounts.pop(account.access_token, None)
        account.access_token = f"token-{account.name}-{label}-{number}"
        account.refresh_token = f"refresh-{account.name}-{label}-{number}"
        self.accounts[account.access_token] = account
        return self._content(
            {
                "accessToken": account.access_token,
                "refreshToken": account.refresh_token,
                "tokenType": "Bearer",
                "expiresIn": 86400,
            }
        )

    async def handle_users_me(self, request: web.Request):
        if self.users_me_status is not None:
            await self._record(request)
            return self._content(code=self.users_me_status, message="USER_INFO_ERROR")
        return await super().handle_users_me(request)


@pytest_asyncio.fixture
async def server():
    instance = OAuthServer()
    await instance.start()
    yield instance
    await instance.stop()


@pytest.fixture(autouse=True)
def fast_reconnect(monkeypatch):
    monkeypatch.setattr("chzzkpy.client._RECONNECT_INITIAL_DELAY", INITIAL_DELAY)
    monkeypatch.setattr("chzzkpy.client._RECONNECT_MAX_DELAY", MAX_DELAY)


@pytest.fixture
def api_at_mock_server(monkeypatch, server):
    """Points the `ChzzkOpenAPISession` of a client that sets itself up at the mock
    server, instead of the Chzzk Open API."""
    original_init = ahttp_client.Session.__init__

    def init(self, base_url, **kwargs):
        original_init(self, server.url, **kwargs)

    monkeypatch.setattr(ahttp_client.Session, "__init__", init)


class RecordingHandler(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord):
        self.records.append(record)


@pytest.fixture
def log_records():
    logger = logging.getLogger("chzzkpy.client")
    handler = RecordingHandler()
    level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    yield handler.records
    logger.removeHandler(handler)
    logger.setLevel(level)


def logged(records: list[logging.LogRecord], text: str) -> list[logging.LogRecord]:
    """The warnings and errors containing `text`."""
    return [
        record
        for record in records
        if record.levelno >= logging.WARNING and text in record.getMessage()
    ]


def make_stale(user_client: UserClient, age: datetime.timedelta = STALE) -> None:
    """Makes the access token of `user_client` older than a day."""
    user_client._token_generated_at = datetime.datetime.now() - age


def token_requests(server) -> list[dict]:
    return server.requests_to(TOKEN_PATH)


# ---- event handlers ----


def create_event_manager() -> BaseEventManager:
    return BaseEventManager(asyncio.get_running_loop())


async def run_scheduled_events():
    """Let event handler tasks, and the error events they dispatch, run to completion."""
    for _ in range(5):
        await asyncio.sleep(0)


def scheduled_tasks(name: str) -> list[asyncio.Task]:
    return [task for task in asyncio.all_tasks() if task.get_name() == name]


@pytest.mark.asyncio
class TestHandlerErrors:
    async def test_failing_handler_is_logged_and_dispatched_as_error(self, log_records):
        manager = create_event_manager()
        error = ValueError("handler broke")
        errors = []

        @manager.event
        async def on_chat(message, *, flag):
            raise error

        @manager.event
        async def on_error(exc, *args, **kwargs):
            errors.append((exc, args, kwargs))

        manager.dispatch("chat", "hello", flag=True)
        await run_scheduled_events()

        # The error handler gets the exception, then the arguments of the failed event.
        assert errors == [(error, ("hello",), {"flag": True})]
        assert errors[0][0] is error
        (record,) = logged(log_records, "Ignoring exception in on_chat")
        assert record.levelno == logging.ERROR
        assert record.exc_info[1] is error

    async def test_failing_handler_without_an_error_handler_is_only_logged(
        self, log_records
    ):
        manager = create_event_manager()

        @manager.event
        async def on_chat(message):
            raise ValueError("handler broke")

        manager.dispatch("chat", "hello")
        (task,) = scheduled_tasks("chzzk.py: on_chat")
        await run_scheduled_events()

        # The exception doesn't stay on the task as "never retrieved".
        assert task.done() and task.exception() is None
        assert len(logged(log_records, "Ignoring exception in on_chat")) == 1

    async def test_failing_handler_does_not_stop_other_handlers(self):
        manager = create_event_manager()
        handled = []

        @manager.event
        async def on_chat(message):
            raise ValueError("handler broke")

        @manager.event
        async def on_chat(message):  # noqa: F811
            handled.append(message)

        waiter = asyncio.ensure_future(manager.wait_for("chat"))
        manager.dispatch("chat", "first")
        manager.dispatch("chat", "second")
        await run_scheduled_events()

        assert handled == ["first", "second"]
        assert await waiter == "first"

    @pytest.mark.parametrize("how", ["task_cancelled", "handler_raises"])
    async def test_cancelled_handler_is_ignored(self, how, log_records):
        manager = create_event_manager()
        started = asyncio.Event()
        errors = []

        @manager.event
        async def on_chat(message):
            started.set()
            if how == "handler_raises":
                raise asyncio.CancelledError()
            await asyncio.Event().wait()

        @manager.event
        async def on_error(exc, *args):
            errors.append(exc)

        manager.dispatch("chat", "hello")
        (task,) = scheduled_tasks("chzzk.py: on_chat")
        await started.wait()
        if how == "task_cancelled":
            task.cancel()
        await asyncio.wait({task}, timeout=1.0)
        await run_scheduled_events()

        # The cancellation ends the handler without being an error.
        assert task.done() and not task.cancelled() and task.exception() is None
        assert errors == []
        assert logged(log_records, "Ignoring exception") == []

    async def test_failing_error_handler_does_not_break_dispatch(self, log_records):
        manager = create_event_manager()
        handled = []
        errors = []

        @manager.event
        async def on_chat(message):
            handled.append(message)
            if message == "first":
                raise ValueError("handler broke")

        @manager.event
        async def on_error(exc, *args):
            errors.append(exc)
            if len(errors) == 1:
                raise RuntimeError("error handler broke")

        manager.dispatch("chat", "first")
        await run_scheduled_events()
        manager.dispatch("chat", "second")
        await run_scheduled_events()

        assert isinstance(errors[0], ValueError)
        assert handled == ["first", "second"]
        assert len(logged(log_records, "Ignoring exception in on_error")) >= 1

    async def test_failing_error_handler_is_not_called_for_its_own_failure(self):
        manager = create_event_manager()
        calls = []

        @manager.event
        async def on_chat(message):
            raise ValueError("handler broke")

        @manager.event
        async def on_error(exc, *args):
            calls.append((exc, args))
            # Without the limit the failures would be dispatched forever.
            if len(calls) < 20:
                raise RuntimeError("error handler broke")

        manager.dispatch("chat", "hello")
        await run_scheduled_events()
        await asyncio.sleep(0.05)

        assert len(calls) == 1

    async def test_failing_error_handler_is_logged_once_and_not_dispatched(
        self, log_records
    ):
        manager = create_event_manager()
        chat_error = ValueError("handler broke")
        error_handler_error = RuntimeError("error handler broke")
        calls = []

        @manager.event
        async def on_chat(message):
            raise chat_error

        @manager.event
        async def on_error(exc, *args):
            calls.append(exc)
            raise error_handler_error

        manager.dispatch("chat", "hello")
        await run_scheduled_events()
        await asyncio.sleep(0.05)

        assert calls == [chat_error]
        (record,) = logged(log_records, "Ignoring exception in on_error")
        assert record.levelno == logging.ERROR
        assert record.exc_info[1] is error_handler_error
        assert record.exc_info[2] is not None
        (record,) = logged(log_records, "Ignoring exception in on_chat")
        assert record.exc_info[1] is chat_error
        assert scheduled_tasks("chzzk.py: on_error") == []

    async def test_failing_error_handler_does_not_stop_the_other_error_handlers(self):
        manager = create_event_manager()
        failures = []
        received = []

        @manager.event
        async def on_chat(message):
            raise ValueError("handler broke")

        @manager.event
        async def on_error(exc, *args):
            failures.append(exc)
            raise RuntimeError("error handler broke")

        @manager.event
        async def on_error(exc, *args):  # noqa: F811
            received.append((exc, args))

        manager.dispatch("chat", "hello")
        await run_scheduled_events()
        await asyncio.sleep(0.05)

        assert len(failures) == 1 and failures[0] is received[0][0]
        assert isinstance(received[0][0], ValueError)
        assert [args for _, args in received] == [("hello",)]

    async def test_failing_error_handler_still_receives_later_errors(self):
        manager = create_event_manager()
        errors = []

        @manager.event
        async def on_chat(message):
            raise ValueError(message)

        @manager.event
        async def on_error(exc, *args):
            errors.append((str(exc), args))
            if len(errors) == 1:
                raise RuntimeError("error handler broke")

        for message in ("first", "second"):
            manager.dispatch("chat", message)
            await run_scheduled_events()
            await asyncio.sleep(0.02)

        assert errors == [("first", ("first",)), ("second", ("second",))]

    async def test_failing_error_handler_does_not_dispatch_to_error_listeners(self):
        manager = create_event_manager()
        error = ValueError("handler broke")

        @manager.event
        async def on_chat(message):
            raise error

        @manager.event
        async def on_error(exc, *args):
            raise RuntimeError("error handler broke")

        listener = asyncio.ensure_future(manager.wait_for("error"))
        manager.dispatch("chat", "hello")
        await run_scheduled_events()

        # The listener gets the failure of the chat handler, as before.
        failure, message = await asyncio.wait_for(listener, timeout=1.0)
        assert failure is error and message == "hello"
        # Nothing is dispatched for the failure of the error handler.
        with pytest.raises(asyncio.TimeoutError):
            await manager.wait_for("error", timeout=0.05)


@pytest.mark.asyncio
class TestHandlerErrorsOnTheGateway:
    async def test_failing_handler_does_not_stop_the_read_loop(
        self, server, client, alice
    ):
        handled = []
        errors = []

        @client.event
        async def on_chat(message):
            raise ValueError(message.content)

        @client.event
        async def on_chat(message):  # noqa: F811
            handled.append(message.content)

        @client.event
        async def on_error(exc, message):
            errors.append((str(exc), message.content))

        await alice.connect(UserPermission(chat=True), addition_connect=True)
        gateway = alice._gateway
        session = server.session_of("alice")
        for text in ("first", "second", "third"):
            await server.push(session, "CHAT", chat_payload("channel-alice", text))

        await wait_until(lambda: len(handled) == 3 and len(errors) == 3)

        assert sorted(handled) == ["first", "second", "third"]
        assert sorted(errors) == [
            ("first", "first"),
            ("second", "second"),
            ("third", "third"),
        ]
        assert alice.is_connected and not gateway._read_background_loop.done()

    async def test_failing_on_connect_handler_does_not_fail_connect(
        self, server, client
    ):
        errors = []

        @client.event
        async def on_connect(session_id):
            raise RuntimeError("handler broke")

        @client.event
        async def on_error(exc, session_id):
            errors.append((str(exc), session_id))

        session_id = await asyncio.wait_for(
            client.connect(addition_connect=True), timeout=2.0
        )
        await wait_until(lambda: errors)

        assert errors == [("handler broke", session_id)]
        gateway = client._gateway[session_id]
        assert gateway.is_connected and not gateway._read_background_loop.done()
        waiter = asyncio.ensure_future(client.wait_for("chat", timeout=2.0))
        await server.push(
            server.sessions[session_id], "CHAT", chat_payload("channel-x", "after")
        )
        assert (await waiter).content == "after"


# ---- using a client outside of an async context ----


class TestLoopOutsideAsyncContext:
    @pytest.mark.parametrize(
        "attribute", ["create_task", "create_future", "call_later", "time"]
    )
    def test_loop_cannot_be_used_before_setup(self, attribute):
        client = Client(CLIENT_ID, CLIENT_SECRET)

        assert isinstance(client.loop, chzzkpy.client._LoopSentinel)
        with pytest.raises(AttributeError, match="non-async contexts"):
            getattr(client.loop, attribute)

    def test_waiting_for_an_event_before_setup_raises(self):
        client = Client(CLIENT_ID, CLIENT_SECRET)

        with pytest.raises(AttributeError, match="non-async contexts"):
            client.wait_for("chat")

        assert client._listeners == {}


@pytest.mark.asyncio
class TestAsyncSetup:
    async def test_setup_binds_the_running_loop(self):
        client = Client(CLIENT_ID, CLIENT_SECRET)
        assert client.http is None

        await client._async_setup_hook()
        try:
            assert client.loop is asyncio.get_running_loop()
            assert client.http is not None and not client.http.closed
        finally:
            await client.http.close()

    async def test_setup_rejects_a_loop_that_is_not_running_the_caller(self):
        other_loop = asyncio.new_event_loop()
        try:
            client = Client(CLIENT_ID, CLIENT_SECRET, loop=other_loop)

            with pytest.raises(RuntimeError, match="asynchronous context"):
                await client._async_setup_hook()

            assert client.http is None
        finally:
            other_loop.close()

    async def test_api_methods_do_not_request_when_setup_fails(
        self, server, api_at_mock_server
    ):
        other_loop = asyncio.new_event_loop()
        try:
            client = Client(CLIENT_ID, CLIENT_SECRET, loop=other_loop)

            with pytest.raises(RuntimeError, match="asynchronous context"):
                await client.generate_access_token("code", "state")
            with pytest.raises(RuntimeError, match="asynchronous context"):
                await client.get_user_client(
                    AccessToken(access_token="a", refresh_token="r", expires_in=1)
                )

            assert client.http is None and client.user_client == []
            assert server.requests == []
        finally:
            other_loop.close()

    async def test_api_methods_set_the_client_up_on_first_use(
        self, server, api_at_mock_server
    ):
        server.add_account("alice")
        server.add_code("alice", "code", "state")
        client = Client(CLIENT_ID, CLIENT_SECRET)
        assert client.http is None
        assert isinstance(client.loop, chzzkpy.client._LoopSentinel)

        try:
            token = await client.generate_access_token("code", "state")
            http = client.http

            assert client.loop is asyncio.get_running_loop()
            assert http is not None and http.base_url == server.url
            assert token.access_token.startswith("token-alice-issued-")
            # It's set up once.
            await client.refresh_access_token(token.refresh_token)
            assert client.http is http
        finally:
            await client.http.close()


# ---- the access token ----


async def call_fetch_self(user, session_key):
    await user.fetch_self()


async def call_send_message(user, session_key):
    await user.send_message("hello")


async def call_connect(user, session_key):
    await user.connect(UserPermission(chat=True), addition_connect=True)


async def call_subscribe(user, session_key):
    await user.subscribe(UserPermission(donation=True), session_key)


async def call_unsubscribe(user, session_key):
    await user.unsubscribe(UserPermission(chat=True), session_key)


REFRESHABLE_CALLS: dict[str, Callable] = {
    "fetch_self": call_fetch_self,
    "send_message": call_send_message,
    "connect": call_connect,
    "subscribe": call_subscribe,
    "unsubscribe": call_unsubscribe,
}
NEEDS_SESSION = ("subscribe", "unsubscribe")


@pytest.mark.asyncio
class TestRefreshable:
    @pytest.mark.parametrize("method", REFRESHABLE_CALLS)
    async def test_old_token_is_refreshed_before_the_call(self, method, server, alice):
        session_key = None
        if method in NEEDS_SESSION:
            session_key = await alice.connect(
                UserPermission(chat=True), addition_connect=True
            )
        old = alice.access_token
        make_stale(alice)
        before = len(server.requests)

        await REFRESHABLE_CALLS[method](alice, session_key)

        made = server.requests[before:]
        refreshed = alice.access_token
        assert refreshed is not old
        assert refreshed.access_token.startswith("token-alice-refreshed-")
        assert made[0]["path"] == TOKEN_PATH
        assert made[0]["body"]["grantType"] == "refresh_token"
        assert made[0]["body"]["refreshToken"] == old.refresh_token
        # The call itself goes out with the refreshed token, and refreshing is done once.
        assert len(made) > 1
        assert all(request["token"] == refreshed.access_token for request in made[1:])
        assert len(token_requests(server)) == 1
        assert datetime.datetime.now() - alice._token_generated_at < STALE

    @pytest.mark.parametrize(
        "age, refreshed",
        [
            (datetime.timedelta(hours=23, minutes=59), False),
            (datetime.timedelta(days=1), True),
            (datetime.timedelta(days=30), True),
        ],
    )
    async def test_token_is_refreshed_once_it_is_a_day_old(
        self, age, refreshed, server, alice
    ):
        make_stale(alice, age)

        await alice.send_message("hello")

        assert len(token_requests(server)) == int(refreshed)
        (sent,) = server.requests_to("/open/v1/chats/send")
        expected = "token-alice-refreshed-" if refreshed else "token-alice"
        assert sent["token"].startswith(expected)

    @pytest.mark.parametrize("method", ["send_message", "connect"])
    @pytest.mark.parametrize(
        "status, error", [(401, UnauthorizedException), (500, HTTPException)]
    )
    async def test_failing_refresh_propagates_and_skips_the_call(
        self, method, status, error, server, alice
    ):
        old = alice.access_token
        make_stale(alice)
        stale_at = alice._token_generated_at
        server.token_errors = [status]

        with pytest.raises(error):
            await REFRESHABLE_CALLS[method](alice, None)

        assert alice.access_token is old and alice._connection.access_token is old
        assert alice._token_generated_at == stale_at
        assert server.requests_to("/open/v1/chats/send") == []
        assert server.requests_to("/open/v1/sessions/auth") == []
        assert alice._gateway is None

        # The token is still old, so the next call refreshes it again.
        await REFRESHABLE_CALLS[method](alice, None)
        assert alice.access_token is not old
        assert len(token_requests(server)) == 2

    async def test_refreshed_token_is_used_by_the_connection_after_connect(
        self, server, client, alice
    ):
        replies = []

        @client.event
        async def on_chat(message):
            replies.append(await message.send("reply"))

        make_stale(alice)
        await alice.connect(UserPermission(chat=True), addition_connect=True)
        refreshed = alice.access_token

        await server.push(
            server.session_of("alice"), "CHAT", chat_payload("channel-alice", "hi")
        )
        await wait_until(lambda: replies)

        (sent,) = server.requests_to("/open/v1/chats/send")
        assert sent["token"] == refreshed.access_token != "token-alice"
        assert alice._connection.access_token is refreshed


@pytest.mark.asyncio
class TestRefresh:
    async def test_refresh_replaces_the_token_the_connection_uses(self, server, alice):
        old = alice.access_token
        make_stale(alice, datetime.timedelta(minutes=10))
        generated_at = alice._token_generated_at

        await alice.refresh()

        new = alice.access_token
        assert new is not old
        assert alice._connection.access_token is new
        assert alice._token_generated_at > generated_at
        assert alice.is_expired is False
        request = token_requests(server)[-1]
        assert request["method"] == "POST"
        assert {k: v for k, v in request["body"].items() if v is not None} == {
            "grantType": "refresh_token",
            "clientId": CLIENT_ID,
            "clientSecret": CLIENT_SECRET,
            "refreshToken": old.refresh_token,
        }
        assert server.token_headers[-1] == {
            "Authorization": None,
            "Client-Id": CLIENT_ID,
            "Client-Secret": CLIENT_SECRET,
        }

        # The refresh token is rotated, so the next refresh sends the new one.
        await alice.refresh()
        assert token_requests(server)[-1]["body"]["refreshToken"] == new.refresh_token

    @pytest.mark.parametrize(
        "status, error", [(401, UnauthorizedException), (500, HTTPException)]
    )
    async def test_failed_refresh_keeps_the_token(self, status, error, server, alice):
        old = alice.access_token
        make_stale(alice, datetime.timedelta(minutes=10))
        generated_at = alice._token_generated_at
        server.token_errors = [status]

        with pytest.raises(error):
            await alice.refresh()

        assert alice.access_token is old
        assert alice._connection.access_token is old
        assert alice._token_generated_at == generated_at

    async def test_rejected_refresh_token_raises(self, server, alice):
        # The server doesn't know the account any more.
        del server.accounts["token-alice"]

        with pytest.raises(UnauthorizedException):
            await alice.refresh()

        assert alice.access_token.access_token == "token-alice"


@pytest_asyncio.fixture
async def revoke_endpoint(client):
    """Points the client at an endpoint that only serves `/auth/v1/token/revoke`."""
    requests: list[dict] = []
    statuses: list[int] = []

    async def handle(request: web.Request):
        requests.append(
            {
                "method": request.method,
                "path": request.path,
                "headers": dict(request.headers),
                "body": await request.json(),
            }
        )
        status = statuses.pop(0) if statuses else 200
        return web.json_response(
            {"code": status, "message": "REVOKE_ERROR", "content": None}, status=status
        )

    app = web.Application()
    app.router.add_post("/auth/v1/token/revoke", handle)
    revoke_server = TestServer(app)
    await revoke_server.start_server()
    await client.http.session.close()
    client.http.session = aiohttp.ClientSession(
        f"http://{revoke_server.host}:{revoke_server.port}"
    )

    yield types.SimpleNamespace(requests=requests, statuses=statuses)
    await revoke_server.close()


@pytest.mark.asyncio
class TestRevoke:
    @staticmethod
    def make_user_client(client) -> UserClient:
        return UserClient(
            client,
            AccessToken(
                access_token="token-x", refresh_token="refresh-x", expires_in=1
            ),
        )

    async def test_revoke_sends_the_access_token_with_the_client_credentials(
        self, client, revoke_endpoint
    ):
        user_client = self.make_user_client(client)

        await user_client.revoke()

        (request,) = revoke_endpoint.requests
        assert request["method"] == "POST"
        assert {k: v for k, v in request["body"].items() if v is not None} == {
            "clientId": CLIENT_ID,
            "clientSecret": CLIENT_SECRET,
            "token": "token-x",
            "tokenTypeHint": "access_token",
        }
        assert request["headers"]["Client-Id"] == CLIENT_ID
        assert request["headers"]["Client-Secret"] == CLIENT_SECRET
        assert "Authorization" not in request["headers"]

    @pytest.mark.parametrize(
        "status, error",
        [
            (400, BadRequestException),
            (401, UnauthorizedException),
            (500, HTTPException),
        ],
    )
    async def test_rejected_revoke_raises(self, status, error, client, revoke_endpoint):
        user_client = self.make_user_client(client)
        token = user_client.access_token
        revoke_endpoint.statuses.append(status)

        with pytest.raises(error):
            await user_client.revoke()

        assert user_client.access_token is token
        assert len(revoke_endpoint.requests) == 1


@pytest.mark.asyncio
class TestInvalidAccessToken:
    @pytest.mark.parametrize(
        "token", ["token-string", None, {"access_token": "a", "refresh_token": "r"}]
    )
    async def test_user_client_requires_an_access_token(self, token, client):
        with pytest.raises(TypeError, match="must be AccessToken type"):
            UserClient(client, token)

    async def test_get_user_client_rejects_a_raw_token(self, server, client):
        with pytest.raises(TypeError, match="must be AccessToken type"):
            await client.get_user_client("token-alice")

        assert client.user_client == []
        assert server.requests == []


# ---- creating user clients ----

CREATORS = ["generate_user_client", "refresh_user_client", "get_user_client"]
TOKEN_PREFIX = {
    "generate_user_client": "token-alice-issued-",
    "refresh_user_client": "token-alice-refreshed-",
    "get_user_client": "token-alice",
}


async def create_user_client(creator: str, server, client, **account) -> UserClient:
    token = server.add_account("alice", **account)
    if creator == "generate_user_client":
        server.add_code("alice", "code-alice", "state-alice")
        return await client.generate_user_client("code-alice", "state-alice")
    if creator == "refresh_user_client":
        return await client.refresh_user_client(token.refresh_token)
    return await client.get_user_client(token)


@pytest.mark.asyncio
class TestGenerateAccessToken:
    async def test_authorization_code_is_exchanged_with_the_client_credentials(
        self, server, client
    ):
        server.add_account("alice")
        server.add_code("alice", "code-alice", "state-alice")

        token = await client.generate_access_token("code-alice", "state-alice")

        assert isinstance(token, AccessToken)
        assert token.access_token.startswith("token-alice-issued-")
        assert token.refresh_token.startswith("refresh-alice-issued-")
        assert token.expires_in == 86400
        (request,) = token_requests(server)
        assert request["method"] == "POST"
        assert {k: v for k, v in request["body"].items() if v is not None} == {
            "grantType": "authorization_code",
            "clientId": CLIENT_ID,
            "clientSecret": CLIENT_SECRET,
            "code": "code-alice",
            "state": "state-alice",
        }
        assert server.token_headers == [
            {
                "Authorization": None,
                "Client-Id": CLIENT_ID,
                "Client-Secret": CLIENT_SECRET,
            }
        ]
        # Only the token is made: no user client is registered.
        assert client.user_client == []

    @pytest.mark.parametrize(
        "code, state",
        [("unknown-code", "state-alice"), ("code-alice", "another-state")],
    )
    async def test_rejected_code_raises(self, code, state, server, client):
        server.add_account("alice")
        server.add_code("alice", "code-alice", "state-alice")

        with pytest.raises(UnauthorizedException, match="INVALID_CODE"):
            await client.generate_access_token(code, state)
        with pytest.raises(UnauthorizedException, match="INVALID_CODE"):
            await client.generate_user_client(code, state)

        assert client.user_client == []
        assert len(server.requests_to("/open/v1/users/me")) == 0

    async def test_code_can_be_exchanged_once(self, server, client):
        server.add_account("alice")
        server.add_code("alice", "code-alice", "state-alice")
        await client.generate_access_token("code-alice", "state-alice")

        with pytest.raises(UnauthorizedException):
            await client.generate_access_token("code-alice", "state-alice")

    @pytest.mark.parametrize(
        "status, error", [(400, BadRequestException), (500, HTTPException)]
    )
    async def test_server_errors_raise(self, status, error, server, client):
        server.add_account("alice")
        server.add_code("alice", "code-alice", "state-alice")
        server.token_errors = [status]

        with pytest.raises(error):
            await client.generate_access_token("code-alice", "state-alice")


@pytest.mark.asyncio
class TestRefreshAccessToken:
    async def test_refresh_token_is_exchanged_with_the_client_credentials(
        self, server, client
    ):
        token = server.add_account("alice")

        refreshed = await client.refresh_access_token(token.refresh_token)

        assert refreshed.access_token.startswith("token-alice-refreshed-")
        (request,) = token_requests(server)
        assert {k: v for k, v in request["body"].items() if v is not None} == {
            "grantType": "refresh_token",
            "clientId": CLIENT_ID,
            "clientSecret": CLIENT_SECRET,
            "refreshToken": token.refresh_token,
        }
        assert server.token_headers[-1]["Client-Id"] == CLIENT_ID
        assert client.user_client == []

    async def test_rejected_refresh_token_raises(self, server, client):
        server.add_account("alice")

        with pytest.raises(UnauthorizedException, match="INVALID_REFRESH_TOKEN"):
            await client.refresh_access_token("unknown-refresh-token")
        with pytest.raises(UnauthorizedException, match="INVALID_REFRESH_TOKEN"):
            await client.refresh_user_client("unknown-refresh-token")

        assert client.user_client == []


@pytest.mark.asyncio
class TestCreateUserClient:
    @pytest.mark.parametrize("creator", CREATORS)
    async def test_user_client_is_registered_with_its_channel(
        self, creator, server, client
    ):
        user_client = await create_user_client(creator, server, client)

        assert isinstance(user_client, UserClient)
        assert user_client.access_token.access_token.startswith(TOKEN_PREFIX[creator])
        assert user_client.channel_id == "channel-alice"
        assert user_client.channel_name == "alice"
        assert client.user_client == [user_client]
        assert client.get_user_client_cached("channel-alice") is user_client

    @pytest.mark.parametrize("creator", CREATORS)
    async def test_token_without_the_user_info_scope_still_makes_a_client(
        self, creator, server, client
    ):
        user_client = await create_user_client(
            creator, server, client, profile_scope=False
        )

        assert isinstance(user_client, UserClient)
        assert user_client.channel_id is None and user_client.channel_name is None
        assert client.user_client == [user_client]
        assert client.get_user_client_cached("channel-alice") is None
        assert len(server.requests_to("/open/v1/users/me")) == 1
        # The client is usable: the scope is only required to know its channel.
        await user_client.send_message("hello")
        assert len(server.requests_to("/open/v1/chats/send")) == 1

    @pytest.mark.parametrize("creator", CREATORS)
    @pytest.mark.parametrize(
        "status, error",
        [
            (401, UnauthorizedException),
            (404, NotFoundException),
            (500, HTTPException),
        ],
    )
    async def test_other_errors_of_fetch_self_propagate(
        self, creator, status, error, server, client
    ):
        server.users_me_status = status

        with pytest.raises(error):
            await create_user_client(creator, server, client)

        assert client.user_client == []
        assert len(server.requests_to("/open/v1/users/me")) == 1

    async def test_each_call_makes_another_user_client(self, server, client):
        token = server.add_account("alice")

        first = await client.get_user_client(token)
        second = await client.get_user_client(token)

        assert first is not second
        assert client.user_client == [first, second]
        assert client.get_user_client_cached("channel-alice") is first


@pytest.fixture
def browser(monkeypatch):
    fake = FakeBrowser([])
    monkeypatch.setattr(ChzzkOAuth2Client, "_open_webbrowser", fake.open)
    return fake


@pytest.mark.asyncio
class TestLogin:
    LOGIN = {"remote_host": "127.0.0.1"}

    async def test_login_returns_the_user_client_of_the_authorized_account(
        self, server, client, browser
    ):
        server.add_account("alice")
        # The fake browser sends the code "code-<state>"; the default state is used.
        server.add_code("alice", "code-chzzkpy_authorization", "chzzkpy_authorization")
        port = find_free_port()

        user_client = await asyncio.wait_for(
            client.login(remote_port=port, **self.LOGIN), timeout=TIMEOUT
        )

        assert client.user_client == [user_client]
        assert user_client.channel_id == "channel-alice"
        assert user_client.access_token.access_token.startswith("token-alice-issued-")
        query = URL(browser.urls["chzzkpy_authorization"]).query
        assert query["clientId"] == CLIENT_ID
        assert query["redirectUri"] == f"http://127.0.0.1:{port}/"
        assert browser.replies == [(200, "Success to login!")]
        assert not is_listening(port)

    async def test_login_options_are_used(self, server, client, browser):
        server.add_account("alice")
        server.add_code("alice", "code-my-state", "my-state")
        port = find_free_port()

        user_client = await asyncio.wait_for(
            client.login(
                state="my-state",
                remote_port=port,
                remote_path="/callback",
                success_response=web.Response(text="Welcome"),
                **self.LOGIN,
            ),
            timeout=TIMEOUT,
        )

        assert user_client.channel_id == "channel-alice"
        query = URL(browser.urls["my-state"]).query
        assert query["redirectUri"] == f"http://127.0.0.1:{port}/callback"
        assert query["state"] == "my-state"
        assert browser.replies == [(200, "Welcome")]

    async def test_login_with_a_token_without_the_user_info_scope(
        self, server, client, browser
    ):
        server.add_account("alice", profile_scope=False)
        server.add_code("alice", "code-s", "s")

        user_client = await asyncio.wait_for(
            client.login(state="s", remote_port=find_free_port(), **self.LOGIN),
            timeout=TIMEOUT,
        )

        assert user_client.channel_id is None
        assert client.user_client == [user_client]

    async def test_login_raises_when_the_code_is_rejected(
        self, server, client, browser
    ):
        server.add_account("alice")
        port = find_free_port()

        with pytest.raises(UnauthorizedException, match="INVALID_CODE"):
            await asyncio.wait_for(
                client.login(state="s", remote_port=port, **self.LOGIN), timeout=TIMEOUT
            )
        await browser.settle()

        assert browser.replies == [(500, "Failed to login. Please run login() again.")]
        assert client.user_client == []
        assert not is_listening(port)

    async def test_login_raises_when_the_user_info_request_fails(
        self, server, client, browser
    ):
        server.add_account("alice")
        server.add_code("alice", "code-s", "s")
        server.users_me_status = 500

        with pytest.raises(HTTPException):
            await asyncio.wait_for(
                client.login(state="s", remote_port=find_free_port(), **self.LOGIN),
                timeout=TIMEOUT,
            )

        assert client.user_client == []

    @pytest.mark.parametrize("ssl, scheme", [(False, "http"), (True, "https")])
    async def test_ssl_option_selects_the_scheme_of_the_redirect_url(
        self, ssl, scheme, client, browser
    ):
        browser.hold.add("s")
        port = find_free_port()
        login = asyncio.ensure_future(
            client.login(state="s", remote_port=port, ssl=ssl, **self.LOGIN)
        )
        await browser.opened("s")

        query = URL(browser.urls["s"]).query
        assert query["redirectUri"] == f"{scheme}://127.0.0.1:{port}/"

        login.cancel()
        await asyncio.wait({login}, timeout=TIMEOUT)
        assert login.cancelled()
        assert client.user_client == []
        assert not is_listening(port)


# ---- subscribing ----


@pytest.mark.asyncio
class TestSubscribeErrors:
    @pytest.mark.parametrize("method", ["subscribe", "unsubscribe"])
    async def test_session_is_required(self, method, server, alice):
        with pytest.raises(TypeError, match="session_id is not filled"):
            await getattr(alice, method)(UserPermission(chat=True))

        assert server.requests_to(SUBSCRIBE_PATH) == []
        assert server.requests_to("/open/v1/sessions/events/unsubscribe/") == []

    async def test_unknown_session_raises_without_being_tracked(self, server, alice):
        session_key = await alice.connect(
            UserPermission(chat=True), addition_connect=True
        )

        with pytest.raises(NotFoundException, match="Unknown session key"):
            await alice.subscribe(UserPermission(donation=True), "unknown-session")
        with pytest.raises(NotFoundException, match="Unknown session key"):
            await alice.unsubscribe(UserPermission(chat=True), "unknown-session")

        requests = server.requests_to("/open/v1/sessions/events/")
        assert [request["query"]["sessionKey"] for request in requests[1:]] == [
            "unknown-session",
            "unknown-session",
        ]
        # What it has subscribed on its own session is untouched.
        assert alice._subscriptions.events == UserPermission(chat=True)
        assert alice._subscriptions._session_id == session_key

    async def test_session_of_another_user_client_is_requested_without_tracking(
        self, server, client, alice
    ):
        key = await alice.connect(UserPermission(chat=True), addition_connect=True)
        # Another user client of the same account: the session isn't one of its own.
        twin = await client.get_user_client(alice.access_token)

        await twin.subscribe(UserPermission(donation=True), key)
        await twin.unsubscribe(UserPermission(chat=True), key)

        assert server.sessions[key].subscriptions == [("donation", "channel-alice")]
        assert twin._subscriptions.events == UserPermission()
        assert alice._subscriptions.events == UserPermission(chat=True)

    @pytest.mark.parametrize("kind", KINDS)
    async def test_rejected_subscription_is_not_remembered(
        self, kind, server, client, alice
    ):
        key = await start(kind, client, alice)
        server.subscribe_errors = [403]

        with pytest.raises(ForbiddenException):
            await alice.subscribe(UserPermission(donation=True), key)

        # Reconnecting subscribes only what was subscribed.
        await server.drop(server.sessions[key])
        second_key = (
            await reconnected_user(alice, key)
            if kind == "user"
            else await reconnected_client(client, key)
        )
        assert subscriptions_on(server, second_key) == {("chat", "token-alice")}


@pytest.mark.asyncio
class TestSubscriptions:
    async def test_late_unsubscribe_on_an_old_session_keeps_the_new_session_tracked(
        self,
    ):
        subscriptions = _Subscriptions("old")
        request = await subscriptions.begin("chat", "old")
        subscriptions.end("chat", "old", request, True)
        # The session is reconnected, and subscribed again.
        subscriptions.start("new")
        request = await subscriptions.begin("chat", "new")
        subscriptions.end("chat", "new", request, True)

        # The response of an unsubscribe request sent on the old session comes late.
        subscriptions.unsubscribed("chat", "old")

        # The event isn't subscribed again on later reconnections, but the new session
        # still has it subscribed.
        assert subscriptions.events == UserPermission()
        assert await subscriptions.begin("chat", "new") is None


# ---- reconnecting and disconnecting ----


async def reconnected(kind: str, client, alice, previous_key: str) -> str:
    if kind == "user":
        return await reconnected_user(alice, previous_key)
    return await reconnected_client(client, previous_key)


def balanced(session_events) -> bool:
    """Whether every session reported as connected was reported as disconnected."""
    connects = [key for event, key in session_events.log if event == "connect"]
    disconnects = [key for event, key in session_events.log if event == "disconnect"]
    return sorted(connects) == sorted(disconnects)


async def start_waiting(kind: str, monkeypatch, server, client, alice):
    """Starts a blocking connect, and returns it once it is waiting for the connection
    to end, with the session key."""
    if kind == "client":
        blocking_connect = start_blocking(kind, client, alice)
        return blocking_connect, await connected(kind, server, client, alice)

    subscribed = asyncio.Event()
    original_subscribe = alice.subscribe

    async def subscribe(*args, **kwargs):
        await original_subscribe(*args, **kwargs)
        subscribed.set()

    monkeypatch.setattr(alice, "subscribe", subscribe)
    blocking_connect = start_blocking(kind, client, alice)
    await asyncio.wait_for(subscribed.wait(), timeout=2.0)
    return blocking_connect, alice._session_id


async def returned(blocking_connect: asyncio.Future, timeout: float = 2.0):
    done, _ = await asyncio.wait({blocking_connect}, timeout=timeout)
    assert done, "the blocking connect() is still waiting"
    return blocking_connect.result()


@pytest.mark.asyncio
class TestReconnectTokenErrors:
    @pytest.mark.parametrize("refresh_status", [401, 500])
    @pytest.mark.parametrize(
        "status, error", [(401, UnauthorizedException), (403, ForbiddenException)]
    )
    async def test_failing_refresh_stops_reconnecting_with_the_rejection(
        self,
        status,
        error,
        refresh_status,
        server,
        client,
        alice,
        monitor,
        connections,
        log_records,
    ):
        blocking_connect = start_blocking("user", client, alice)
        first_key = await connected("user", server, client, alice)
        old = alice.access_token
        server.reject_sessions["alice"] = status
        server.token_errors = [refresh_status]

        await server.drop(server.sessions[first_key])

        with pytest.raises(error) as raised:
            await asyncio.wait_for(blocking_connect, timeout=2.0)
        # The error of the session is raised, not the one of refreshing the token.
        assert str(raised.value) == "SESSION_ERROR"
        assert len(token_requests(server)) == 1
        assert len(session_requests(server, "alice")) == 2
        assert alice.access_token is old
        assert len(logged(log_records, "Failed to refresh the access token.")) == 1
        assert len(logged(log_records, "Stopped reconnecting the user session")) == 1
        assert_disconnected("user", client, alice, first_key)
        assert_nothing_open(client, monitor, connections)
        await asyncio.sleep(SETTLE)
        assert len(token_requests(server)) == 1
        assert len(session_requests(server, "alice")) == 2

        # The user client can connect again.
        del server.reject_sessions["alice"]
        await alice.connect(UserPermission(chat=True), addition_connect=True)
        assert alice.is_connected

    @pytest.mark.parametrize(
        "status, error", [(401, UnauthorizedException), (403, ForbiddenException)]
    )
    async def test_token_is_refreshed_only_once_across_attempts(
        self, status, error, server, client, alice, monitor, connections
    ):
        blocking_connect = start_blocking("user", client, alice)
        first_key = await connected("user", server, client, alice)
        # Rejected and refreshed, failing for another reason, then rejected again.
        server.session_errors["alice"] = [status, 500, status]

        await server.drop(server.sessions[first_key])

        with pytest.raises(error):
            await asyncio.wait_for(blocking_connect, timeout=2.0)
        refreshed = alice.access_token.access_token
        assert refreshed.startswith("token-alice-refreshed-")
        assert len(token_requests(server)) == 1
        assert [r["token"] for r in session_requests(server, "alice")] == [
            "token-alice",
            "token-alice",
            refreshed,
            refreshed,
        ]
        assert_disconnected("user", client, alice, first_key)
        assert_nothing_open(client, monitor, connections)


@pytest.mark.asyncio
class TestReconnectCancelledFromOutside:
    @pytest.mark.parametrize("stage", ["session_request", "ready", "subscribe"])
    @pytest.mark.parametrize("kind", KINDS)
    async def test_cancelled_reconnection_gives_the_session_up(
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
        session_events,
    ):
        blocking_connect = start_blocking(kind, client, alice)
        first_key = await connected(kind, server, client, alice)
        if kind == "client":
            await alice.subscribe(UserPermission(chat=True), first_key)
        push = server.push
        reached = hold_stage(stage, kind, monkeypatch, server, client, hold, first_key)
        await server.drop(server.sessions[first_key])
        await wait_until(reached)
        attempt = reconnection(kind, client, alice, first_key)
        assert isinstance(attempt, asyncio.Task) and not attempt.done()

        # Something other than disconnect() stops the reconnection.
        attempt.cancel()

        # The connect() is released as if it was disconnected, instead of waiting forever.
        assert await returned(blocking_connect) == first_key
        assert attempt.cancelled()
        assert_disconnected(kind, client, alice, first_key)
        assert_nothing_open(client, monitor, connections)
        requests = len(session_requests(server, owner_of(kind)))
        hold.release()
        server.answer_probe = True
        await asyncio.sleep(SETTLE)
        assert len(session_requests(server, owner_of(kind))) == requests
        assert balanced(session_events)

        # The session doesn't take a slot any more, and can connect again.
        monkeypatch.setattr(server, "push", push)
        if kind == "user":
            await alice.connect(UserPermission(chat=True), addition_connect=True)
            assert alice.is_connected
        else:
            await client.connect(addition_connect=True)
            assert len(client._client_sessions) == 1


@pytest.mark.asyncio
class TestReconnectBranches:
    async def test_user_client_with_nothing_subscribed_is_skipped(
        self, server, client, alice
    ):
        bob = await client.get_user_client(server.add_account("bob"))
        first_key = await client.connect(addition_connect=True)
        await alice.subscribe(UserPermission(chat=True), first_key)
        await bob.subscribe(UserPermission(chat=True), first_key)
        await alice.unsubscribe(UserPermission(chat=True), first_key)
        # Subscribing again would refresh the token of alice first.
        make_stale(alice)
        refreshes = len(token_requests(server))

        await server.drop(server.sessions[first_key])
        second_key = await reconnected_client(client, first_key)

        assert subscriptions_on(server, second_key) == {("chat", "token-bob")}
        assert len(token_requests(server)) == refreshes

    @pytest.mark.parametrize("kind", KINDS)
    async def test_failing_close_of_an_ended_connection_does_not_stop_reconnecting(
        self, monkeypatch, kind, server, client, alice, log_records
    ):
        first_key = await start(kind, client, alice)
        first_gateway = alice._gateway if kind == "user" else client._gateway[first_key]
        original_disconnect = ChzzkGateway.disconnect

        async def failing_disconnect(gateway):
            if gateway is first_gateway:
                raise RuntimeError("close failed")
            await original_disconnect(gateway)

        monkeypatch.setattr(ChzzkGateway, "disconnect", failing_disconnect)

        await server.drop(server.sessions[first_key])
        second_key = await reconnected(kind, client, alice, first_key)

        (record,) = logged(log_records, "Failed to close the connection.")
        assert str(record.exc_info[1]) == "close failed"
        # The aiohttp session is closed although closing the connection failed.
        assert first_gateway.session.closed
        assert subscriptions_on(server, second_key) == {("chat", "token-alice")}

    @pytest.mark.parametrize("kind", KINDS)
    async def test_cancelling_a_released_blocking_connect_raises_cancelled_error(
        self,
        monkeypatch,
        kind,
        server,
        client,
        alice,
        monitor,
        connections,
        session_events,
    ):
        blocking_connect, first_key = await start_waiting(
            kind, monkeypatch, server, client, alice
        )

        # Nothing suspends after the blocking connect() is released, so it hasn't
        # run yet when it's cancelled.
        await disconnect(kind, client, alice)
        blocking_connect.cancel()

        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(blocking_connect, timeout=1.0)
        assert_disconnected(kind, client, alice, first_key)
        assert_nothing_open(client, monitor, connections)
        await asyncio.sleep(SETTLE)
        # The session is disconnected once.
        assert session_events.log == [("connect", first_key), ("disconnect", first_key)]

    async def test_user_client_waits_for_its_session(self, server, client, alice):
        waiter = asyncio.ensure_future(alice.wait_until_connect())
        await asyncio.sleep(0.05)
        assert not waiter.done()

        first_key = await alice.connect(
            UserPermission(chat=True), addition_connect=True
        )
        await asyncio.wait_for(waiter, timeout=1.0)
        await asyncio.wait_for(alice.wait_until_connect(), timeout=1.0)

        # It doesn't return while the session is being reconnected.
        server.reject_sessions["alice"] = 500
        await server.drop(server.sessions[first_key])
        await wait_until(lambda: not alice.is_connected)
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(alice.wait_until_connect(), timeout=0.1)
        del server.reject_sessions["alice"]
        await asyncio.wait_for(alice.wait_until_connect(), timeout=2.0)
        assert alice.is_connected

        await alice.disconnect()
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(alice.wait_until_connect(), timeout=0.1)

    async def test_repeated_connected_event_is_ignored(self, server, client):
        session_id = await client.connect(addition_connect=True)
        gateway = client._gateway[session_id]
        session = server.sessions[session_id]
        waiter = asyncio.ensure_future(client.wait_for("chat", timeout=2.0))

        for key in (session_id, "another-session-key"):
            await server.push(
                session, "SYSTEM", {"type": "connected", "data": {"sessionKey": key}}
            )
        await server.push(session, "CHAT", chat_payload("channel-x", "still reading"))

        # The read loop keeps going, and the session keeps its key.
        assert (await waiter).content == "still reading"
        assert gateway.is_connected and not gateway._read_background_loop.done()
        assert list(client._gateway) == [session_id]
        assert list(client._session_keys) == [session_id]
        assert client._client_sessions[0].keys == [session_id]

    async def test_disconnect_closes_every_session_even_when_one_close_fails(
        self, monkeypatch, server, client
    ):
        first = await client.connect(addition_connect=True)
        second = await client.connect(addition_connect=True)
        failing, other = client._gateway[first], client._gateway[second]
        original_disconnect = ChzzkGateway.disconnect

        async def failing_disconnect(gateway):
            if gateway is failing:
                raise RuntimeError("close failed")
            await original_disconnect(gateway)

        monkeypatch.setattr(ChzzkGateway, "disconnect", failing_disconnect)

        with contextlib.suppress(RuntimeError):
            await client.disconnect()

        assert other.session.closed and not other.is_connected


def fail_closing(monkeypatch, *failing: ChzzkGateway) -> list[OSError]:
    """Makes closing each of the gateways raise once it has been disconnected.
    Returns the errors, in the order of the gateways."""
    errors = [OSError(f"close failed {number}") for number in range(len(failing))]
    original_disconnect = ChzzkGateway.disconnect

    async def failing_disconnect(gateway):
        await original_disconnect(gateway)
        for failing_gateway, error in zip(failing, errors):
            if gateway is failing_gateway:
                raise error

    monkeypatch.setattr(ChzzkGateway, "disconnect", failing_disconnect)
    return errors


@pytest.mark.asyncio
class TestDisconnectWithFailingClose:
    """A connection that fails to close is logged, and doesn't keep `disconnect()` from
    closing the other sessions: they have been removed already, so nothing could
    disconnect them afterwards."""

    @pytest.mark.parametrize("failing", [(0,), (1,), (2,), (0, 2), (0, 1, 2)])
    async def test_every_session_is_closed_and_the_failures_are_logged(
        self, monkeypatch, failing, server, client, session_events, log_records
    ):
        keys = [await client.connect(addition_connect=True) for _ in range(3)]
        gateways = [client._gateway[key] for key in keys]
        errors = fail_closing(monkeypatch, *(gateways[number] for number in failing))

        await asyncio.wait_for(client.disconnect(), timeout=2.0)

        records = logged(log_records, "Failed to close the connection.")
        assert [record.exc_info[1] for record in records] == errors
        assert all(record.levelno == logging.ERROR for record in records)
        for gateway in gateways:
            assert gateway.session.closed and not gateway.is_connected
        assert client._gateway == {}
        assert client._client_sessions == [] and client._session_keys == {}
        await wait_until(
            lambda: {event for event in session_events.log if event[0] == "disconnect"}
            == {("disconnect", key) for key in keys}
        )

    async def test_disconnecting_one_session_keeps_the_others(
        self, monkeypatch, server, client, log_records
    ):
        first = await client.connect(addition_connect=True)
        second = await client.connect(addition_connect=True)
        failing, other = client._gateway[first], client._gateway[second]
        (error,) = fail_closing(monkeypatch, failing)

        await client.disconnect(first)

        (record,) = logged(log_records, "Failed to close the connection.")
        assert record.exc_info[1] is error
        assert failing.session.closed and not failing.is_connected
        assert list(client._gateway) == [second]
        assert other.is_connected and not other.session.closed

    @pytest.mark.parametrize("how", ["disconnect", "cancel"])
    async def test_blocking_connect_ends_as_usual(
        self, monkeypatch, how, server, client, log_records
    ):
        blocking = asyncio.ensure_future(client.connect())
        await wait_until(lambda: len(client._gateway) == 1)
        key, gateway = next(iter(client._gateway.items()))
        (error,) = fail_closing(monkeypatch, gateway)

        if how == "disconnect":
            await client.disconnect()
            assert await asyncio.wait_for(blocking, timeout=1.0) == key
        else:
            blocking.cancel()
            # The failed close doesn't replace the cancellation.
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(blocking, timeout=1.0)

        (record,) = logged(log_records, "Failed to close the connection.")
        assert record.exc_info[1] is error
        assert gateway.session.closed
        assert client._gateway == {} and client._client_sessions == []

    async def test_reconnection_in_progress_is_stopped(
        self, monkeypatch, server, client, hold, monitor, connections
    ):
        first = await client.connect(addition_connect=True)
        second = await client.connect(addition_connect=True)
        reached = hold_stage(
            "session_request", "client", monkeypatch, server, client, hold, second
        )
        await server.drop(server.sessions[second])
        await wait_until(reached)
        attempt = reconnection("client", client, None, second)
        assert attempt is not None
        fail_closing(monkeypatch, client._gateway[first])

        await asyncio.wait_for(client.disconnect(), timeout=2.0)

        # The attempt is cancelled and has finished, although closing the first session failed.
        assert attempt.done()
        assert_disconnected("client", client, None, second)
        assert_nothing_open(client, monitor, connections)
        requests = len(session_requests(server, None))
        hold.release()
        await asyncio.sleep(SETTLE)
        assert len(session_requests(server, None)) == requests

    async def test_aexit_still_disconnects_user_clients_and_closes_the_http_session(
        self, monkeypatch, server, client, alice, log_records
    ):
        first = await client.connect(addition_connect=True)
        second = await client.connect(addition_connect=True)
        await alice.connect(UserPermission(chat=True), addition_connect=True)
        user_gateway = alice._gateway
        failing, other = client._gateway[first], client._gateway[second]
        (error,) = fail_closing(monkeypatch, failing)

        await asyncio.wait_for(client.__aexit__(None, None, None), timeout=2.0)

        (record,) = logged(log_records, "Failed to close the connection.")
        assert record.exc_info[1] is error
        assert failing.session.closed and other.session.closed
        assert not other.is_connected
        assert client._gateway == {}
        assert not alice.is_connected and user_gateway.session.closed
        assert client.http.closed
