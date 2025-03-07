"""MIT License

Copyright (c) 2024 gunyu1019

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

from pydantic import Field, PrivateAttr
from typing import Any, Literal, Optional, TYPE_CHECKING

from .base_model import ChzzkModel

if TYPE_CHECKING:
    from .authorization import AccessToken
    from .state import ConnectionState


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
        message = await self._state.http.create_message(
            message=content, token=self._access_token
        )
        message._state = self._state
        message._access_token = self._access_token
        return message


class Donation(Messageable):
    """A donation instance received form the live.
    Donations can be received via the `on_donation` event.
    """

    type: Literal["CHAT", "VIDEO"] = Field(alias="donationType")
    channel: str = Field(alias="channelId")
    donator_id: str = Field(alias="donatorChannelId")
    donator_name: str = Field(alias="donatorChannelId")

    pay_amount: int
    donation_text: str


class Message(Messageable):
    """A message instance received from the live.
    Messages can be received via the `on_chat` event.
    """

    user_id: str = Field(alias="senderChannelId")

    profile: Profile
    content: str
    channel: str = Field(alias="channelId")
    created_time: datetime.datetime = Field(alias="messageTime")


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
