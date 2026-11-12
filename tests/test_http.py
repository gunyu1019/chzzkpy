"""MIT License

Copyright (c) 2024-2025 gunyu1019

Tests for `ChzzkOpenAPISession` (`chzzkpy/http.py`).

Only chzzkpy's own hooks are exercised:

* `before_request` turns the `AccessToken` of an endpoint into an `Authorization` header,
  adds the client credentials, and refuses to send a user-only request without a token.
* `after_request` maps error statuses onto chzzkpy exceptions.

A small local aiohttp server stands in for the Chzzk Open API. It records every request
and answers with a configurable status and body, so the real endpoint methods run
against it and nothing ever reaches the real API.
"""

import asyncio
import inspect
import json
from dataclasses import dataclass
from typing import Any, Optional

import aiohttp
import pytest
import pytest_asyncio
from aiohttp import web
from ahttp_client import get
from ahttp_client.request import RequestCore
from multidict import CIMultiDict

from chzzkpy import AccessToken
from chzzkpy.error import (
    BadRequestException,
    ChzzkpyException,
    ForbiddenException,
    HTTPException,
    LoginRequired,
    NotFoundException,
    TooManyRequestsException,
    UnauthorizedException,
)
from chzzkpy.http import ChzzkOpenAPISession

CLIENT_ID = "test-client-id"
CLIENT_SECRET = "test-client-secret"

_UNSET: Any = object()


@dataclass
class RecordedRequest:
    method: str
    path: str
    query: dict[str, str]
    headers: CIMultiDict
    body: Any  # parsed JSON, the raw bytes when it is not JSON, None without a body


class MockOpenAPIServer:
    """Records every request and answers with the configured reply."""

    def __init__(self):
        self.url: Optional[str] = None
        self.requests: list[RecordedRequest] = []

        self.status = 200
        self.reason: Optional[str] = None
        self.content_type: Optional[str] = None
        self.raw = b""
        self.reply(200, payload={"code": 200, "message": None, "content": None})

        # When set, every request waits until this many requests are in flight at the
        # same time, so tests can prove that requests really overlapped.
        self.barrier = 0
        self.in_flight = 0
        self.max_in_flight = 0
        self._released: Optional[asyncio.Event] = None

        self._runner: Optional[web.AppRunner] = None

    def reply(
        self,
        status: int = 200,
        *,
        payload: Any = _UNSET,
        raw: bytes = b"",
        content_type: Optional[str] = None,
        reason: Optional[str] = None,
    ):
        """Set the reply of every following request: a JSON `payload`, or `raw` bytes."""
        self.status = status
        self.reason = reason
        if payload is not _UNSET:
            self.raw = json.dumps(payload).encode()
            self.content_type = content_type or "application/json"
        else:
            self.raw = raw
            self.content_type = content_type

    def error(self, status: int, message: Optional[str] = None, **kwargs):
        """Reply the way the Chzzk Open API does for an error."""
        self.reply(status, payload={"code": status, "message": message}, **kwargs)

    async def start(self):
        self._released = asyncio.Event()
        app = web.Application()
        app.router.add_route("*", "/{path:.*}", self.handle)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        self.url = f"http://127.0.0.1:{port}"

    async def stop(self):
        await self._runner.cleanup()

    async def handle(self, request: web.Request) -> web.Response:
        raw = await request.read()
        try:
            body = json.loads(raw) if raw else None
        except ValueError:
            body = raw
        self.requests.append(
            RecordedRequest(
                method=request.method,
                path=request.path,
                query=dict(request.query),
                headers=CIMultiDict(request.headers),
                body=body,
            )
        )

        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            if self.barrier:
                if self.in_flight >= self.barrier:
                    self._released.set()
                await asyncio.wait_for(self._released.wait(), timeout=10)
        finally:
            self.in_flight -= 1

        kwargs: dict[str, Any] = dict()
        if self.content_type is not None:
            kwargs["content_type"] = self.content_type
        if self.reason is not None:
            kwargs["reason"] = self.reason
        return web.Response(status=self.status, body=self.raw, **kwargs)


