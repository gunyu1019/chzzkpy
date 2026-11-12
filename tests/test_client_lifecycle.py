"""MIT License

Copyright (c) 2024-2025 gunyu1019

Lifecycle tests for the official chzzkpy package: the expiry check of a user client's
access token, releasing a client with `async with`, and paging through search results.

The mock Chzzk server and fixtures are shared with `test_multi_account.py`.
"""

import datetime

import pytest
import pytest_asyncio

from chzzkpy import AccessToken, Client, UserClient, UserPermission
from chzzkpy.base_model import ChannelSearchResult, Content
from chzzkpy.channel import FollowerInfo

from test_multi_account import client, monitor, server  # noqa: F401


@pytest_asyncio.fixture
async def plain_client():
    instance = Client("client-id", "client-secret")
    await instance._async_setup_hook()

    yield instance

    await instance.http.close()


def make_user_client(client: Client, expires_in: int = 86400) -> UserClient:
    access_token = AccessToken(
        access_token="a", refresh_token="r", expires_in=expires_in
    )
    return UserClient(client, access_token)


@pytest.mark.asyncio
class TestIsExpired:
    async def test_fresh_token_is_not_expired(self, plain_client):
        user_client = make_user_client(plain_client)

        assert user_client.is_expired is False

    async def test_token_within_expires_in_is_not_expired(self, plain_client):
        user_client = make_user_client(plain_client)
        user_client._token_generated_at = datetime.datetime.now() - datetime.timedelta(
            hours=23
        )

        assert user_client.is_expired is False

    async def test_token_older_than_expires_in_is_expired(self, plain_client):
        user_client = make_user_client(plain_client)
        user_client._token_generated_at = datetime.datetime.now() - datetime.timedelta(
            seconds=86400 + 60
        )

        assert user_client.is_expired is True

    async def test_expires_in_is_compared_in_seconds(self, plain_client):
        user_client = make_user_client(plain_client, expires_in=90)

        user_client._token_generated_at = datetime.datetime.now() - datetime.timedelta(
            seconds=60
        )
        assert user_client.is_expired is False

        user_client._token_generated_at = datetime.datetime.now() - datetime.timedelta(
            seconds=120
        )
        assert user_client.is_expired is True


@pytest.mark.asyncio
class TestAsyncContextManager:
    async def test_async_with_closes_http_session(self):
        async with Client("client-id", "client-secret") as entered:
            http = entered.http
            assert http is not None and not http.closed

        assert http.closed
        assert entered.http.closed

    async def test_exception_propagates_and_http_session_is_closed(self):
        with pytest.raises(RuntimeError, match="boom"):
            async with Client("client-id", "client-secret") as entered:
                raise RuntimeError("boom")

        assert entered.http.closed

    async def test_aexit_without_setup_is_noop(self):
        unused = Client("client-id", "client-secret")

        assert await unused.__aexit__(None, None, None) is None
        assert unused.http is None

    async def test_aexit_disconnects_client_and_user_sessions(self, server, client):
        alice = await client.get_user_client(server.add_account("alice"))
        bob = await client.get_user_client(server.add_account("bob"))
        await alice.connect(UserPermission(chat=True), addition_connect=True)
        await bob.connect(UserPermission(chat=True), addition_connect=True)
        first = await client.connect(addition_connect=True)
        second = await client.connect(addition_connect=True)
        gateways = [
            alice._gateway,
            bob._gateway,
            client._gateway[first],
            client._gateway[second],
        ]
        assert alice.is_connected and bob.is_connected

        await client.__aexit__(None, None, None)

        assert not alice.is_connected
        assert not bob.is_connected
        assert client._gateway == {}
        assert all(gateway.session.closed for gateway in gateways)
        assert client.http.closed

    async def test_aexit_closes_http_session_when_disconnect_fails(
        self, monkeypatch, client
    ):
        async def failing_disconnect(*args, **kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(client, "disconnect", failing_disconnect)

        with pytest.raises(RuntimeError, match="boom"):
            await client.__aexit__(None, None, None)

        assert client.http.closed


class TestSearchResult:
    FOLLOWERS = {
        "code": 200,
        "message": None,
        "content": {"data": [], "totalCount": 60, "totalPages": 2, "page": 0},
    }

    @pytest.mark.asyncio
    async def test_next_and_previous_use_the_page(self):
        requested = []

        async def get_followers(page: int):
            requested.append(page)
            payload = {**self.FOLLOWERS, "content": {**self.FOLLOWERS["content"]}}
            payload["content"]["page"] = page
            return Content[ChannelSearchResult[FollowerInfo]].model_validate(payload)

        first = (
            Content[ChannelSearchResult[FollowerInfo]]
            .model_validate(self.FOLLOWERS)
            .content
        )
        first._next_method = get_followers

        with pytest.raises(TypeError):
            await first.previous()

        second = await first.next()
        assert second._page == 1
        assert requested == [1]

        with pytest.raises(TypeError):
            await second.next()

        again = await second.previous()
        assert again._page == 0
        assert requested == [1, 0]
