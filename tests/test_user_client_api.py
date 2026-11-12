"""MIT License

Copyright (c) 2024-2025 gunyu1019

Tests for the Open API methods of `UserClient`, the paged methods of `Client` and the
action methods of the received messages: the requests they send (path, HTTP method, query,
JSON body, and the access token of the account they belong to), how they page, and how
failures reach the caller.

Only chzzkpy's own logic is covered, not the (de)serialization of the data models. The mock
Chzzk server and fixtures are shared with `test_multi_account.py`.
"""

import asyncio
import datetime
import math

import pytest

from chzzkpy import UserPermission
from chzzkpy.category import Category
from chzzkpy.chat import ChatSetting
from chzzkpy.enums import FollowingPeriod
from chzzkpy.error import (
    BadRequestException,
    ForbiddenException,
    NotFoundException,
    TooManyRequestsException,
    UnauthorizedException,
)
from chzzkpy.live import BrodecastSetting
from chzzkpy.message import Donation, Message, SentMessage, Subscription
from chzzkpy.state import ConnectionState

from test_multi_account import (  # noqa: F401
    client,
    events,
    monitor,
    server,
)
from test_multi_account import chat_payload, donation_payload, subscription_payload

CHAT_SETTING_PATH = "/open/v1/chats/settings"
RESTRICTION_PATH = "/open/v1/restrict-channels"
TEMPORARY_RESTRICTION_PATH = "/open/v1/temporary-restrict-channels"
LIVE_SETTING_PATH = "/open/v1/lives/setting"
SEND_PATH = "/open/v1/chats/send"
NOTICE_PATH = "/open/v1/chats/notice"
BLIND_PATH = "/open/v1/chats/blind-message"
FOLLOWERS_PATH = "/open/v1/channels/followers"
SUBSCRIBERS_PATH = "/open/v1/channels/subscribers"
CHANNELS_PATH = "/open/v1/channels"
LIVES_PATH = "/open/v1/lives"
CATEGORIES_PATH = "/open/v1/categories/search"
TOKEN_PATH = "/auth/v1/token"

# What the API answers a rejected request with, and what chzzkpy raises for it.
API_ERRORS = [
    (400, BadRequestException),
    (401, UnauthorizedException),
    (403, ForbiddenException),
    (404, NotFoundException),
    (429, TooManyRequestsException),
]

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


def api_requests(server, method: str, path: str) -> list[dict]:
    """The requests to one route (`requests_to` matches every path with the prefix)."""
    return [r for r in server.requests if r["method"] == method and r["path"] == path]


async def connect_accounts(client, server, *names, permission=None):
    """Adds accounts to the mock server and connects a user session for each of them."""
    permission = permission or UserPermission(chat=True)
    accounts = []
    for name in names:
        account = await client.get_user_client(server.add_account(name))
        await account.connect(permission, addition_connect=True)
        accounts.append(account)
    return accounts


async def receive(server, events, session, event: str, payload: dict):
    """Delivers an event on a session and returns what the client's handler got."""
    await server.push(session, event.upper(), payload)
    return await events.next(event)


# The ids and the time of what an account receives differ per account, so that a request
# built from another account's message shows.
MESSAGE_TIMES = {"alice": 1_700_000_000_123, "bob": 1_700_000_005_456}


def chat_of(name: str, **overrides) -> dict:
    """A chat that a viewer sends in the channel of an account."""
    payload = chat_payload(f"channel-{name}", f"hello {name}")
    payload.update(
        senderChannelId=f"viewer-of-{name}",
        chatChannelId=f"live-of-{name}",
        messageTime=MESSAGE_TIMES.get(name, 1_700_000_009_789),
    )
    payload.update(overrides)
    return payload


class DerivedFrom:
    """Equal to a number that is the Unix time of `moment`, in seconds or milliseconds.

    The documentation only says that the time of a message to blind is a `long`
    "timestamp", without a unit. chzzkpy sends `moment.timestamp()` (seconds, a float)
    while the `messageTime` of a received chat is in epoch milliseconds, so the unit the
    API expects is unverified. Both are accepted: what is checked is that the value is
    derived from the given datetime, not which unit it is in.
    """

    def __init__(self, moment: datetime.datetime):
        self.moment = moment

    def __eq__(self, other) -> bool:
        if isinstance(other, bool) or not isinstance(other, (int, float)):
            return False
        seconds = self.moment.timestamp()
        return any(
            math.isclose(other, expected, abs_tol=1e-3)
            for expected in (seconds, seconds * 1000)
        )

    __hash__ = None

    def __repr__(self) -> str:
        return f"DerivedFrom({self.moment.isoformat()})"


def moment_of(payload: dict) -> datetime.datetime:
    return datetime.datetime.fromtimestamp(
        payload["messageTime"] / 1000, datetime.timezone.utc
    )


# The action methods of a received `Message`: (method, HTTP method, route, the body that
# the chat payload it was received with has to produce).
MESSAGE_ACTIONS = [
    (
        "blind",
        "POST",
        BLIND_PATH,
        lambda p: {
            "chatChannelId": p["chatChannelId"],
            "senderChannelId": p["senderChannelId"],
            "messageTime": DerivedFrom(moment_of(p)),
        },
    ),
    (
        "add_temporal_restrict",
        "POST",
        TEMPORARY_RESTRICTION_PATH,
        lambda p: {
            "targetChannelId": p["senderChannelId"],
            "chatChannelId": p["chatChannelId"],
        },
    ),
    (
        "remove_temporal_restrict",
        "DELETE",
        TEMPORARY_RESTRICTION_PATH,
        lambda p: {
            "targetChannelId": p["senderChannelId"],
            "chatChannelId": p["chatChannelId"],
        },
    ),
    (
        "add_permanent_restrict",
        "POST",
        RESTRICTION_PATH,
        lambda p: {"targetChannelId": p["senderChannelId"]},
    ),
    (
        "remove_permanent_restrict",
        "DELETE",
        RESTRICTION_PATH,
        lambda p: {"targetChannelId": p["senderChannelId"]},
    ),
]
ACTION_PARAMS = [pytest.param(*row, id=row[0]) for row in MESSAGE_ACTIONS]


def action_invoker(name: str):
    async def invoke(message):
        await getattr(message, name)()

    return invoke


async def invoke_send(message):
    await message.send("reply")


async def invoke_send_and_pin(message):
    sent = await message.send("reply")
    await sent.pin()


# Everything a received message can do: (HTTP method, route, how to do it). Pinning goes
# through a sent message, so a rejection of the notice route is what makes it fail.
MESSAGE_CALLS = [
    pytest.param(method, path, action_invoker(name), id=name)
    for name, method, path, _ in MESSAGE_ACTIONS
] + [
    pytest.param("POST", SEND_PATH, invoke_send, id="send"),
    pytest.param("POST", NOTICE_PATH, invoke_send_and_pin, id="send_and_pin"),
]


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


# ---------------------------------------------------------------------------------------
# Follow period of the chat setting
# ---------------------------------------------------------------------------------------


@pytest.mark.asyncio
class TestChatSettingFollowPeriod:
    @pytest.mark.parametrize("minutes", [129600, 172800, 216000, 259200])
    async def test_get_chat_setting_returns_the_follow_period_of_the_channel(
        self, server, client, minutes
    ):
        alice = await client.get_user_client(server.add_account("alice"))
        server.chat_settings["alice"] = {
            **server.DEFAULT_CHAT_SETTING,
            "chatAvailableGroup": "FOLLOWER",
            "minFollowerMinute": minutes,
        }

        setting = await alice.get_chat_setting()

        assert setting.min_follower_minute == minutes

    @pytest.mark.parametrize(
        "period, minutes",
        [
            pytest.param(FollowingPeriod.FOUR_MONTH, 172800, id="four-months"),
            pytest.param(FollowingPeriod.FIVE_MONTH, 216000, id="five-months"),
            pytest.param(FollowingPeriod.SIX_MONTH, 259200, id="six-months"),
        ],
    )
    async def test_set_chat_setting_sends_the_minutes_of_the_period(
        self, server, client, period, minutes
    ):
        alice = await client.get_user_client(server.add_account("alice"))

        await alice.set_chat_setting(
            chat_available_condition="NONE",
            chat_available_group="FOLLOWER",
            min_follower_minute=period,
            allow_subscriber_in_follower_mode=False,
        )

        [request] = chat_setting_updates(server)
        assert request["body"]["minFollowerMinute"] == minutes


# ---------------------------------------------------------------------------------------
# Actions of the messages received by the event handlers
# ---------------------------------------------------------------------------------------