def make_token(name: str, token_type: str = "Bearer") -> AccessToken:
    return AccessToken(
        access_token=f"token-{name}",
        refresh_token=f"refresh-{name}",
        token_type=token_type,
        expires_in=86400,
    )


async def open_session(
    server: MockOpenAPIServer,
    client_id: str = CLIENT_ID,
    client_secret: str = CLIENT_SECRET,
    session_class: type[ChzzkOpenAPISession] = ChzzkOpenAPISession,
) -> ChzzkOpenAPISession:
    """A `ChzzkOpenAPISession` whose traffic goes to the mock server."""
    session = session_class(client_id=client_id, client_secret=client_secret)
    await session.session.close()
    session.session = aiohttp.ClientSession(
        server.url, timeout=aiohttp.ClientTimeout(total=15)
    )
    return session


@pytest_asyncio.fixture
async def server():
    instance = MockOpenAPIServer()
    await instance.start()
    yield instance
    await instance.stop()


@pytest_asyncio.fixture
async def http(server):
    instance = await open_session(server)
    yield instance
    await instance.close()


# Endpoints that need the token of a user, with different methods and kinds of arguments.
USER_ENDPOINTS = [
    pytest.param(
        "GET",
        "/open/v1/users/me",
        lambda http, token: http.get_user_self(token=token),
        id="get_user_self",
    ),
    pytest.param(
        "GET",
        "/open/v1/channels/followers",
        lambda http, token: http.get_channel_followers(token=token, page=2),
        id="get_channel_followers",
    ),
    pytest.param(
        "GET",
        "/open/v1/sessions/auth",
        lambda http, token: http.generate_user_session(token=token),
        id="generate_user_session",
    ),
    pytest.param(
        "POST",
        "/open/v1/chats/send",
        lambda http, token: http.create_message(token=token, message="hello"),
        id="create_message",
    ),
    pytest.param(
        "POST",
        "/open/v1/chats/notice",
        lambda http, token: http.create_notice(token=token, message="notice"),
        id="create_notice",
    ),
    pytest.param(
        "PUT",
        "/open/v1/chats/settings",
        lambda http, token: http.set_chat_setting(
            token=token,
            chat_available_condition="NONE",
            chat_available_group="ALL",
            min_follower_minute=0,
            allow_subscriber_in_follower_mode=False,
            chat_slow_mode_sec=0,
            chat_emoji_mode=True,
        ),
        id="set_chat_setting",
    ),
    pytest.param(
        "PATCH",
        "/open/v1/lives/setting",
        lambda http, token: http.set_live_setting(token=token, default_live_title="t"),
        id="set_live_setting",
    ),
    pytest.param(
        "DELETE",
        "/open/v1/restrict-channels",
        lambda http, token: http.remove_restrict_user(
            token=token, target_channel_id="target"
        ),
        id="remove_restrict_user",
    ),
]

# Endpoints that authenticate the application only.
CLIENT_ENDPOINTS = [
    pytest.param(
        "GET",
        "/open/v1/channels",
        lambda http: http.get_channel(channel_ids="a,b"),
        id="get_channel",
    ),
    pytest.param(
        "GET",
        "/open/v1/categories/search",
        lambda http: http.get_category(query="game"),
        id="get_category",
    ),
    pytest.param(
        "GET",
        "/open/v1/lives",
        lambda http: http.get_lives(),
        id="get_lives",
    ),
    pytest.param(
        "GET",
        "/open/v1/sessions/auth/client",
        lambda http: http.generate_client_session(),
        id="generate_client_session",
    ),
    pytest.param(
        "POST",
        "/auth/v1/token",
        lambda http: http.generate_access_token(
            grant_type="refresh_token",
            client_id="body-client-id",
            client_secret="body-client-secret",
            refresh_token="refresh",
        ),
        id="generate_access_token",
    ),
    pytest.param(
        "POST",
        "/auth/v1/token/revoke",
        lambda http: http.revoke_access_token(
            client_id="body-client-id", client_secret="body-client-secret", token="t"
        ),
        id="revoke_access_token",
    ),
]


