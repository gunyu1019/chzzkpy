"""MIT License

Copyright (c) 2024-2025 gunyu1019

Tests for the Open API methods of `UserClient`: the requests they send (path, query, JSON
body, and the access token of the account they belong to) and how failures reach the caller.

Only chzzkpy's own logic is covered, not the (de)serialization of the data models. The mock
Chzzk server and fixtures are shared with `test_multi_account.py`.
"""

import asyncio
import datetime

import pytest

from chzzkpy.chat import ChatSetting
from chzzkpy.enums import FollowingPeriod
from chzzkpy.error import (
    BadRequestException,
    ForbiddenException,
    TooManyRequestsException,
    UnauthorizedException,
)

from test_multi_account import client, monitor, server  # noqa: F401

CHAT_SETTING_PATH = "/open/v1/chats/settings"
RESTRICTION_PATH = "/open/v1/restrict-channels"

# Every field set to something other than its default, so a field that is dropped or
# replaced by a default shows up.
CUSTOM_CHAT_SETTING = {
    "chatAvailableCondition": "REAL_NAME",
    "chatAvailableGroup": "FOLLOWER",
    "minFollowerMinute": 60,
    "allowSubscriberInFollowerMode": True,
    "chatSlowModeSec": 30,
    "chatEmojiMode": True,
}


def custom_chat_setting(**overrides) -> ChatSetting:
    values = dict(
        chat_available_condition="REAL_NAME",
        chat_available_group="FOLLOWER",
        min_follower_minute=FollowingPeriod.HOUR,
        allow_subscriber_in_follower_mode=True,
        chat_slow_mode_sec=30,
        chat_emoji_mode=True,
    )
    values.update(overrides)
    return ChatSetting(**values)


def chat_setting_updates(server) -> list[dict]:
    return [r for r in server.requests_to(CHAT_SETTING_PATH) if r["method"] == "PUT"]


def restriction_requests(server) -> list[dict]:
    return server.requests_to(RESTRICTION_PATH)


@pytest.mark.asyncio
class TestSetChatSetting:
    async def test_instance_sends_every_field_with_account_token(self, server, client):
        alice = await client.get_user_client(server.add_account("alice"))

        await alice.set_chat_setting(custom_chat_setting())

        [request] = chat_setting_updates(server)
        assert request["token"] == "token-alice"
        assert request["body"] == CUSTOM_CHAT_SETTING

    async def test_instance_without_slow_mode_and_emoji_mode_sends_their_defaults(
        self, server, client
    ):
        alice = await client.get_user_client(server.add_account("alice"))
        # A payload that has none of the two fields added to the setting later.
        setting = ChatSetting.model_validate(
            {
                "chatAvailableCondition": "NONE",
                "chatAvailableGroup": "ALL",
                "minFollowerMinute": 0,
                "allowSubscriberInFollowerMode": False,
            }
        )

        await alice.set_chat_setting(setting)

        [request] = chat_setting_updates(server)
        assert request["body"] == server.DEFAULT_CHAT_SETTING

    async def test_keyword_form_sends_every_field_with_account_token(
        self, server, client
    ):
        alice = await client.get_user_client(server.add_account("alice"))

        await alice.set_chat_setting(
            chat_available_condition="REAL_NAME",
            chat_available_group="FOLLOWER",
            min_follower_minute=FollowingPeriod.HOUR,
            allow_subscriber_in_follower_mode=True,
            slow_mode=30,
            emoji_mode=True,
        )

        [request] = chat_setting_updates(server)
        assert request["token"] == "token-alice"
        assert request["body"] == CUSTOM_CHAT_SETTING

    async def test_keyword_form_defaults_to_no_slow_mode_and_no_emoji_mode(
        self, server, client
    ):
        alice = await client.get_user_client(server.add_account("alice"))

        await alice.set_chat_setting(
            chat_available_condition="NONE",
            chat_available_group="ALL",
            min_follower_minute=FollowingPeriod.NONE,
            allow_subscriber_in_follower_mode=False,
        )

        [request] = chat_setting_updates(server)
        assert request["body"] == server.DEFAULT_CHAT_SETTING

    async def test_setting_read_with_get_can_be_written_back_unchanged(
        self, server, client
    ):
        alice = await client.get_user_client(server.add_account("alice"))
        server.chat_settings["alice"] = dict(CUSTOM_CHAT_SETTING)

        setting = await alice.get_chat_setting()
        await alice.set_chat_setting(setting)

        assert server.chat_settings["alice"] == CUSTOM_CHAT_SETTING
        assert len(chat_setting_updates(server)) == 1

    async def test_accounts_update_their_own_setting_concurrently(self, server, client):
        alice = await client.get_user_client(server.add_account("alice"))
        bob = await client.get_user_client(server.add_account("bob"))

        await asyncio.gather(
            alice.set_chat_setting(custom_chat_setting()),
            bob.set_chat_setting(
                custom_chat_setting(chat_slow_mode_sec=300, chat_emoji_mode=False)
            ),
        )

        assert server.chat_settings["alice"] == CUSTOM_CHAT_SETTING
        assert server.chat_settings["bob"] == {
            **CUSTOM_CHAT_SETTING,
            "chatSlowModeSec": 300,
            "chatEmojiMode": False,
        }
        tokens = {r["token"] for r in chat_setting_updates(server)}
        assert tokens == {"token-alice", "token-bob"}

    async def test_expired_token_is_refreshed_before_the_update(self, server, client):
        alice = await client.get_user_client(server.add_account("alice"))
        alice._token_generated_at = datetime.datetime.now() - datetime.timedelta(days=2)

        await alice.set_chat_setting(custom_chat_setting())

        [request] = chat_setting_updates(server)
        assert request["token"] == alice.access_token.access_token
        assert request["token"].startswith("token-alice-refreshed-")

    @pytest.mark.parametrize(
        "status, exception",
        [
            (400, BadRequestException),
            (403, ForbiddenException),
            (429, TooManyRequestsException),
        ],
    )
    async def test_rejected_update_raises_the_matching_exception(
        self, server, client, status, exception
    ):
        alice = await client.get_user_client(server.add_account("alice"))
        server.api_errors[("PUT", CHAT_SETTING_PATH)] = [status, status]

        with pytest.raises(exception):
            await alice.set_chat_setting(custom_chat_setting())
        with pytest.raises(exception):
            await alice.set_chat_setting(
                chat_available_condition="NONE",
                chat_available_group="ALL",
                min_follower_minute=FollowingPeriod.NONE,
                allow_subscriber_in_follower_mode=False,
            )

        assert "alice" not in server.chat_settings

    async def test_revoked_token_raises_unauthorized(self, server, client):
        alice = await client.get_user_client(server.add_account("alice"))
        del server.accounts["token-alice"]

        with pytest.raises(UnauthorizedException):
            await alice.set_chat_setting(custom_chat_setting())

    async def test_failed_update_can_be_retried(self, server, client):
        alice = await client.get_user_client(server.add_account("alice"))
        server.api_errors[("PUT", CHAT_SETTING_PATH)] = [403]

        with pytest.raises(ForbiddenException):
            await alice.set_chat_setting(custom_chat_setting())
        await alice.set_chat_setting(custom_chat_setting())

        assert server.chat_settings["alice"] == CUSTOM_CHAT_SETTING