@pytest.mark.asyncio
class TestMessageActions:
    """`Message` action methods, on chats received through the user session of each
    account. A request has to carry the token of the account that received the chat and
    the ids of that chat."""

    @pytest.mark.parametrize("action, http_method, path, body_of", ACTION_PARAMS)
    async def test_action_sends_the_ids_of_the_message_with_the_receiving_accounts_token(
        self, server, client, events, action, http_method, path, body_of
    ):
        await connect_accounts(client, server, "alice", "bob")

        for name in ("alice", "bob"):
            message = await receive(
                server, events, server.session_of(name), "chat", chat_of(name)
            )
            assert await getattr(message, action)() is None

        assert [
            (r["token"], r["body"]) for r in api_requests(server, http_method, path)
        ] == [
            ("token-alice", body_of(chat_of("alice"))),
            ("token-bob", body_of(chat_of("bob"))),
        ]
        assert not api_requests(server, http_method, path)[0]["query"]

    @pytest.mark.parametrize("action, http_method, path, body_of", ACTION_PARAMS)
    async def test_concurrent_actions_of_two_accounts_keep_their_tokens_and_ids(
        self, server, client, events, action, http_method, path, body_of
    ):
        await connect_accounts(client, server, "alice", "bob")
        messages = {
            name: await receive(
                server, events, server.session_of(name), "chat", chat_of(name)
            )
            for name in ("alice", "bob")
        }

        await asyncio.gather(
            *(
                getattr(messages[name], action)()
                for _ in range(10)
                for name in ("alice", "bob")
            )
        )

        requests = api_requests(server, http_method, path)
        assert len(requests) == 20
        for request in requests:
            name = request["token"].removeprefix("token-")
            assert request["body"] == body_of(chat_of(name))

    async def test_blind_time_follows_the_time_of_each_message(
        self, server, client, events
    ):
        await connect_accounts(client, server, "alice")
        session = server.session_of("alice")
        earlier = await receive(
            server,
            events,
            session,
            "chat",
            chat_of("alice", messageTime=1_700_000_000_000),
        )
        later = await receive(
            server,
            events,
            session,
            "chat",
            chat_of("alice", messageTime=1_700_000_042_000),
        )

        await later.blind()
        await earlier.blind()

        later_request, earlier_request = api_requests(server, "POST", BLIND_PATH)
        assert later_request["body"]["messageTime"] == DerivedFrom(later.created_time)
        assert earlier_request["body"]["messageTime"] == DerivedFrom(
            earlier.created_time
        )
        # Whatever the unit is, 42 seconds later is a larger number.
        assert (
            later_request["body"]["messageTime"]
            > earlier_request["body"]["messageTime"]
        )

    async def test_permanent_restrict_changes_the_restrictions_of_the_receiving_account(
        self, server, client, events
    ):
        alice, bob = await connect_accounts(client, server, "alice", "bob")
        message = await receive(
            server, events, server.session_of("bob"), "chat", chat_of("bob")
        )

        await message.add_permanent_restrict()

        assert server.restricted_channels == {"bob": ["viewer-of-bob"]}
        assert (await alice.get_restriction()).data == []
        assert [u.channel_id for u in (await bob.get_restriction()).data] == [
            "viewer-of-bob"
        ]

        await message.remove_permanent_restrict()

        assert server.restricted_channels == {"bob": []}

    @pytest.mark.parametrize("http_method, path, invoke", MESSAGE_CALLS)
    @pytest.mark.parametrize("status, exception", API_ERRORS)
    async def test_rejected_call_raises_the_matching_exception_and_can_be_retried(
        self, server, client, events, http_method, path, invoke, status, exception
    ):
        await connect_accounts(client, server, "alice")
        message = await receive(
            server, events, server.session_of("alice"), "chat", chat_of("alice")
        )
        server.api_errors[(http_method, path)] = [status]

        with pytest.raises(exception):
            await invoke(message)
        assert len(api_requests(server, http_method, path)) == 1

        await invoke(message)
        assert len(api_requests(server, http_method, path)) == 2

    @pytest.mark.parametrize("http_method, path, invoke", MESSAGE_CALLS)
    async def test_revoked_token_raises_unauthorized(
        self, server, client, events, http_method, path, invoke
    ):
        await connect_accounts(client, server, "alice", "bob")
        message = await receive(
            server, events, server.session_of("alice"), "chat", chat_of("alice")
        )
        del server.accounts["token-alice"]
        before = len(server.requests)

        with pytest.raises(UnauthorizedException):
            await invoke(message)

        # Only the token of the account was tried, not the one of the other account.
        assert {r["token"] for r in server.requests[before:]} == {"token-alice"}


@pytest.mark.asyncio
class TestMessageActionsOnClientSession:
    """Several accounts subscribed to one client session: the token of the message is
    that of the account that owns the channel the chat was sent in."""

    @staticmethod
    async def subscribe_accounts(client, server, *names, permission=None):
        permission = permission or UserPermission(chat=True)
        accounts = [
            await client.get_user_client(server.add_account(name)) for name in names
        ]
        await client.connect(addition_connect=True)
        session = server.session_of(None)
        for account in accounts:
            await account.subscribe(permission, session.key)
        return session

    @pytest.mark.parametrize("action, http_method, path, body_of", ACTION_PARAMS)
    async def test_action_goes_out_with_the_token_of_the_channel_owner(
        self, server, client, events, action, http_method, path, body_of
    ):
        session = await self.subscribe_accounts(client, server, "alice", "bob")

        # The chat of bob's channel arrives first, so a token picked by arrival order
        # (or the first account's) is wrong for it.
        for name in ("bob", "alice"):
            message = await receive(server, events, session, "chat", chat_of(name))
            await getattr(message, action)()

        assert [
            (r["token"], r["body"]) for r in api_requests(server, http_method, path)
        ] == [
            ("token-bob", body_of(chat_of("bob"))),
            ("token-alice", body_of(chat_of("alice"))),
        ]

    @pytest.mark.parametrize("action, http_method, path, body_of", ACTION_PARAMS)
    async def test_concurrent_actions_keep_their_tokens_and_ids(
        self, server, client, events, action, http_method, path, body_of
    ):
        session = await self.subscribe_accounts(client, server, "alice", "bob")
        messages = {
            name: await receive(server, events, session, "chat", chat_of(name))
            for name in ("alice", "bob")
        }

        await asyncio.gather(
            *(
                getattr(messages[name], action)()
                for _ in range(10)
                for name in ("alice", "bob")
            )
        )

        requests = api_requests(server, http_method, path)
        assert len(requests) == 20
        for request in requests:
            name = request["token"].removeprefix("token-")
            assert request["body"] == body_of(chat_of(name))

    @pytest.mark.parametrize("http_method, path, invoke", MESSAGE_CALLS)
    async def test_message_of_a_channel_without_account_cannot_act(
        self, server, client, events, http_method, path, invoke
    ):
        session = await self.subscribe_accounts(client, server, "alice")
        message = await receive(server, events, session, "chat", chat_of("stranger"))

        with pytest.raises(RuntimeError):
            await invoke(message)

        assert api_requests(server, http_method, path) == []

    @pytest.mark.parametrize(
        "event, payload_of",
        [("donation", donation_payload), ("subscription", subscription_payload)],
    )
    async def test_donation_and_subscription_are_answered_with_the_token_of_the_channel_owner(
        self, server, client, events, event, payload_of
    ):
        session = await self.subscribe_accounts(
            client, server, "alice", "bob", permission=UserPermission.all()
        )

        for name in ("bob", "alice"):
            message = await receive(
                server, events, session, event, payload_of(f"channel-{name}")
            )
            sent = await message.send(f"thanks {name}")
            await sent.pin()

        sends = api_requests(server, "POST", SEND_PATH)
        assert [(r["token"], r["body"]["message"]) for r in sends] == [
            ("token-bob", "thanks bob"),
            ("token-alice", "thanks alice"),
        ]
        notices = api_requests(server, "POST", NOTICE_PATH)
        assert [(n["token"], n["body"]["messageId"]) for n in notices] == [
            (r["token"], r["message_id"]) for r in sends
        ]

    async def test_send_replies_in_the_channel_with_the_token_of_its_owner(
        self, server, client, events
    ):
        session = await self.subscribe_accounts(client, server, "alice", "bob")
        message = await receive(server, events, session, "chat", chat_of("bob"))

        sent = await message.send("reply to bob")
        await sent.pin()

        [send_request] = api_requests(server, "POST", SEND_PATH)
        [notice] = api_requests(server, "POST", NOTICE_PATH)
        assert (send_request["token"], send_request["body"]) == (
            "token-bob",
            {"message": "reply to bob"},
        )
        assert notice["token"] == "token-bob"
        assert notice["body"]["messageId"] == send_request["message_id"] == sent.id