def assert_no_user_credentials(record: RecordedRequest):
    assert "Authorization" not in record.headers
    # The `AccessToken` argument must not be sent on under its own parameter name either.
    assert "token" not in record.headers


def assert_client_credentials(record: RecordedRequest):
    assert record.headers["Client-Id"] == CLIENT_ID
    assert record.headers["Client-Secret"] == CLIENT_SECRET


def assert_no_client_credentials(record: RecordedRequest):
    assert "Client-Id" not in record.headers
    assert "Client-Secret" not in record.headers


class TestAuthorizationDeclarations:
    """`before_request` trusts `__authorization_configuration__`, so a missing or wrong
    declaration would silently send a request without its credentials."""

    ENDPOINTS = dict(
        inspect.getmembers(
            ChzzkOpenAPISession, lambda member: isinstance(member, RequestCore)
        )
    )

    @pytest.mark.parametrize("name", sorted(ENDPOINTS))
    def test_every_endpoint_declares_who_it_authenticates(self, name):
        function = self.ENDPOINTS[name].func

        configuration = getattr(function, "__authorization_configuration__", None)

        assert configuration is not None, f"{name} has no authorization_configuration"
        assert (
            configuration["client"] or configuration["user"]
        ), f"{name} authenticates neither the client nor a user"

    @pytest.mark.parametrize("name", sorted(ENDPOINTS))
    def test_user_endpoints_take_a_token_header(self, name):
        endpoint = self.ENDPOINTS[name]
        configuration = endpoint.func.__authorization_configuration__

        assert ("token" in endpoint.header_parameter) == configuration["user"], (
            f"{name}: a user endpoint needs a `token` header parameter (and an "
            "endpoint with one needs is_user=True), or its token is never sent"
        )

    @pytest.mark.parametrize(
        "flags, expected",
        [
            ({}, {"client": False, "user": False}),
            ({"is_client": True}, {"client": True, "user": False}),
            ({"is_user": True}, {"client": False, "user": True}),
            ({"is_client": True, "is_user": True}, {"client": True, "user": True}),
        ],
    )
    def test_decorator_records_the_flags(self, flags, expected):
        @ChzzkOpenAPISession.authorization_configuration(**flags)
        async def endpoint(): ...

        assert endpoint.__authorization_configuration__ == expected


@pytest.mark.asyncio
class TestSessionSetup:
    async def test_targets_the_open_api_with_the_given_credentials(self):
        session = ChzzkOpenAPISession(client_id="id", client_secret="secret")
        try:
            assert session.base_url == "https://openapi.chzzk.naver.com"
            assert session.client_id == "id"
            assert session.client_secret == "secret"
        finally:
            await session.close()


@pytest.mark.asyncio
class TestUserAuthorization:
    @pytest.mark.parametrize("method, path, call", USER_ENDPOINTS)
    async def test_token_becomes_the_authorization_header(
        self, server, http, method, path, call
    ):
        await call(http, make_token("alice"))

        (record,) = server.requests
        assert (record.method, record.path) == (method, path)
        assert record.headers["Authorization"] == "Bearer token-alice"
        assert record.headers["Content-Type"] == "application/json"
        assert "token" not in record.headers
        # Only the application-wide endpoints carry the client credentials.
        assert_no_client_credentials(record)

    @pytest.mark.parametrize("token_type", ["Bearer", "bearer", "Custom"])
    async def test_header_uses_the_token_type_of_the_token(
        self, server, http, token_type
    ):
        await http.get_user_self(token=make_token("alice", token_type=token_type))

        assert server.requests[0].headers["Authorization"] == (
            f"{token_type} token-alice"
        )

    @pytest.mark.parametrize("method, path, call", USER_ENDPOINTS)
    async def test_missing_token_raises_login_required_before_sending(
        self, server, http, method, path, call
    ):
        with pytest.raises(LoginRequired):
            await call(http, None)

        assert server.requests == []

    async def test_omitted_token_raises_login_required_before_sending(
        self, server, http
    ):
        # The token is optional in the signature of these endpoints.
        for call in (
            http.get_channel_administrator,
            http.get_channel_followers,
            http.get_channel_subscribers,
            http.generate_user_session,
        ):
            with pytest.raises(LoginRequired):
                await call()

        assert server.requests == []

    async def test_only_an_access_token_counts_as_a_token(self, server, http):
        with pytest.raises(LoginRequired):
            await http.get_user_self(token="token-alice")

        assert server.requests == []

    async def test_login_required_does_not_poison_the_session(self, server, http):
        with pytest.raises(LoginRequired):
            await http.get_user_self(token=None)

        await http.get_user_self(token=make_token("alice"))

        (record,) = server.requests
        assert record.headers["Authorization"] == "Bearer token-alice"


