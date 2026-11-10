"""MIT License

Copyright (c) 2024-2025 gunyu1019

Connect option tests for the official chzzkpy package: the `ssl` option of
`Client.connect()` and `UserClient.connect()`, which is passed on to the gateway to pick
the scheme (https/wss or http/ws) of the session server.

The mock Chzzk server is shared with `test_multi_account.py`. It speaks plain HTTP, so
connecting to it works only when the connect methods pass `ssl=False` on. Unlike the
`client` fixture of that module, the client here is not patched to skip TLS.
"""

import aiohttp
import pytest
import pytest_asyncio

from chzzkpy import Client, UserPermission
from chzzkpy.gateway import ChzzkGateway

from test_multi_account import (  # noqa: F401
    CLIENT_ID,
    CLIENT_SECRET,
    EventRecorder,
    chat_payload,
    server,
)


class StopConnect(Exception):
    """Raised by the stubbed gateway to end a connect() before it reaches the network."""


@pytest_asyncio.fixture
async def plain_client(server):
    """A `Client` whose Open API traffic goes to the mock server, without patching the gateway."""
    instance = Client(CLIENT_ID, CLIENT_SECRET)
    await instance._async_setup_hook()
    await instance.http.session.close()
    instance.http.session = aiohttp.ClientSession(server.url)

    yield instance

    try:
        await instance.disconnect()
        for user_client in instance.user_client:
            await user_client.disconnect()
    finally:
        await instance.http.close()


@pytest.fixture
def events(plain_client):
    return EventRecorder(plain_client)


@pytest_asyncio.fixture
async def alice(server, plain_client):
    return await plain_client.get_user_client(server.add_account("alice"))


@pytest.fixture
def gateway_calls(monkeypatch) -> list[dict]:
    """Replaces `ChzzkGateway.connect` with a stub that records its keyword arguments
    and raises `StopConnect`."""
    calls = []

    async def connect(cls, *args, **kwargs):
        calls.append(kwargs)
        raise StopConnect()

    monkeypatch.setattr(ChzzkGateway, "connect", classmethod(connect))
    return calls


@pytest.mark.asyncio
class TestConnectWithoutSsl:
    """`ssl=False` reaches the gateway, so a plain HTTP session server can be used."""

    async def test_user_client_connects_to_plain_http_server(
        self, server, alice, events
    ):
        session_id = await alice.connect(
            UserPermission(chat=True), addition_connect=True, ssl=False
        )
        session = server.session_of("alice")

        assert session_id == session.key
        assert alice.is_connected

        await server.push(session, "CHAT", chat_payload("channel-alice", "hello"))
        message = await events.next("chat")
        assert message.content == "hello"

    async def test_client_connects_to_plain_http_server(
        self, server, plain_client, alice, events
    ):
        session_id = await plain_client.connect(addition_connect=True, ssl=False)
        session = server.session_of(None)

        assert session_id == session.key

        await alice.subscribe(UserPermission(chat=True), session.key)
        await server.push(session, "CHAT", chat_payload("channel-alice", "hello"))
        message = await events.next("chat")
        assert message.content == "hello"


@pytest.mark.asyncio
class TestSslOptionPassedToGateway:
    """What `ChzzkGateway.connect` is called with, without connecting to anything."""

    CASES = [
        pytest.param((), {}, True, id="omitted"),
        pytest.param((), {"ssl": True}, True, id="keyword-true"),
        pytest.param((), {"ssl": False}, False, id="keyword-false"),
        pytest.param((True, False), {}, False, id="positional"),
    ]

    @pytest.mark.parametrize("args, kwargs, expected", CASES)
    async def test_client_connect(
        self, plain_client, gateway_calls, args, kwargs, expected
    ):
        with pytest.raises(StopConnect):
            await plain_client.connect(*args, **kwargs)

        assert len(gateway_calls) == 1
        assert gateway_calls[0]["ssl"] is expected

    @pytest.mark.parametrize("args, kwargs, expected", CASES)
    async def test_user_client_connect(
        self, alice, gateway_calls, args, kwargs, expected
    ):
        with pytest.raises(StopConnect):
            await alice.connect(UserPermission(chat=True), *args, **kwargs)

        assert len(gateway_calls) == 1
        assert gateway_calls[0]["ssl"] is expected