@pytest.mark.asyncio
class TestMessageWithoutAuthentication:
    """A message that was not received through a session (so it only stores data), or
    that no account can act for, refuses to act and sends nothing."""

    UNATTACHED = [
        pytest.param(
            lambda: Message.model_validate(chat_of("alice")), "blind", (), id="blind"
        ),
        pytest.param(
            lambda: Message.model_validate(chat_of("alice")),
            "add_temporal_restrict",
            (),
            id="add_temporal_restrict",
        ),
        pytest.param(
            lambda: Message.model_validate(chat_of("alice")),
            "remove_temporal_restrict",
            (),
            id="remove_temporal_restrict",
        ),
        pytest.param(
            lambda: Message.model_validate(chat_of("alice")),
            "add_permanent_restrict",
            (),
            id="add_permanent_restrict",
        ),
        pytest.param(
            lambda: Message.model_validate(chat_of("alice")),
            "remove_permanent_restrict",
            (),
            id="remove_permanent_restrict",
        ),
        pytest.param(
            lambda: Message.model_validate(chat_of("alice")),
            "send",
            ("reply",),
            id="Message.send",
        ),
        pytest.param(
            lambda: Donation.model_validate(donation_payload("channel-alice")),
            "send",
            ("thanks",),
            id="Donation.send",
        ),
        pytest.param(
            lambda: Subscription.model_validate(subscription_payload("channel-alice")),
            "send",
            ("thanks",),
            id="Subscription.send",
        ),
        pytest.param(
            lambda: SentMessage(id="message-1", content="reply"), "pin", (), id="pin"
        ),
    ]

    @pytest.mark.parametrize("factory, method, arguments", UNATTACHED)
    async def test_message_without_state_and_token_raises_runtime_error(
        self, server, factory, method, arguments
    ):
        message = factory()

        with pytest.raises(RuntimeError):
            await getattr(message, method)(*arguments)

        assert server.requests == []

    @pytest.mark.parametrize("factory, method, arguments", UNATTACHED)
    async def test_message_with_a_token_but_without_state_raises_runtime_error(
        self, server, factory, method, arguments
    ):
        message = factory()
        message._access_token = server.add_account("alice")

        with pytest.raises(RuntimeError):
            await getattr(message, method)(*arguments)

        assert server.requests == []

    @pytest.mark.parametrize("factory, method, arguments", UNATTACHED)
    async def test_message_with_state_but_without_a_token_raises_runtime_error(
        self, server, client, factory, method, arguments
    ):
        message = factory()
        message._state = ConnectionState(
            dispatch=client.dispatch, handler={}, http=client.http
        )

        with pytest.raises(RuntimeError):
            await getattr(message, method)(*arguments)

        assert server.requests == []

    async def test_state_and_token_given_to_the_constructor_are_used(
        self, server, client
    ):
        token = server.add_account("alice")
        state = ConnectionState(dispatch=client.dispatch, handler={}, http=client.http)
        donation = Donation(
            **donation_payload("channel-alice"), state=state, access_token=token
        )

        sent = await donation.send("thanks")
        await sent.pin()

        [send_request] = api_requests(server, "POST", SEND_PATH)
        [notice] = api_requests(server, "POST", NOTICE_PATH)
        assert send_request["token"] == notice["token"] == "token-alice"
        assert notice["body"]["messageId"] == send_request["message_id"]

    @pytest.mark.parametrize(
        "model, payload",
        [
            pytest.param(Donation, donation_payload("channel-alice"), id="Donation"),
            pytest.param(
                Subscription, subscription_payload("channel-alice"), id="Subscription"
            ),
            pytest.param(Message, chat_of("alice"), id="Message"),
        ],
    )
    async def test_token_given_to_the_constructor_is_not_exposed(
        self, server, client, model, payload
    ):
        token = server.add_account("alice")
        state = ConnectionState(dispatch=client.dispatch, handler={}, http=client.http)
        message = model(**payload, state=state, access_token=token)

        exposed = repr(message) + str(message.model_dump())
        assert token.access_token not in exposed
        assert "state" not in message.model_dump()
        assert "access_token" not in message.model_dump()

    async def test_message_with_state_and_token_keeps_its_emojis_and_sends(
        self, server, client
    ):
        token = server.add_account("alice")
        state = ConnectionState(dispatch=client.dispatch, handler={}, http=client.http)
        payload = chat_of("alice", emojis={"smile": "https://example.com/smile.png"})
        message = Message(**payload, state=state, access_token=token)

        sent = await message.send("reply")

        assert [(e.id, e.url) for e in message.emojis] == [
            ("smile", "https://example.com/smile.png")
        ]
        [request] = api_requests(server, "POST", SEND_PATH)
        assert (request["token"], request["body"]) == (
            "token-alice",
            {"message": "reply"},
        )
        assert sent.id == request["message_id"]


@pytest.mark.asyncio
class TestSentMessage:
    """`Messageable.send` and `SentMessage.pin`: the sent message belongs to the account
    that sent it."""

    async def test_send_returns_the_message_with_the_id_the_server_answered(
        self, server, client, events
    ):
        await connect_accounts(client, server, "alice")
        message = await receive(
            server, events, server.session_of("alice"), "chat", chat_of("alice")
        )

        sent = await message.send("reply")

        [request] = api_requests(server, "POST", SEND_PATH)
        assert request["body"] == {"message": "reply"}
        assert (sent.id, sent.content) == (request["message_id"], "reply")

    async def test_pin_announces_the_sent_message_with_the_token_that_sent_it(
        self, server, client, events
    ):
        await connect_accounts(client, server, "alice", "bob")
        message = await receive(
            server, events, server.session_of("bob"), "chat", chat_of("bob")
        )
        sent = await message.send("reply")

        await sent.pin()

        [send_request] = api_requests(server, "POST", SEND_PATH)
        [notice] = api_requests(server, "POST", NOTICE_PATH)
        assert notice["token"] == send_request["token"] == "token-bob"
        assert notice["body"]["messageId"] == send_request["message_id"]
        # The message is announced by its id, not sent again as new content.
        assert notice["body"].get("message") is None

    async def test_two_accounts_pin_their_own_sent_messages_concurrently(
        self, server, client, events
    ):
        await connect_accounts(client, server, "alice", "bob")
        messages = {
            name: await receive(
                server, events, server.session_of(name), "chat", chat_of(name)
            )
            for name in ("alice", "bob")
        }
        sent = {}
        for name in ("alice", "bob"):
            sent[name] = await asyncio.gather(
                *(messages[name].send(f"{name}-{index}") for index in range(5))
            )

        await asyncio.gather(
            *(
                sent[name][index].pin()
                for index in range(5)
                for name in ("alice", "bob")
            )
        )

        sent_by = {
            r["message_id"]: r["token"] for r in api_requests(server, "POST", SEND_PATH)
        }
        notices = api_requests(server, "POST", NOTICE_PATH)
        assert len(notices) == 10
        assert {n["body"]["messageId"] for n in notices} == set(sent_by)
        for notice in notices:
            assert notice["token"] == sent_by[notice["body"]["messageId"]]

    @pytest.mark.parametrize(
        "event, payload",
        [
            ("donation", donation_payload("channel-bob")),
            ("subscription", subscription_payload("channel-bob")),
        ],
    )
    async def test_donation_and_subscription_can_be_answered_and_pinned(
        self, server, client, events, event, payload
    ):
        await connect_accounts(
            client, server, "alice", "bob", permission=UserPermission.all()
        )
        message = await receive(
            server, events, server.session_of("bob"), event, payload
        )

        sent = await message.send("thank you")
        await sent.pin()

        [send_request] = api_requests(server, "POST", SEND_PATH)
        [notice] = api_requests(server, "POST", NOTICE_PATH)
        assert send_request["token"] == notice["token"] == "token-bob"
        assert send_request["body"] == {"message": "thank you"}
        assert notice["body"]["messageId"] == sent.id == send_request["message_id"]


# ---------------------------------------------------------------------------------------
# UserClient methods that transform their arguments
# ---------------------------------------------------------------------------------------

GAME = Category(categoryId="game-1", categoryValue="Game One", categoryType="GAME")
SPORTS = Category(
    categoryId="sports-1", categoryValue="Sports One", categoryType="SPORTS"
)


def live_setting_updates(server) -> list[dict]:
    return api_requests(server, "PATCH", LIVE_SETTING_PATH)