@pytest.mark.asyncio
class TestClientAuthorization:
    @pytest.mark.parametrize("method, path, call", CLIENT_ENDPOINTS)
    async def test_client_credentials_come_from_the_session(
        self, server, http, method, path, call
    ):
        await call(http)

        (record,) = server.requests
        assert (record.method, record.path) == (method, path)
        assert_client_credentials(record)
        assert record.headers["Content-Type"] == "application/json"
        assert_no_user_credentials(record)

    async def test_credentials_follow_the_session_that_was_created(self, server):
        session = await open_session(server, "other-id", "other-secret")
        try:
            await session.get_channel(channel_ids="a")
        finally:
            await session.close()

        headers = server.requests[0].headers
        assert headers["Client-Id"] == "other-id"
        assert headers["Client-Secret"] == "other-secret"

    async def test_endpoint_without_declaration_gets_no_credentials(self, server):
        class ExtendedSession(ChzzkOpenAPISession):
            @get("/open/v1/undeclared", directly_response=True)
            async def undeclared(self) -> None:
                pass

        session = await open_session(server, session_class=ExtendedSession)
        try:
            await session.undeclared()
        finally:
            await session.close()

        (record,) = server.requests
        assert record.path == "/open/v1/undeclared"
        assert record.headers["Content-Type"] == "application/json"
        assert_no_user_credentials(record)
        assert_no_client_credentials(record)


@pytest.mark.asyncio
class TestClientAndUserAuthorization:
    """Subscribing works for a user session (with the token) and a client session
    (without it), so both credentials are sent and the token is optional."""

    @pytest.mark.parametrize("action", ["subscribe", "unsubscribe"])
    async def test_user_session_sends_token_and_client_credentials(
        self, server, http, action
    ):
        method = getattr(
            http, "subcribe_event" if action == "subscribe" else "unsubcribe_event"
        )

        await method(event="chat", session_key="key-1", token=make_token("alice"))

        (record,) = server.requests
        assert record.method == "POST"
        assert record.path == f"/open/v1/sessions/events/{action}/chat"
        assert record.query == {"sessionKey": "key-1"}
        assert record.headers["Authorization"] == "Bearer token-alice"
        assert_client_credentials(record)
        assert record.headers["Content-Type"] == "application/json"
        assert "token" not in record.headers

    @pytest.mark.parametrize("action", ["subscribe", "unsubscribe"])
    async def test_client_session_sends_client_credentials_only(
        self, server, http, action
    ):
        method = getattr(
            http, "subcribe_event" if action == "subscribe" else "unsubcribe_event"
        )

        await method(event="donation", session_key="key-2")

        (record,) = server.requests
        assert record.path == f"/open/v1/sessions/events/{action}/donation"
        assert_client_credentials(record)
        assert_no_user_credentials(record)


