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
import functools
from typing import Optional, Literal, TypeVar, Generic, TYPE_CHECKING, Any
from pydantic import AliasChoices, Field, Json, ConfigDict, PrivateAttr

from .donation import (
    BaseDonation,
    ChatDonation,
    VideoDonation,
    MissionDonation,
    MissionParticipationDonation,
)
from .enums import ChatType
from .profile import Profile
from ..base_model import ChzzkModel

if TYPE_CHECKING:
    from .chat_client import ChatClient

E = TypeVar("E", bound="ExtraBase | BaseDonation")


class ExtraBase(ChzzkModel):
    pass


class Extra(ExtraBase):
    chat_type: str
    emojis: Optional[Any] = None
    os_type: Literal["PC", "AOS", "IOS"]
    streaming_channel_id: str


class Message(ChzzkModel, Generic[E]):
    service_id: str = Field(validation_alias=AliasChoices("serviceId", "svcid"))
    channel_id: str = Field(validation_alias=AliasChoices("channelId", "cid"))
    user_id: str = Field(validation_alias=AliasChoices("uid", "userId"))

    profile: Optional[Json[Profile]]
    content: str = Field(validation_alias=AliasChoices("msg", "content"))
    type: ChatType = Field(
        validation_alias=AliasChoices("msgTypeCode", "messageTypeCode")
    )
    extras: Optional[Json[E]]

    created_time: datetime.datetime = Field(
        validation_alias=AliasChoices("ctime", "createTime")
    )
    updated_time: Optional[datetime.datetime] = Field(
        default=None, validation_alias=AliasChoices("utime", "updateTime")
    )
    time: datetime.datetime = Field(
        validation_alias=AliasChoices("msgTime", "messageTime")
    )

    _client: Optional[ChatClient] = PrivateAttr(default=None)

    @staticmethod
    def _based_client(func):
        @functools.wraps(func)
        async def wrapper(self: MessageDetail, *args, **kwargs):
            if self._client is None:
                raise RuntimeError(
                    f"This {self.__class__.__name__} is intended to store message information only."
                )
            return await func(self, *args, **kwargs)

        return wrapper

    @classmethod
    def model_validate_with_client(
        cls: type[Message], obj: Any, client: ChatClient
    ) -> Message:
        model = super().model_validate(obj)
        model._client = client

        if model.profile is not None:
            model.profile._set_manage_client(client.manage_self)
        return model

    @property
    def is_me(self) -> bool:
        """Verify that this message is from a user signed in to the client."""
        if self._client is None:
            raise RuntimeError(
                f"This {self.__class__.__name__} is intended to store message information only."
            )
        return self._client.user_id == self.user_id

    @_based_client
    async def send(self, message: str):
        """Send message to broadcaster."""
        await self._client.send_chat(message)


class MessageDetail(Message[E], Generic[E]):
    member_count: int = Field(validation_alias=AliasChoices("mbrCnt", "memberCount"))
    message_status: Optional[str] = Field(
        validation_alias=AliasChoices("msgStatusType", "messageStatusType")
    )

    # message_tid: ???
    # session: bool

    @property
    def is_blind(self) -> bool:
        return self.message_status == "BLIND"


class ChatMessage(MessageDetail[Extra]):
    @Message._based_client
    async def pin(self):
        """Pin this message."""
        await self._client.set_notice_message(self)

    @Message._based_client
    async def unpin(self):
        """Unpin this message."""
        await self._client.delete_notice_message()

    @Message._based_client
    async def blind(self):
        """Blind this message."""
        await self._client.blind_message(self)

    @Message._based_client
    async def temporary_restrict(self):
        """Temporary restrict this user."""
        await self._client.temporary_restrict(self.profile)


class NoticeExtra(Extra):
    register_profile: Profile


class NoticeMessage(Message[NoticeExtra]):
    @Message._based_client
    async def unpin(self):
        """Unpin this message."""
        await self._client.delete_notice_message()


class ChatDonationExtra(ChatDonation):
    pass


class VideoDonationExtra(VideoDonation):
    pass


class MissionDonationExtra(MissionDonation):
    pass


class DonationMessage(
    MessageDetail[
        ChatDonationExtra
        | VideoDonationExtra
        | MissionDonationExtra
        | MissionParticipationDonation
    ]
):
    pass


class SubscriptionExtra(ExtraBase):
    month: int
    tier_name: str
    nickname: Optional[str] = None
    tier_no: Optional[int] = None


class SubscriptionMessage(MessageDetail[SubscriptionExtra]):
    pass


class SystemExtraParameter(ChzzkModel):
    register_nickname: str
    target_nickname: str
    register_chat_profile: Optional[Json[Profile]] = Field(
        alias="registerChatProfileJson", default=None
    )
    target_profile: Optional[Json[Profile]] = Field(
        alias="targetChatProfileJson", default=None
    )


class SystemExtra(ExtraBase):
    description: str
    style_type: int
    visible_roles: list[str]
    params: Optional[SystemExtraParameter] = None


class SystemMessage(MessageDetail[SystemExtra]):
    pass