@pytest.mark.asyncio
class TestSetLiveSetting:
    async def test_instance_sends_title_category_and_tags_with_account_token(
        self, server, client
    ):
        alice = await client.get_user_client(server.add_account("alice"))
        setting = BrodecastSetting(
            defaultLiveTitle="on air", category=GAME, tags=["chat", "game"]
        )

        await alice.set_live_setting(setting)

        [request] = live_setting_updates(server)
        assert request["token"] == "token-alice"
        assert request["body"] == {
            "defaultLiveTitle": "on air",
            "categoryId": "game-1",
            "categoryType": "GAME",
            "tags": ["chat", "game"],
        }

    async def test_keyword_form_turns_a_category_into_its_id_and_type(
        self, server, client
    ):
        alice = await client.get_user_client(server.add_account("alice"))

        await alice.set_live_setting(title="on air", category=SPORTS, tags=["a", "b"])

        [request] = live_setting_updates(server)
        assert request["token"] == "token-alice"
        assert request["body"] == {
            "defaultLiveTitle": "on air",
            "categoryId": "sports-1",
            "categoryType": "SPORTS",
            "tags": ["a", "b"],
        }

    async def test_keyword_form_without_category_sends_null_category(
        self, server, client
    ):
        alice = await client.get_user_client(server.add_account("alice"))

        await alice.set_live_setting(title="on air", category=None, tags=["a"])

        [request] = live_setting_updates(server)
        assert request["body"] == {
            "defaultLiveTitle": "on air",
            "categoryId": None,
            "categoryType": None,
            "tags": ["a"],
        }

    async def test_keyword_form_sends_nothing_for_what_is_not_given(
        self, server, client
    ):
        alice = await client.get_user_client(server.add_account("alice"))

        await alice.set_live_setting(category=GAME)

        [request] = live_setting_updates(server)
        assert request["body"] == {
            "defaultLiveTitle": None,
            "categoryId": "game-1",
            "categoryType": "GAME",
            "tags": None,
        }

    async def test_empty_tags_are_not_sent_as_null(self, server, client):
        alice = await client.get_user_client(server.add_account("alice"))

        await alice.set_live_setting(title="on air", tags=[])
        await alice.set_live_setting(
            BrodecastSetting(defaultLiveTitle="on air", category=GAME, tags=[])
        )

        keyword_request, instance_request = live_setting_updates(server)
        assert keyword_request["body"]["tags"] == []
        assert instance_request["body"]["tags"] == []

    async def test_category_without_a_type_sends_its_id_and_a_null_type(
        self, server, client
    ):
        alice = await client.get_user_client(server.add_account("alice"))
        category = Category(categoryId="etc-1", categoryValue="Etc", categoryType=None)

        await alice.set_live_setting(title="on air", category=category)
        await alice.set_live_setting(
            BrodecastSetting(defaultLiveTitle="on air", category=category, tags=[])
        )

        for request in live_setting_updates(server):
            assert request["body"]["categoryId"] == "etc-1"
            assert request["body"]["categoryType"] is None

    async def test_accounts_update_their_own_live_setting_concurrently(
        self, server, client
    ):
        alice = await client.get_user_client(server.add_account("alice"))
        bob = await client.get_user_client(server.add_account("bob"))

        await asyncio.gather(
            alice.set_live_setting(title="alice live", category=GAME),
            bob.set_live_setting(
                BrodecastSetting(defaultLiveTitle="bob live", category=SPORTS, tags=[])
            ),
        )

        by_token = {r["token"]: r["body"] for r in live_setting_updates(server)}
        assert by_token["token-alice"]["defaultLiveTitle"] == "alice live"
        assert by_token["token-alice"]["categoryId"] == "game-1"
        assert by_token["token-bob"]["defaultLiveTitle"] == "bob live"
        assert by_token["token-bob"]["categoryId"] == "sports-1"
        assert len(by_token) == 2

    @pytest.mark.parametrize("status, exception", API_ERRORS)
    async def test_rejected_update_raises_the_matching_exception(
        self, server, client, status, exception
    ):
        alice = await client.get_user_client(server.add_account("alice"))
        server.api_errors[("PATCH", LIVE_SETTING_PATH)] = [status, status]

        with pytest.raises(exception):
            await alice.set_live_setting(title="on air")
        with pytest.raises(exception):
            await alice.set_live_setting(
                BrodecastSetting(defaultLiveTitle="on air", category=GAME, tags=[])
            )

        await alice.set_live_setting(title="on air")
        assert len(live_setting_updates(server)) == 3

    async def test_revoked_token_raises_unauthorized(self, server, client):
        alice = await client.get_user_client(server.add_account("alice"))
        del server.accounts["token-alice"]

        with pytest.raises(UnauthorizedException):
            await alice.set_live_setting(title="on air")


@pytest.mark.asyncio
class TestSendMessage:
    """`UserClient.send_message`, which works without a connected session."""

    async def test_sends_the_content_and_returns_the_message_the_server_created(
        self, server, client
    ):
        alice = await client.get_user_client(server.add_account("alice"))

        sent = await alice.send_message("hello chat")

        [request] = api_requests(server, "POST", SEND_PATH)
        assert request["token"] == "token-alice"
        assert request["body"] == {"message": "hello chat"}
        assert isinstance(sent, SentMessage)
        assert (sent.id, sent.content) == (request["message_id"], "hello chat")

    async def test_pin_of_the_returned_message_uses_the_token_that_sent_it(
        self, server, client
    ):
        await client.get_user_client(server.add_account("alice"))
        bob = await client.get_user_client(server.add_account("bob"))
        before = len(server.requests)
        sent = await bob.send_message("pin me")

        await sent.pin()

        [send_request] = api_requests(server, "POST", SEND_PATH)
        [notice] = api_requests(server, "POST", NOTICE_PATH)
        assert notice["token"] == send_request["token"] == "token-bob"
        assert notice["body"]["messageId"] == send_request["message_id"]
        assert notice["body"].get("message") is None
        assert {r["token"] for r in server.requests[before:]} == {"token-bob"}

    async def test_accounts_send_and_pin_their_own_messages_concurrently(
        self, server, client
    ):
        alice = await client.get_user_client(server.add_account("alice"))
        bob = await client.get_user_client(server.add_account("bob"))

        async def send_and_pin(account, content):
            sent = await account.send_message(content)
            await sent.pin()

        await asyncio.gather(
            *(
                send_and_pin(account, f"{name}-{index}")
                for index in range(5)
                for name, account in (("alice", alice), ("bob", bob))
            )
        )

        sent_by = {
            r["message_id"]: (r["token"], r["body"]["message"])
            for r in api_requests(server, "POST", SEND_PATH)
        }
        notices = api_requests(server, "POST", NOTICE_PATH)
        assert len(sent_by) == len(notices) == 10
        for notice in notices:
            token, content = sent_by[notice["body"]["messageId"]]
            assert notice["token"] == token == f"token-{content.split('-')[0]}"

    async def test_message_sent_after_a_refresh_is_pinned_with_the_refreshed_token(
        self, server, client
    ):
        alice = await client.get_user_client(server.add_account("alice"))
        alice._token_generated_at = datetime.datetime.now() - datetime.timedelta(days=2)

        sent = await alice.send_message("after refresh")
        await sent.pin()

        refreshed = alice.access_token.access_token
        assert refreshed.startswith("token-alice-refreshed-")
        [send_request] = api_requests(server, "POST", SEND_PATH)
        [notice] = api_requests(server, "POST", NOTICE_PATH)
        assert send_request["token"] == notice["token"] == refreshed

    @pytest.mark.parametrize("status, exception", API_ERRORS)
    async def test_rejected_message_raises_the_matching_exception(
        self, server, client, status, exception
    ):
        alice = await client.get_user_client(server.add_account("alice"))
        server.api_errors[("POST", SEND_PATH)] = [status]

        with pytest.raises(exception):
            await alice.send_message("rejected")
        sent = await alice.send_message("accepted")

        assert [
            r["body"]["message"] for r in api_requests(server, "POST", SEND_PATH)
        ] == [
            "rejected",
            "accepted",
        ]
        assert sent.content == "accepted"

    @pytest.mark.parametrize("status, exception", API_ERRORS)
    async def test_rejected_pin_raises_the_matching_exception(
        self, server, client, status, exception
    ):
        alice = await client.get_user_client(server.add_account("alice"))
        sent = await alice.send_message("pin me")
        server.api_errors[("POST", NOTICE_PATH)] = [status]

        with pytest.raises(exception):
            await sent.pin()
        await sent.pin()

        assert len(api_requests(server, "POST", NOTICE_PATH)) == 2