@pytest.mark.asyncio
class TestRequestIsolation:
    """Every request is built from its own arguments; nothing stays behind in the
    session for the next (or a concurrent) request."""

    async def test_credentials_do_not_carry_over_to_later_requests(self, server, http):
        await http.get_user_self(token=make_token("alice"))
        await http.get_channel(channel_ids="a")
        with pytest.raises(LoginRequired):
            await http.get_channel_followers()
        await http.get_user_self(token=make_token("bob"))
        await http.subcribe_event(event="chat", session_key="key")

        user_alice, client, user_bob, subscribe = server.requests
        assert user_alice.headers["Authorization"] == "Bearer token-alice"
        assert_no_client_credentials(user_alice)
        assert_no_user_credentials(client)
        assert_client_credentials(client)
        assert user_bob.headers["Authorization"] == "Bearer token-bob"
        assert_no_client_credentials(user_bob)
        assert_no_user_credentials(subscribe)
        assert_client_credentials(subscribe)

    async def test_concurrent_requests_carry_their_own_token(self, server, http):
        count = 8
        server.barrier = count
        tokens = [make_token(f"user-{index}") for index in range(count)]

        await asyncio.wait_for(
            asyncio.gather(
                *(
                    http.get_channel_followers(token=token, page=index)
                    for index, token in enumerate(tokens)
                )
            ),
            timeout=15,
        )

        assert server.max_in_flight == count, "the requests did not overlap"
        assert len(server.requests) == count
        for record in server.requests:
            index = int(record.query["page"])
            assert record.headers["Authorization"] == f"Bearer token-user-{index}"
            assert "token" not in record.headers
            assert_no_client_credentials(record)

    async def test_concurrent_user_and_client_requests_do_not_share_headers(
        self, server, http
    ):
        server.barrier = 4

        await asyncio.wait_for(
            asyncio.gather(
                http.get_user_self(token=make_token("alice")),
                http.get_channel(channel_ids="a"),
                http.create_message(token=make_token("bob"), message="hi"),
                http.get_category(query="game"),
            ),
            timeout=15,
        )

        assert server.max_in_flight == 4, "the requests did not overlap"
        by_path = {record.path: record for record in server.requests}
        assert by_path["/open/v1/users/me"].headers["Authorization"] == (
            "Bearer token-alice"
        )
        assert by_path["/open/v1/chats/send"].headers["Authorization"] == (
            "Bearer token-bob"
        )
        for path in ("/open/v1/users/me", "/open/v1/chats/send"):
            assert_no_client_credentials(by_path[path])
        for path in ("/open/v1/channels", "/open/v1/categories/search"):
            assert_client_credentials(by_path[path])
            assert_no_user_credentials(by_path[path])