@pytest.mark.asyncio
class TestGetRestriction:
    @staticmethod
    def channel_ids(page) -> list[str]:
        return [user.channel_id for user in page.data]

    async def test_first_page_asks_for_size_with_account_token(self, server, client):
        alice = await client.get_user_client(server.add_account("alice"))
        server.restricted_channels["alice"] = [f"alice-{i}" for i in range(5)]

        page = await alice.get_restriction(size=2)

        [request] = restriction_requests(server)
        assert request["method"] == "GET"
        assert request["token"] == "token-alice"
        assert request["query"] == {"size": "2"}
        assert self.channel_ids(page) == ["alice-0", "alice-1"]

    async def test_next_requests_following_page_with_cursor_and_token(
        self, server, client
    ):
        alice = await client.get_user_client(server.add_account("alice"))
        server.restricted_channels["alice"] = [f"alice-{i}" for i in range(5)]
        page = await alice.get_restriction(size=2)

        following = await page.next()

        assert self.channel_ids(following) == ["alice-2", "alice-3"]
        first, second = restriction_requests(server)
        assert second["token"] == first["token"] == "token-alice"
        assert second["query"] == {"size": "2", "next": "2"}

    async def test_paging_walks_every_restricted_channel_once_in_order(
        self, server, client
    ):
        alice = await client.get_user_client(server.add_account("alice"))
        expected = [f"alice-{i}" for i in range(5)]
        server.restricted_channels["alice"] = expected

        page = await alice.get_restriction(size=2)
        collected = self.channel_ids(page)
        for _ in range(2):
            page = await page.next()
            collected += self.channel_ids(page)

        assert collected == expected
        assert [r["query"] for r in restriction_requests(server)] == [
            {"size": "2"},
            {"size": "2", "next": "2"},
            {"size": "2", "next": "4"},
        ]
        assert {r["token"] for r in restriction_requests(server)} == {"token-alice"}

    async def test_accounts_do_not_mix_tokens_while_paging(self, server, client):
        alice = await client.get_user_client(server.add_account("alice"))
        bob = await client.get_user_client(server.add_account("bob"))
        server.restricted_channels["alice"] = [f"alice-{i}" for i in range(4)]
        server.restricted_channels["bob"] = [f"bob-{i}" for i in range(4)]
        alice_page, bob_page = await asyncio.gather(
            alice.get_restriction(size=2), bob.get_restriction(size=2)
        )

        # Each token only lists the restrictions of its own account, so a page of
        # another account's channels means the wrong token was sent.
        alice_next, bob_next = await asyncio.gather(alice_page.next(), bob_page.next())

        assert self.channel_ids(alice_next) == ["alice-2", "alice-3"]
        assert self.channel_ids(bob_next) == ["bob-2", "bob-3"]
        following = [r for r in restriction_requests(server) if "next" in r["query"]]
        assert sorted(r["token"] for r in following) == ["token-alice", "token-bob"]

    async def test_unauthorized_token_raises_on_first_page(self, server, client):
        alice = await client.get_user_client(server.add_account("alice"))
        del server.accounts["token-alice"]

        with pytest.raises(UnauthorizedException):
            await alice.get_restriction()

    async def test_revoked_token_raises_unauthorized_on_next_page(self, server, client):
        alice = await client.get_user_client(server.add_account("alice"))
        server.restricted_channels["alice"] = [f"alice-{i}" for i in range(4)]
        page = await alice.get_restriction(size=2)
        del server.accounts["token-alice"]

        with pytest.raises(UnauthorizedException):
            await page.next()

    async def test_failed_next_page_can_be_retried(self, server, client):
        alice = await client.get_user_client(server.add_account("alice"))
        server.restricted_channels["alice"] = [f"alice-{i}" for i in range(4)]
        page = await alice.get_restriction(size=2)
        server.api_errors[("GET", RESTRICTION_PATH)] = [429]

        with pytest.raises(TooManyRequestsException):
            await page.next()
        following = await page.next()

        assert self.channel_ids(following) == ["alice-2", "alice-3"]
        retried = restriction_requests(server)[-1]
        assert retried["query"] == {"size": "2", "next": "2"}
        assert retried["token"] == "token-alice"