@pytest.mark.asyncio
class TestSendAnnouncement:
    async def test_sends_the_content_as_a_new_announcement_with_account_token(
        self, server, client
    ):
        alice = await client.get_user_client(server.add_account("alice"))

        assert await alice.send_announcement("read the rules") is None

        [request] = api_requests(server, "POST", NOTICE_PATH)
        assert request["token"] == "token-alice"
        assert request["body"]["message"] == "read the rules"
        # A new message, not the announcement of a message that was sent before.
        assert request["body"].get("messageId") is None
        assert api_requests(server, "POST", SEND_PATH) == []

    async def test_accounts_announce_with_their_own_token_concurrently(
        self, server, client
    ):
        alice = await client.get_user_client(server.add_account("alice"))
        bob = await client.get_user_client(server.add_account("bob"))

        await asyncio.gather(
            *(
                account.send_announcement(f"{name}-{index}")
                for index in range(5)
                for name, account in (("alice", alice), ("bob", bob))
            )
        )

        requests = api_requests(server, "POST", NOTICE_PATH)
        assert len(requests) == 10
        for request in requests:
            assert (
                request["token"] == f"token-{request['body']['message'].split('-')[0]}"
            )

    @pytest.mark.parametrize("status, exception", API_ERRORS)
    async def test_rejected_announcement_raises_the_matching_exception(
        self, server, client, status, exception
    ):
        alice = await client.get_user_client(server.add_account("alice"))
        server.api_errors[("POST", NOTICE_PATH)] = [status]

        with pytest.raises(exception):
            await alice.send_announcement("rejected")
        await alice.send_announcement("accepted")

        assert len(api_requests(server, "POST", NOTICE_PATH)) == 2


@pytest.mark.asyncio
class TestRestrictChannel:
    @staticmethod
    def restricted(page) -> list[str]:
        return [user.channel_id for user in page.data]

    async def test_add_posts_the_target_and_restricts_it_for_that_account_only(
        self, server, client
    ):
        alice = await client.get_user_client(server.add_account("alice"))
        bob = await client.get_user_client(server.add_account("bob"))

        assert await alice.add_restrict_channel("troll-1") is None

        [request] = api_requests(server, "POST", RESTRICTION_PATH)
        assert request["token"] == "token-alice"
        assert request["body"] == {"targetChannelId": "troll-1"}
        assert self.restricted(await alice.get_restriction()) == ["troll-1"]
        assert self.restricted(await bob.get_restriction()) == []

    async def test_remove_sends_a_delete_with_the_target_in_the_body(
        self, server, client
    ):
        alice = await client.get_user_client(server.add_account("alice"))
        bob = await client.get_user_client(server.add_account("bob"))
        server.restricted_channels["alice"] = ["troll-1", "troll-2"]
        server.restricted_channels["bob"] = ["troll-1"]

        assert await alice.remove_restrict_channel("troll-1") is None

        [request] = api_requests(server, "DELETE", RESTRICTION_PATH)
        assert request["token"] == "token-alice"
        assert request["body"] == {"targetChannelId": "troll-1"}
        assert self.restricted(await alice.get_restriction()) == ["troll-2"]
        # bob restricted the same channel on its own, which alice did not change.
        assert self.restricted(await bob.get_restriction()) == ["troll-1"]

    async def test_accounts_restrict_concurrently_with_their_own_token(
        self, server, client
    ):
        alice = await client.get_user_client(server.add_account("alice"))
        bob = await client.get_user_client(server.add_account("bob"))

        await asyncio.gather(
            *(
                account.add_restrict_channel(f"{name}-troll-{index}")
                for index in range(5)
                for name, account in (("alice", alice), ("bob", bob))
            )
        )

        for name in ("alice", "bob"):
            assert server.restricted_channels[name] == [
                f"{name}-troll-{index}" for index in range(5)
            ]

    @pytest.mark.parametrize("status, exception", API_ERRORS)
    async def test_rejected_add_raises_and_restricts_nothing(
        self, server, client, status, exception
    ):
        alice = await client.get_user_client(server.add_account("alice"))
        server.api_errors[("POST", RESTRICTION_PATH)] = [status]

        with pytest.raises(exception):
            await alice.add_restrict_channel("troll-1")

        assert server.restricted_channels.get("alice", []) == []

    @pytest.mark.parametrize("status, exception", API_ERRORS)
    async def test_rejected_remove_raises_and_keeps_the_restriction(
        self, server, client, status, exception
    ):
        alice = await client.get_user_client(server.add_account("alice"))
        server.restricted_channels["alice"] = ["troll-1"]
        server.api_errors[("DELETE", RESTRICTION_PATH)] = [status]

        with pytest.raises(exception):
            await alice.remove_restrict_channel("troll-1")

        assert server.restricted_channels["alice"] == ["troll-1"]
        await alice.remove_restrict_channel("troll-1")
        assert server.restricted_channels["alice"] == []


@pytest.mark.asyncio
class TestTemporaryRestrict:
    async def test_add_posts_the_target_and_the_chat_channel(self, server, client):
        alice = await client.get_user_client(server.add_account("alice"))

        assert await alice.add_temporary_restrict("troll-1", "live-77") is None

        [request] = api_requests(server, "POST", TEMPORARY_RESTRICTION_PATH)
        assert request["token"] == "token-alice"
        assert request["body"] == {
            "targetChannelId": "troll-1",
            "chatChannelId": "live-77",
        }
        assert api_requests(server, "DELETE", TEMPORARY_RESTRICTION_PATH) == []

    async def test_remove_sends_a_delete_with_the_target_and_the_chat_channel(
        self, server, client
    ):
        alice = await client.get_user_client(server.add_account("alice"))

        assert await alice.remove_temporary_restrict("troll-1", "live-77") is None

        [request] = api_requests(server, "DELETE", TEMPORARY_RESTRICTION_PATH)
        assert request["token"] == "token-alice"
        assert request["body"] == {
            "targetChannelId": "troll-1",
            "chatChannelId": "live-77",
        }
        assert api_requests(server, "POST", TEMPORARY_RESTRICTION_PATH) == []

    async def test_accounts_restrict_concurrently_with_their_own_token(
        self, server, client
    ):
        alice = await client.get_user_client(server.add_account("alice"))
        bob = await client.get_user_client(server.add_account("bob"))

        await asyncio.gather(
            alice.add_temporary_restrict("troll-a", "live-a"),
            bob.add_temporary_restrict("troll-b", "live-b"),
            alice.remove_temporary_restrict("troll-a2", "live-a"),
            bob.remove_temporary_restrict("troll-b2", "live-b"),
        )

        requests = {
            (r["method"], r["token"]): r["body"]
            for r in server.requests_to(TEMPORARY_RESTRICTION_PATH)
        }
        assert requests == {
            ("POST", "token-alice"): {
                "targetChannelId": "troll-a",
                "chatChannelId": "live-a",
            },
            ("POST", "token-bob"): {
                "targetChannelId": "troll-b",
                "chatChannelId": "live-b",
            },
            ("DELETE", "token-alice"): {
                "targetChannelId": "troll-a2",
                "chatChannelId": "live-a",
            },
            ("DELETE", "token-bob"): {
                "targetChannelId": "troll-b2",
                "chatChannelId": "live-b",
            },
        }

    @pytest.mark.parametrize("method", ["add", "remove"])
    @pytest.mark.parametrize("status, exception", API_ERRORS)
    async def test_rejected_request_raises_the_matching_exception(
        self, server, client, method, status, exception
    ):
        alice = await client.get_user_client(server.add_account("alice"))
        http_method = "POST" if method == "add" else "DELETE"
        call = getattr(alice, f"{method}_temporary_restrict")
        server.api_errors[(http_method, TEMPORARY_RESTRICTION_PATH)] = [status]

        with pytest.raises(exception):
            await call("troll-1", "live-77")
        await call("troll-1", "live-77")

        assert len(api_requests(server, http_method, TEMPORARY_RESTRICTION_PATH)) == 2