@pytest.mark.asyncio
class TestErrorResponses:
    async def test_success_statuses_pass_through(self, server, http):
        for status in (200, 201, 204, 304):
            server.reply(status)

            response = await http.create_notice(token=make_token("a"), message="m")

            assert response.status == status

    async def test_success_returns_the_content(self, server, http):
        server.reply(
            payload={
                "code": 200,
                "message": None,
                "content": {"channelId": "channel-1", "channelName": "Alice"},
            }
        )

        result = await http.get_user_self(token=make_token("alice"))

        assert result.content.id == "channel-1"
        assert result.content.name == "Alice"

    async def test_bad_request_carries_the_reason_phrase(self, server, http):
        server.error(400, "ignored", reason="Invalid channel ids")

        with pytest.raises(BadRequestException, match="^Invalid channel ids$"):
            await http.get_channel(channel_ids="")

    async def test_too_many_requests_carries_the_reason_phrase(self, server, http):
        server.error(429, "ignored", reason="Slow Down")

        with pytest.raises(TooManyRequestsException, match="^Slow Down$"):
            await http.create_message(token=make_token("a"), message="hi")

    @pytest.mark.parametrize(
        "status, exception",
        [(400, BadRequestException), (429, TooManyRequestsException)],
    )
    async def test_status_alone_decides_for_bad_request_and_rate_limit(
        self, server, http, status, exception
    ):
        # A rate limiting proxy answers with HTML; the body is not needed for these.
        server.reply(status, raw=b"<html>slow down</html>", content_type="text/html")

        with pytest.raises(exception):
            await http.get_lives()

    @pytest.mark.parametrize(
        "status, exception",
        [
            (401, UnauthorizedException),
            (403, ForbiddenException),
            (404, NotFoundException),
        ],
    )
    async def test_message_of_the_response_is_carried(
        self, server, http, status, exception
    ):
        server.error(status, "THE_MESSAGE_OF_CHZZK")

        with pytest.raises(exception, match="^THE_MESSAGE_OF_CHZZK$"):
            await http.get_user_self(token=make_token("alice"))

    @pytest.mark.parametrize(
        "status, exception, default_message",
        [
            (401, UnauthorizedException, "Invalid or expired authorization"),
            (403, ForbiddenException, "Invalid permission"),
            (404, NotFoundException, "Not Found"),
        ],
    )
    async def test_missing_message_falls_back_to_the_default(
        self, server, http, status, exception, default_message
    ):
        server.reply(status, payload={"code": status})

        with pytest.raises(exception, match=f"^{default_message}$"):
            await http.get_user_self(token=make_token("alice"))

    @pytest.mark.parametrize(
        "payload",
        [
            pytest.param({"code": 401}, id="missing"),
            pytest.param({"code": 401, "message": None}, id="null"),
        ],
    )
    async def test_unauthorized_without_message_still_raises_unauthorized(
        self, server, http, payload
    ):
        server.reply(401, payload=payload)

        with pytest.raises(UnauthorizedException):
            await http.get_user_self(token=make_token("alice"))

    async def test_unauthorized_without_message_does_not_claim_not_found(
        self, server, http
    ):
        server.reply(401, payload={"code": 401})

        with pytest.raises(UnauthorizedException) as error:
            await http.get_user_self(token=make_token("alice"))

        assert "Not Found" not in str(error.value)
        assert str(error.value) == "Invalid or expired authorization"

    @pytest.mark.parametrize("status", [402, 405, 409, 418, 500, 502, 503])
    async def test_other_errors_raise_http_exception_with_code_and_message(
        self, server, http, status
    ):
        server.error(status, "SOMETHING_FAILED")

        with pytest.raises(HTTPException) as error:
            await http.create_message(token=make_token("alice"), message="hi")

        assert str(error.value) == f"SOMETHING_FAILED ({status})"

    async def test_http_exception_without_message_still_names_the_code(
        self, server, http
    ):
        server.error(500, None)

        with pytest.raises(HTTPException) as error:
            await http.get_lives()

        assert "500" in str(error.value)
        assert str(error.value) == "Responded error code (500)"

    @pytest.mark.parametrize(
        "status, exception",
        [
            (400, BadRequestException),
            (401, UnauthorizedException),
            (403, ForbiddenException),
            (404, NotFoundException),
            (429, TooManyRequestsException),
            (500, HTTPException),
        ],
    )
    async def test_each_status_raises_only_its_own_exception(
        self, server, http, status, exception
    ):
        server.error(status, "MESSAGE")

        with pytest.raises(ChzzkpyException) as error:
            await http.get_lives()

        assert type(error.value) is exception

    async def test_error_is_raised_before_the_body_is_parsed_as_a_model(
        self, server, http
    ):
        # An error body has no `content`, which `get_user_self` would fail to parse.
        server.error(403, "INSUFFICIENT_SCOPE")

        with pytest.raises(ForbiddenException):
            await http.get_user_self(token=make_token("alice"))

    async def test_session_is_usable_after_an_error(self, server, http):
        server.error(500, "DOWN")
        with pytest.raises(HTTPException):
            await http.get_lives()

        server.reply(200, payload={"code": 200, "message": None, "content": None})
        result = await http.get_lives()

        assert result.code == 200


DEFAULT_MESSAGES = {
    UnauthorizedException: "Invalid or expired authorization",
    ForbiddenException: "Invalid permission",
    NotFoundException: "Not Found",
}


def default_message(exception: type[ChzzkpyException], status: int) -> str:
    """The text an exception carries when the response gave no usable message."""
    if exception is HTTPException:
        return f"Responded error code ({status})"
    return DEFAULT_MESSAGES[exception]


