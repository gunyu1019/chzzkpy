"""MIT License

Copyright (c) 2024-2025 gunyu1019

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

from __future__ import annotations

import datetime

from pydantic import Field, PrivateAttr, computed_field
from typing import Any, Literal, Optional, TYPE_CHECKING

from .base_model import ChzzkModel

if TYPE_CHECKING:
    from .authorization import AccessToken
    from .state import ConnectionState


class Emoji(ChzzkModel):
    id: str
    url: str = Field(alias="value")


class Profile(ChzzkModel):
    nickname: str
    badges: list[Any]
    verified_mark: bool


class Messageable(ChzzkModel):
    _access_token: Optional[AccessToken] = PrivateAttr(default=None)
    _state: Optional[ConnectionState] = PrivateAttr(default=None)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if "state" in kwargs.keys() and "access_token" in kwargs.keys():
            self._access_token = kwargs.pop("access_token")
            self._state = kwargs.pop("state")

    async def send(self, content: str) -> SentMessage:
        """Send a message to the received channel

        Parameters
        ----------
        content : str
            A content of message to send.

        Raises
        ------
        RuntimeError
            Raised when the access token is missing,
            or there is insufficient data to send message due to unusual situations.
        """
        if self._state is None or self._access_token is None:
            raise RuntimeError(
                f"This {self.__class__.__name__} is intended to store data only."
                f"Or don't have the authentication token to send the message."
            )
        response = await self._state.http.create_message(
            message=content, token=self._access_token
        )

        message_id = response.content["messageId"]
        message = SentMessage(id=message_id, content=content)
        message._access_token = self._access_token
        message._state = self._state
        return message


class Subscription(Messageable):
    """A subscription instance received form the live.
    Subscription can be received via the `on_subscription` event.
    """

    channel: str = Field(alias="channelId")
    subscriber_id: str = Field(alias="subscriberChannelId")
    subscriber_name: str = Field(alias="subscriberNickname")

    tier_no: int
    tier_name: str
    month: int


class Donation(Messageable):
    """A donation instance received form the live.
    Donations can be received via the `on_donation` event.
    """

    type: Literal["CHAT", "VIDEO"] = Field(alias="donationType")
    channel: str = Field(alias="channelId")
    donator_id: str = Field(alias="donatorChannelId")
    donator_name: str = Field(alias="donatorNickname")

    pay_amount: int
    donation_text: str


class Message(Messageable):
    """A message instance received from the live.
    Messages can be received via the `on_chat` event.
    """

    _raw_emojis: Optional[dict[str, Any]] = PrivateAttr(default=None)

    user_id: str = Field(alias="senderChannelId")

    profile: Profile
    content: str
    channel: str = Field(alias="channelId")
    chat_channel: str = Field(alias="chatChannelId")
    created_time: datetime.datetime = Field(alias="messageTime")

    def __init__(self, *args, **kwargs):
        _raw_emojis = dict()
        if "emojis" in kwargs.keys():
            _raw_emojis = kwargs.pop("emojis", dict())
        super().__init__(*args, **kwargs)
        self._raw_emojis = _raw_emojis

    @computed_field
    @property
    def emojis(self) -> list[Emoji]:
        return [Emoji(id=k, value=v) for k, v in self._raw_emojis.items()]

    def __str__(self) -> str:
        return self.content

    async def blind(self) -> None:
        """Blind the message from the channel."""
        if self._state is None or self._access_token is None:
            raise RuntimeError(
                f"This {self.__class__.__name__} is intended to store data only."
                f"Or don't have the authentication token to send the message."
            )
        await self._state.http.blind_message(
            token=self._access_token,
            chat_channel_id=self.chat_channel,
            message_time=self.created_time.timestamp(),
            sender_channel_id=self.user_id,
        )

    async def add_temporal_restrict(self) -> None:
        """Temporarily restrict user of the message from chatting."""
        if self._state is None or self._access_token is None:
            raise RuntimeError(
                f"This {self.__class__.__name__} is intended to store data only."
                f"Or don't have the authentication token to send the message."
            )
        await self._state.http.add_temporary_restrict_user(
            token=self._access_token,
            target_channel_id=self.user_id,
            chat_channel_id=self.chat_channel,
        )
        return None

    async def remove_temporal_restrict(self) -> None:
        """Remove temporary restriction of user of the message."""
        if self._state is None or self._access_token is None:
            raise RuntimeError(
                f"This {self.__class__.__name__} is intended to store data only."
                f"Or don't have the authentication token to send the message."
            )
        await self._state.http.remove_temporary_restrict_user(
            token=self._access_token,
            target_channel_id=self.user_id,
            chat_channel_id=self.chat_channel,
        )

    async def add_permanent_restrict(self) -> None:
        """Permanently restrict user of the message from chatting."""
        if self._state is None or self._access_token is None:
            raise RuntimeError(
                f"This {self.__class__.__name__} is intended to store data only."
                f"Or don't have the authentication token to send the message."
            )
        await self._state.http.add_restrict_user(
            token=self._access_token,
            target_channel_id=self.user_id,
        )
        return None

    async def remove_permanent_restrict(self) -> None:
        """Remove permanent restriction of user of the message."""
        if self._state is None or self._access_token is None:
            raise RuntimeError(
                f"This {self.__class__.__name__} is intended to store data only."
                f"Or don't have the authentication token to send the message."
            )
        await self._state.http.remove_restrict_user(
            token=self._access_token,
            target_channel_id=self.user_id,
        )
        return None


class SentMessage(Messageable):
    """Represents a message sent by client.send() method"""

    id: str
    content: str
    created_time: datetime.datetime = Field(default_factory=datetime.datetime.now)

    async def pin(self) -> None:
        """Pin the sent message for announcement."""
        if self._state is None or self._access_token is None:
            raise RuntimeError(
                f"This {self.__class__.__name__} is intended to store data only."
            )
        await self._state.http.create_notice(
            message_id=self.id, token=self._access_token
        )