@pytest.mark.asyncio
class TestBlindMessage:
    MOMENT = datetime.datetime(2025, 3, 4, 5, 6, 7, tzinfo=datetime.timezone.utc)

    async def test_sends_the_ids_and_a_time_derived_from_the_datetime(
        self, server, client
    ):
        alice = await client.get_user_client(server.add_account("alice"))

        assert await alice.blind_message("live-77", "troll-1", self.MOMENT) is None

        [request] = api_requests(server, "POST", BLIND_PATH)
        assert request["token"] == "token-alice"
        assert request["body"] == {
            "chatChannelId": "live-77",
            "senderChannelId": "troll-1",
            "messageTime": DerivedFrom(self.MOMENT),
        }

    async def test_naive_datetime_is_taken_in_local_time_like_datetime_does(
        self, server, client
    ):
        alice = await client.get_user_client(server.add_account("alice"))
        naive = datetime.datetime(2025, 3, 4, 5, 6, 7)

        await alice.blind_message("live-77", "troll-1", naive)

        [request] = api_requests(server, "POST", BLIND_PATH)
        assert request["body"]["messageTime"] == DerivedFrom(naive)

    async def test_the_time_of_each_call_is_its_own(self, server, client):
        alice = await client.get_user_client(server.add_account("alice"))
        later = self.MOMENT + datetime.timedelta(seconds=90)

        await alice.blind_message("live-77", "troll-1", later)
        await alice.blind_message("live-77", "troll-1", self.MOMENT)

        later_request, earlier_request = api_requests(server, "POST", BLIND_PATH)
        assert later_request["body"]["messageTime"] == DerivedFrom(later)
        assert earlier_request["body"]["messageTime"] == DerivedFrom(self.MOMENT)
        # Whatever the unit is, 90 seconds later is a larger number.
        assert (
            later_request["body"]["messageTime"]
            > earlier_request["body"]["messageTime"]
        )

    async def test_accounts_blind_concurrently_with_their_own_token(
        self, server, client
    ):
        alice = await client.get_user_client(server.add_account("alice"))
        bob = await client.get_user_client(server.add_account("bob"))

        await asyncio.gather(
            alice.blind_message("live-a", "troll-a", self.MOMENT),
            bob.blind_message("live-b", "troll-b", self.MOMENT),
        )

        by_token = {
            r["token"]: r["body"] for r in api_requests(server, "POST", BLIND_PATH)
        }
        assert by_token["token-alice"]["chatChannelId"] == "live-a"
        assert by_token["token-alice"]["senderChannelId"] == "troll-a"
        assert by_token["token-bob"]["chatChannelId"] == "live-b"
        assert by_token["token-bob"]["senderChannelId"] == "troll-b"
        assert len(by_token) == 2

    @pytest.mark.parametrize("status, exception", API_ERRORS)
    async def test_rejected_request_raises_the_matching_exception(
        self, server, client, status, exception
    ):
        alice = await client.get_user_client(server.add_account("alice"))
        server.api_errors[("POST", BLIND_PATH)] = [status]

        with pytest.raises(exception):
            await alice.blind_message("live-77", "troll-1", self.MOMENT)
        await alice.blind_message("live-77", "troll-1", self.MOMENT)

        assert len(api_requests(server, "POST", BLIND_PATH)) == 2


# What an expired token does to the methods of a `UserClient`: (name, HTTP method, route,
# how to call it).
USER_CLIENT_CALLS = [
    ("send_message", "POST", SEND_PATH, lambda c: c.send_message("hello")),
    ("send_announcement", "POST", NOTICE_PATH, lambda c: c.send_announcement("hello")),
    (
        "set_live_setting",
        "PATCH",
        LIVE_SETTING_PATH,
        lambda c: c.set_live_setting(title="on air"),
    ),
    (
        "add_restrict_channel",
        "POST",
        RESTRICTION_PATH,
        lambda c: c.add_restrict_channel("troll-1"),
    ),
    (
        "remove_restrict_channel",
        "DELETE",
        RESTRICTION_PATH,
        lambda c: c.remove_restrict_channel("troll-1"),
    ),
    ("get_restriction", "GET", RESTRICTION_PATH, lambda c: c.get_restriction()),
    (
        "add_temporary_restrict",
        "POST",
        TEMPORARY_RESTRICTION_PATH,
        lambda c: c.add_temporary_restrict("troll-1", "live-77"),
    ),
    (
        "remove_temporary_restrict",
        "DELETE",
        TEMPORARY_RESTRICTION_PATH,
        lambda c: c.remove_temporary_restrict("troll-1", "live-77"),
    ),
    (
        "blind_message",
        "POST",
        BLIND_PATH,
        lambda c: c.blind_message("live-77", "troll-1", datetime.datetime(2025, 1, 1)),
    ),
    ("get_followers", "GET", FOLLOWERS_PATH, lambda c: c.get_followers()),
    ("get_subscribers", "GET", SUBSCRIBERS_PATH, lambda c: c.get_subscribers()),
]
USER_CLIENT_CALL_PARAMS = [
    pytest.param(*row[1:], id=row[0]) for row in USER_CLIENT_CALLS
]


@pytest.mark.asyncio
class TestRefreshBeforeRequest:
    """An access token that is a day old is refreshed before a method uses it."""

    @pytest.mark.parametrize("http_method, path, call", USER_CLIENT_CALL_PARAMS)
    async def test_expired_token_is_refreshed_before_the_request(
        self, server, client, http_method, path, call
    ):
        alice = await client.get_user_client(server.add_account("alice"))
        bob = await client.get_user_client(server.add_account("bob"))
        alice._token_generated_at = datetime.datetime.now() - datetime.timedelta(days=2)

        await call(alice)
        await call(alice)

        refreshed = alice.access_token.access_token
        assert refreshed.startswith("token-alice-refreshed-")
        # Refreshed once, then used for both calls. The other account is left alone.
        assert len(api_requests(server, "POST", TOKEN_PATH)) == 1
        assert [r["token"] for r in api_requests(server, http_method, path)] == [
            refreshed,
            refreshed,
        ]
        assert bob.access_token.access_token == "token-bob"

    @pytest.mark.parametrize("http_method, path, call", USER_CLIENT_CALL_PARAMS)
    async def test_token_that_is_not_expired_is_not_refreshed(
        self, server, client, http_method, path, call
    ):
        alice = await client.get_user_client(server.add_account("alice"))

        await call(alice)

        assert api_requests(server, "POST", TOKEN_PATH) == []
        assert [r["token"] for r in api_requests(server, http_method, path)] == [
            "token-alice"
        ]

    @pytest.mark.parametrize("http_method, path, call", USER_CLIENT_CALL_PARAMS)
    async def test_failed_refresh_raises_and_sends_nothing_with_the_old_token(
        self, server, client, http_method, path, call
    ):
        alice = await client.get_user_client(server.add_account("alice"))
        alice._token_generated_at = datetime.datetime.now() - datetime.timedelta(days=2)
        server.accounts["token-alice"].refresh_token = "refresh-rotated-elsewhere"

        with pytest.raises(UnauthorizedException):
            await call(alice)

        assert api_requests(server, http_method, path) == []
        assert alice.access_token.access_token == "token-alice"


# ---------------------------------------------------------------------------------------
# Paging
# ---------------------------------------------------------------------------------------