@pytest.mark.asyncio
class TestErrorResponsesWithoutChzzkBody:
    """Gateways, proxies and outages answer with bodies that are not the JSON of the
    Open API. The status is still known, so a chzzkpy exception is expected, carrying
    the default message of its kind."""

    @pytest.mark.parametrize(
        "status, raw, content_type, exception",
        [
            pytest.param(401, b"", None, UnauthorizedException, id="401-empty-body"),
            pytest.param(
                401,
                b"<html>Unauthorized</html>",
                "text/html",
                UnauthorizedException,
                id="401-html",
            ),
            pytest.param(
                403,
                b"<html>Forbidden</html>",
                "text/html",
                ForbiddenException,
                id="403-html",
            ),
            pytest.param(
                404,
                b"<html>Not Found</html>",
                "text/html",
                NotFoundException,
                id="404-html",
            ),
            pytest.param(
                500,
                b"<html>Internal Server Error</html>",
                "text/html",
                HTTPException,
                id="500-html",
            ),
            pytest.param(502, b"", None, HTTPException, id="502-empty-body"),
            pytest.param(
                503,
                b"Service Unavailable",
                "text/plain",
                HTTPException,
                id="503-plain-text",
            ),
            pytest.param(
                401, b"", "application/json", UnauthorizedException, id="401-empty-json"
            ),
            pytest.param(
                500,
                b"{",
                "application/json",
                HTTPException,
                id="500-truncated-json",
            ),
            pytest.param(
                403,
                b"{'code': 403}",
                "application/json",
                ForbiddenException,
                id="403-single-quoted-json",
            ),
            pytest.param(
                404,
                b"<html>Not Found</html>",
                "application/json",
                NotFoundException,
                id="404-html-as-json",
            ),
            pytest.param(
                502,
                b"\xff\xfe\x00",
                "application/json",
                HTTPException,
                id="502-undecodable-bytes",
            ),
        ],
    )
    async def test_non_json_body(
        self, server, http, status, raw, content_type, exception
    ):
        server.reply(status, raw=raw, content_type=content_type)

        with pytest.raises(exception) as error:
            await http.create_notice(token=make_token("alice"), message="hi")

        assert type(error.value) is exception
        assert str(error.value) == default_message(exception, status)

    @pytest.mark.parametrize(
        "payload",
        [
            pytest.param(None, id="null"),
            pytest.param([], id="empty-array"),
            pytest.param([{"code": 500, "message": "IN_AN_ARRAY"}], id="array"),
            pytest.param("SOMETHING_FAILED", id="string"),
            pytest.param(42, id="number"),
            pytest.param(True, id="boolean"),
        ],
    )
    @pytest.mark.parametrize(
        "status, exception",
        [
            (401, UnauthorizedException),
            (403, ForbiddenException),
            (404, NotFoundException),
            (500, HTTPException),
        ],
    )
    async def test_json_body_that_is_not_an_object(
        self, server, http, status, exception, payload
    ):
        server.reply(status, payload=payload)

        with pytest.raises(exception) as error:
            await http.create_notice(token=make_token("alice"), message="hi")

        assert type(error.value) is exception
        assert str(error.value) == default_message(exception, status)

    @pytest.mark.parametrize(
        "payload",
        [
            pytest.param({}, id="empty-object"),
            pytest.param({"code": 500}, id="without-message"),
            pytest.param({"code": 500, "message": None}, id="null-message"),
            pytest.param({"code": 500, "message": ""}, id="empty-message"),
            pytest.param({"code": 500, "message": 123}, id="number-message"),
            pytest.param({"code": 500, "message": ["a"]}, id="array-message"),
            pytest.param({"code": 500, "message": {"a": 1}}, id="object-message"),
        ],
    )
    @pytest.mark.parametrize(
        "status, exception",
        [
            (401, UnauthorizedException),
            (403, ForbiddenException),
            (404, NotFoundException),
            (500, HTTPException),
        ],
    )
    async def test_json_object_without_a_usable_message(
        self, server, http, status, exception, payload
    ):
        server.reply(status, payload=payload)

        with pytest.raises(exception) as error:
            await http.create_notice(token=make_token("alice"), message="hi")

        assert type(error.value) is exception
        if exception is HTTPException:
            # The code of the body is used when it has one, otherwise the status is.
            code = payload.get("code", status)
            assert str(error.value) == f"Responded error code ({code})"
        else:
            assert str(error.value) == default_message(exception, status)

    @pytest.mark.parametrize(
        "payload, text",
        [
            pytest.param({"message": "SOMETHING_FAILED"}, "SOMETHING_FAILED (502)"),
            pytest.param(
                {"code": None, "message": "SOMETHING_FAILED"}, "SOMETHING_FAILED (502)"
            ),
            pytest.param(
                {"code": "oops", "message": "SOMETHING_FAILED"},
                "SOMETHING_FAILED (502)",
            ),
            pytest.param(
                {"code": True, "message": "SOMETHING_FAILED"}, "SOMETHING_FAILED (502)"
            ),
            pytest.param(
                {"code": 500, "message": "SOMETHING_FAILED"}, "SOMETHING_FAILED (500)"
            ),
        ],
    )
    async def test_http_exception_uses_the_status_when_the_code_is_not_a_number(
        self, server, http, payload, text
    ):
        server.reply(502, payload=payload)

        with pytest.raises(HTTPException) as error:
            await http.create_notice(token=make_token("alice"), message="hi")

        assert str(error.value) == text

    async def test_json_body_is_read_whatever_its_content_type(self, server, http):
        server.reply(
            500,
            raw=b'{"code": 500, "message": "FROM_A_PROXY"}',
            content_type="text/plain",
        )

        with pytest.raises(HTTPException) as error:
            await http.create_notice(token=make_token("alice"), message="hi")

        assert str(error.value) == "FROM_A_PROXY (500)"

    async def test_connections_return_to_the_pool_after_an_error(self, server):
        # With a single connection, an error response that is neither read nor
        # released would block every following request. The bodies are too large to be
        # buffered by the client on their own, and the raised errors are kept alive so
        # that a response is not closed merely by being garbage collected.
        size = 4 * 1024 * 1024
        http = await open_session(server)
        await http.session.close()
        http.session = aiohttp.ClientSession(
            server.url,
            connector=aiohttp.TCPConnector(limit=1),
            timeout=aiohttp.ClientTimeout(total=15),
        )
        raised: list[BaseException] = []
        try:
            for status, exception, filler, content_type in (
                (400, BadRequestException, b"x", "text/plain"),
                (401, UnauthorizedException, b"<", "text/html"),
                (404, NotFoundException, b" ", "application/json"),
                (429, TooManyRequestsException, b"x", "text/plain"),
                (500, HTTPException, b"{", "application/json"),
                (502, HTTPException, b"\xff", "application/json"),
            ):
                server.reply(status, raw=filler * size, content_type=content_type)
                for _ in range(3):
                    with pytest.raises(exception) as error:
                        await asyncio.wait_for(http.get_lives(), timeout=5)
                    raised.append(error.value)
        finally:
            await http.close()

        assert len(raised) == 18


@pytest.mark.asyncio
class TestMultipleSessions:
    """`ahttp_client` binds the endpoints, which are shared by every instance of the
    class, to the session that was created last."""

    @pytest.mark.xfail(
        strict=True,
        reason="endpoints are bound to the last created ChzzkOpenAPISession, so an "
        "older session sends the client credentials of the newer one",
    )
    async def test_each_session_sends_its_own_client_credentials(self, server):
        first = await open_session(server, "first-id", "first-secret")
        second = await open_session(server, "second-id", "second-secret")
        try:
            await first.get_channel(channel_ids="a")
            await second.get_channel(channel_ids="a")
        finally:
            await first.close()
            await second.close()

        first_request, second_request = server.requests
        assert first_request.headers["Client-Id"] == "first-id"
        assert first_request.headers["Client-Secret"] == "first-secret"
        assert second_request.headers["Client-Id"] == "second-id"
        assert second_request.headers["Client-Secret"] == "second-secret"

    @pytest.mark.xfail(
        strict=True,
        raises=RuntimeError,
        reason="endpoints are bound to the last created ChzzkOpenAPISession, so "
        "closing it breaks every older session",
    )
    async def test_session_survives_closing_another_session(self, server):
        first = await open_session(server)
        second = await open_session(server)
        await second.close()
        try:
            await first.get_channel(channel_ids="a")
        finally:
            await first.close()