class PagedByNumber:
    """Tests shared by the methods that list followers / subscribers by page number.

    Every account only sees its own listing, so a page of another account's entries
    means that the token of the wrong account was sent."""

    path: str
    # What the first request asks for when the method is called without arguments.
    default_query: dict

    @staticmethod
    def fetch(account, **kwargs):
        raise NotImplementedError

    @staticmethod
    def listing(server) -> dict[str, list[str]]:
        raise NotImplementedError

    def fill(self, server, name: str, count: int = 5) -> list[str]:
        entries = [f"{name}-{index}" for index in range(count)]
        self.listing(server)[name] = entries
        return entries

    @staticmethod
    def ids(page) -> list[str]:
        return [item.user_id for item in page.data]

    def requests(self, server) -> list[dict]:
        return api_requests(server, "GET", self.path)

    async def test_first_page_asks_for_the_page_and_size_with_account_token(
        self, server, client
    ):
        alice = await client.get_user_client(server.add_account("alice"))
        entries = self.fill(server, "alice")

        page = await self.fetch(alice, page=1, size=2)

        [request] = self.requests(server)
        assert request["token"] == "token-alice"
        assert request["query"]["page"] == "1"
        assert request["query"]["size"] == "2"
        assert self.ids(page) == entries[2:4]

    async def test_without_arguments_the_first_page_of_thirty_is_asked_for(
        self, server, client
    ):
        alice = await client.get_user_client(server.add_account("alice"))
        entries = self.fill(server, "alice", count=40)

        page = await self.fetch(alice)

        [request] = self.requests(server)
        assert request["query"] == self.default_query
        assert self.ids(page) == entries[:30]

    async def test_next_and_previous_request_the_neighbouring_pages(
        self, server, client
    ):
        alice = await client.get_user_client(server.add_account("alice"))
        entries = self.fill(server, "alice")

        first = await self.fetch(alice, size=2)
        second = await first.next()
        third = await second.next()
        back_to_second = await third.previous()
        back_to_first = await back_to_second.previous()

        assert self.ids(first) == self.ids(back_to_first) == entries[:2]
        assert self.ids(second) == self.ids(back_to_second) == entries[2:4]
        assert self.ids(third) == entries[4:]
        requests = self.requests(server)
        assert [(r["query"]["page"], r["query"]["size"]) for r in requests] == [
            ("0", "2"),
            ("1", "2"),
            ("2", "2"),
            ("1", "2"),
            ("0", "2"),
        ]
        assert {r["token"] for r in requests} == {"token-alice"}

    async def test_a_page_in_the_middle_goes_both_ways_and_remembers_nothing_else(
        self, server, client
    ):
        alice = await client.get_user_client(server.add_account("alice"))
        entries = self.fill(server, "alice")
        middle = await self.fetch(alice, page=1, size=2)

        before = await middle.previous()
        after = await middle.next()

        assert self.ids(before) == entries[:2]
        assert self.ids(after) == entries[4:]
        assert [r["query"]["page"] for r in self.requests(server)] == ["1", "0", "2"]

    @pytest.mark.parametrize(
        "count, size, pages", [(5, 2, 3), (4, 2, 2), (3, 30, 1), (30, 30, 1)]
    )
    async def test_next_after_the_last_page_raises_type_error_without_a_request(
        self, server, client, count, size, pages
    ):
        alice = await client.get_user_client(server.add_account("alice"))
        entries = self.fill(server, "alice", count=count)
        page = await self.fetch(alice, size=size)
        for _ in range(pages - 1):
            page = await page.next()
        assert self.ids(page) == entries[(pages - 1) * size :]
        requests_before = len(self.requests(server))

        with pytest.raises(TypeError):
            await page.next()

        assert len(self.requests(server)) == requests_before

    async def test_previous_before_the_first_page_raises_type_error_without_a_request(
        self, server, client
    ):
        alice = await client.get_user_client(server.add_account("alice"))
        self.fill(server, "alice")
        first = await self.fetch(alice, size=2)

        with pytest.raises(TypeError):
            await first.previous()

        assert len(self.requests(server)) == 1

    async def test_listing_without_entries_has_no_neighbouring_page(
        self, server, client
    ):
        alice = await client.get_user_client(server.add_account("alice"))

        page = await self.fetch(alice)

        assert page.data == []
        with pytest.raises(TypeError):
            await page.next()
        with pytest.raises(TypeError):
            await page.previous()
        assert len(self.requests(server)) == 1

    async def test_accounts_do_not_mix_tokens_while_paging(self, server, client):
        alice = await client.get_user_client(server.add_account("alice"))
        bob = await client.get_user_client(server.add_account("bob"))
        alice_entries = self.fill(server, "alice", count=6)
        bob_entries = self.fill(server, "bob", count=6)
        alice_first, bob_first = await asyncio.gather(
            self.fetch(alice, size=2), self.fetch(bob, size=2)
        )

        alice_second, bob_second = await asyncio.gather(
            alice_first.next(), bob_first.next()
        )
        alice_third = await alice_second.next()
        bob_back = await bob_second.previous()
        alice_back, bob_third = await asyncio.gather(
            alice_third.previous(), bob_second.next()
        )

        assert self.ids(alice_second) == self.ids(alice_back) == alice_entries[2:4]
        assert self.ids(alice_third) == alice_entries[4:]
        assert self.ids(bob_second) == bob_entries[2:4]
        assert self.ids(bob_back) == bob_entries[:2]
        assert self.ids(bob_third) == bob_entries[4:]
        tokens = [r["token"] for r in self.requests(server)]
        assert sorted(tokens) == ["token-alice"] * 4 + ["token-bob"] * 4

    @pytest.mark.parametrize("status, exception", API_ERRORS)
    async def test_rejected_first_page_raises_the_matching_exception(
        self, server, client, status, exception
    ):
        alice = await client.get_user_client(server.add_account("alice"))
        entries = self.fill(server, "alice")
        server.api_errors[("GET", self.path)] = [status]

        with pytest.raises(exception):
            await self.fetch(alice, size=2)

        assert self.ids(await self.fetch(alice, size=2)) == entries[:2]

    @pytest.mark.parametrize("status, exception", API_ERRORS)
    async def test_rejected_later_page_raises_and_can_be_asked_for_again(
        self, server, client, status, exception
    ):
        alice = await client.get_user_client(server.add_account("alice"))
        entries = self.fill(server, "alice")
        first = await self.fetch(alice, size=2)
        server.api_errors[("GET", self.path)] = [status]

        with pytest.raises(exception):
            await first.next()
        second = await first.next()
        server.api_errors[("GET", self.path)] = [status]
        with pytest.raises(exception):
            await second.previous()
        again = await second.previous()

        assert self.ids(second) == entries[2:4]
        assert self.ids(again) == entries[:2]
        retried = self.requests(server)[-1]
        assert (retried["query"]["page"], retried["query"]["size"]) == ("0", "2")
        assert retried["token"] == "token-alice"

    async def test_revoked_token_raises_unauthorized_on_the_next_page(
        self, server, client
    ):
        alice = await client.get_user_client(server.add_account("alice"))
        self.fill(server, "alice")
        first = await self.fetch(alice, size=2)
        del server.accounts["token-alice"]

        with pytest.raises(UnauthorizedException):
            await first.next()


@pytest.mark.asyncio
class TestGetFollowers(PagedByNumber):
    path = FOLLOWERS_PATH
    default_query = {"page": "0", "size": "30"}

    @staticmethod
    def fetch(account, **kwargs):
        return account.get_followers(**kwargs)

    @staticmethod
    def listing(server):
        return server.followers

    async def test_followers_are_not_asked_to_be_sorted(self, server, client):
        alice = await client.get_user_client(server.add_account("alice"))
        self.fill(server, "alice")

        first = await self.fetch(alice, size=2)
        await first.next()

        assert all("sort" not in r["query"] for r in self.requests(server))


@pytest.mark.asyncio
class TestGetSubscribers(PagedByNumber):
    path = SUBSCRIBERS_PATH
    default_query = {"page": "0", "size": "30", "sort": "RECENT"}

    @staticmethod
    def fetch(account, **kwargs):
        return account.get_subscribers(**kwargs)

    @staticmethod
    def listing(server):
        return server.subscribers

    @pytest.mark.parametrize("sort", ["RECENT", "LONGER"])
    async def test_sort_is_asked_for_on_every_page(self, server, client, sort):
        alice = await client.get_user_client(server.add_account("alice"))
        entries = self.fill(server, "alice")
        # The mock lists the subscribers of "LONGER" in the reverse order.
        expected = entries if sort == "RECENT" else entries[::-1]

        first = await self.fetch(alice, size=2, sort=sort)
        second = await first.next()
        third = await second.next()
        back = await third.previous()

        assert self.ids(first) == expected[:2]
        assert self.ids(second) == self.ids(back) == expected[2:4]
        assert self.ids(third) == expected[4:]
        assert [r["query"]["sort"] for r in self.requests(server)] == [sort] * 4

    async def test_each_call_keeps_the_sort_it_was_made_with(self, server, client):
        alice = await client.get_user_client(server.add_account("alice"))
        bob = await client.get_user_client(server.add_account("bob"))
        alice_entries = self.fill(server, "alice", count=4)
        bob_entries = self.fill(server, "bob", count=4)
        alice_first, bob_first = await asyncio.gather(
            self.fetch(alice, size=2, sort="LONGER"),
            self.fetch(bob, size=2, sort="RECENT"),
        )

        alice_second, bob_second = await asyncio.gather(
            alice_first.next(), bob_first.next()
        )

        assert self.ids(alice_second) == alice_entries[::-1][2:]
        assert self.ids(bob_second) == bob_entries[2:]
        sorts = {r["token"]: r["query"]["sort"] for r in self.requests(server)}
        assert sorts == {"token-alice": "LONGER", "token-bob": "RECENT"}


@pytest.mark.asyncio
class TestGetLive:
    """`Client.get_live`: cursor paging with the client credentials."""

    @staticmethod
    def titles(page) -> list[str]:
        return [live.live_title for live in page.data]

    @staticmethod
    def fill(server, count: int = 5) -> list[str]:
        server.lives = [f"live-{index}" for index in range(count)]
        return server.lives

    @staticmethod
    def requests(server) -> list[dict]:
        return api_requests(server, "GET", LIVES_PATH)

    async def test_first_page_asks_for_size_without_any_user_token(
        self, server, client
    ):
        await client.get_user_client(server.add_account("alice"))
        lives = self.fill(server)

        page = await client.get_live(size=2)

        [request] = self.requests(server)
        assert request["query"] == {"size": "2"}
        assert request["token"] == ""
        assert self.titles(page) == lives[:2]

    async def test_without_arguments_twenty_lives_are_asked_for(self, server, client):
        lives = self.fill(server, count=25)

        page = await client.get_live()

        [request] = self.requests(server)
        assert request["query"] == {"size": "20"}
        assert self.titles(page) == lives[:20]

    async def test_next_asks_for_the_cursor_of_the_page_with_the_same_size(
        self, server, client
    ):
        lives = self.fill(server)
        first = await client.get_live(size=2)

        second = await first.next()
        third = await second.next()

        assert self.titles(second) == lives[2:4]
        assert self.titles(third) == lives[4:]
        assert [r["query"] for r in self.requests(server)] == [
            {"size": "2"},
            {"size": "2", "next": "2"},
            {"size": "2", "next": "4"},
        ]
        assert {r["token"] for r in self.requests(server)} == {""}

    async def test_next_is_relative_to_the_page_it_is_called_on(self, server, client):
        lives = self.fill(server, count=6)
        first = await client.get_live(size=2)
        second = await first.next()

        again = await first.next()
        third = await second.next()

        assert self.titles(again) == self.titles(second) == lives[2:4]
        assert self.titles(third) == lives[4:]
        assert [r["query"].get("next") for r in self.requests(server)] == [
            None,
            "2",
            "2",
            "4",
        ]

    async def test_pages_of_listings_keep_their_own_size(self, server, client):
        lives = self.fill(server, count=12)
        wide = await client.get_live(size=3)
        narrow = await client.get_live(size=2)

        narrow_second = await narrow.next()
        wide_second = await wide.next()
        narrow_third = await narrow_second.next()
        wide_third = await wide_second.next()

        assert self.titles(narrow_second) == lives[2:4]
        assert self.titles(narrow_third) == lives[4:6]
        assert self.titles(wide_second) == lives[3:6]
        assert self.titles(wide_third) == lives[6:9]

    async def test_wrong_client_credentials_raise_unauthorized(self, server, client):
        self.fill(server)
        client.http.client_secret = "not-the-secret"

        with pytest.raises(UnauthorizedException):
            await client.get_live(size=2)

    async def test_credentials_that_stop_working_raise_on_the_next_page(
        self, server, client
    ):
        lives = self.fill(server)
        first = await client.get_live(size=2)
        client.http.client_secret = "rotated"

        with pytest.raises(UnauthorizedException):
            await first.next()

        client.http.client_secret = "client-secret"
        assert self.titles(await first.next()) == lives[2:4]

    @pytest.mark.parametrize("status, exception", API_ERRORS)
    async def test_rejected_first_page_raises_the_matching_exception(
        self, server, client, status, exception
    ):
        lives = self.fill(server)
        server.api_errors[("GET", LIVES_PATH)] = [status]

        with pytest.raises(exception):
            await client.get_live(size=2)

        assert self.titles(await client.get_live(size=2)) == lives[:2]

    @pytest.mark.parametrize("status, exception", API_ERRORS)
    async def test_rejected_later_page_raises_and_can_be_asked_for_again(
        self, server, client, status, exception
    ):
        lives = self.fill(server)
        first = await client.get_live(size=2)
        server.api_errors[("GET", LIVES_PATH)] = [status]

        with pytest.raises(exception):
            await first.next()
        second = await first.next()

        assert self.titles(second) == lives[2:4]
        assert self.requests(server)[-1]["query"] == {"size": "2", "next": "2"}


@pytest.mark.asyncio
class TestGetChannel:
    async def test_ids_are_joined_with_commas_in_the_given_order(self, server, client):
        channels = await client.get_channel(["c-3", "c-1", "c-2"])

        [request] = api_requests(server, "GET", CHANNELS_PATH)
        assert request["query"] == {"channelIds": "c-3,c-1,c-2"}
        assert request["token"] == ""
        assert [channel.id for channel in channels] == ["c-3", "c-1", "c-2"]

    async def test_a_single_id_is_sent_as_it_is(self, server, client):
        channels = await client.get_channel(["c-1"])

        [request] = api_requests(server, "GET", CHANNELS_PATH)
        assert request["query"] == {"channelIds": "c-1"}
        assert [channel.id for channel in channels] == ["c-1"]

    async def test_wrong_client_credentials_raise_unauthorized(self, server, client):
        client.http.client_secret = "not-the-secret"

        with pytest.raises(UnauthorizedException):
            await client.get_channel(["c-1"])

    @pytest.mark.parametrize("status, exception", API_ERRORS)
    async def test_rejected_request_raises_the_matching_exception(
        self, server, client, status, exception
    ):
        server.api_errors[("GET", CHANNELS_PATH)] = [status]

        with pytest.raises(exception):
            await client.get_channel(["c-1", "c-2"])

        assert [c.id for c in await client.get_channel(["c-1", "c-2"])] == [
            "c-1",
            "c-2",
        ]


@pytest.mark.asyncio
class TestGetCategory:
    @staticmethod
    def categories(count: int) -> list[dict]:
        return [
            {
                "categoryType": "GAME",
                "categoryId": f"game-{index}",
                "categoryValue": f"Game {index}",
                "posterImageUrl": None,
            }
            for index in range(count)
        ]

    async def test_asks_for_the_query_and_twenty_categories_by_default(
        self, server, client
    ):
        server.categories = self.categories(25)

        found = await client.get_category("Game")

        [request] = api_requests(server, "GET", CATEGORIES_PATH)
        assert request["query"] == {"query": "Game", "size": "20"}
        assert request["token"] == ""
        assert [c.id for c in found] == [f"game-{index}" for index in range(20)]

    async def test_asks_for_the_given_size(self, server, client):
        server.categories = self.categories(25)

        found = await client.get_category("Game 1", size=3)

        [request] = api_requests(server, "GET", CATEGORIES_PATH)
        assert request["query"] == {"query": "Game 1", "size": "3"}
        assert [c.id for c in found] == ["game-1", "game-10", "game-11"]

    async def test_wrong_client_credentials_raise_unauthorized(self, server, client):
        client.http.client_secret = "not-the-secret"

        with pytest.raises(UnauthorizedException):
            await client.get_category("Game")

    @pytest.mark.parametrize("status, exception", API_ERRORS)
    async def test_rejected_request_raises_the_matching_exception(
        self, server, client, status, exception
    ):
        server.categories = self.categories(2)
        server.api_errors[("GET", CATEGORIES_PATH)] = [status]

        with pytest.raises(exception):
            await client.get_category("Game")

        assert len(await client.get_category("Game")) == 2


@pytest.mark.asyncio
class TestSearchResultNext:
    """`SearchResult.next()` behind `get_live` and `get_restriction`."""

    @staticmethod
    async def first_page(source, server, client, size=2):
        """The first page of a listing of three entries, and what the listing holds."""
        if source == "live":
            server.lives = ["live-0", "live-1", "live-2"]
            return await client.get_live(size=size), server.lives
        alice = await client.get_user_client(server.add_account("alice"))
        server.restricted_channels["alice"] = ["troll-0", "troll-1", "troll-2"]
        return (
            await alice.get_restriction(size=size),
            server.restricted_channels["alice"],
        )

    @staticmethod
    def requests(source, server) -> list[dict]:
        return api_requests(
            server, "GET", LIVES_PATH if source == "live" else RESTRICTION_PATH
        )

    @staticmethod
    def names(page) -> list[str]:
        return [
            item.live_title if hasattr(item, "live_title") else item.channel_id
            for item in page.data
        ]

    @pytest.mark.parametrize("source", ["live", "restriction"])
    async def test_the_cursor_of_the_second_page_leads_to_the_last_entry(
        self, server, client, source
    ):
        first, everything = await self.first_page(source, server, client)

        last = await first.next()

        assert self.names(first) == everything[:2]
        assert self.names(last) == everything[2:]

    @pytest.mark.parametrize("source", ["live", "restriction"])
    async def test_next_on_the_last_page_raises_type_error_without_a_request(
        self, server, client, source
    ):
        first, _ = await self.first_page(source, server, client)
        last = await first.next()
        requests_before = len(self.requests(source, server))

        with pytest.raises(
            TypeError, match=r"^This is the last page of search result\.$"
        ):
            await last.next()

        assert len(self.requests(source, server)) == requests_before

    @pytest.mark.parametrize("source", ["live", "restriction"])
    async def test_next_on_a_result_of_a_single_page_raises_type_error(
        self, server, client, source
    ):
        only, everything = await self.first_page(source, server, client, size=30)
        assert self.names(only) == everything

        with pytest.raises(
            TypeError, match=r"^This is the last page of search result\.$"
        ):
            await only.next()

        assert len(self.requests(source, server)) == 1

    @pytest.mark.parametrize("source", ["live", "restriction"])
    async def test_paging_loop_ends_with_type_error_and_asks_for_each_page_once(
        self, server, client, source
    ):
        first, everything = await self.first_page(source, server, client)
        pages = [first]

        with pytest.raises(TypeError):
            # `while True: page = await page.next()` is meant to end by itself. The
            # bound only keeps a paging that restarts from the first page from hanging.
            for _ in range(10):
                pages.append(await pages[-1].next())
            pytest.fail("The paging never reached the last page.")

        assert [name for page in pages for name in self.names(page)] == everything
        assert [r["query"] for r in self.requests(source, server)] == [
            {"size": "2"},
            {"size": "2", "next": "2"},
        ]

    async def test_result_that_does_not_come_from_a_paging_method_raises_runtime_error(
        self, server, client
    ):
        server.lives = ["live-0", "live-1", "live-2"]
        # The low-level call returns the page without telling it how to ask for the next.
        result = await client.http.get_lives(size=2)

        with pytest.raises(RuntimeError):
            await result.content.next()

        assert len(api_requests(server, "GET", LIVES_PATH)) == 1
