import datetime
from typing import Optional, Literal, TypeVar, Generic

from pydantic import AliasChoices, Field, Json

from .enums import ChatType
from .profile import Profile
from ..base_model import ChzzkModel

E = TypeVar("E", bound="type")


class Extra(ChzzkModel):
    chat_type: str
    emojis: str
    os_type: Literal['PC', 'AOS', 'IOS']
    streaming_channel_id: str


class Message(ChzzkModel, Generic[E]):
    service_id: str = Field(validation_alias=AliasChoices('serviceId', 'svcid'))
    channel_id: str = Field(validation_alias=AliasChoices('channelId', 'cid'))
    user_id: str = Field(validation_alias=AliasChoices('uid', 'userId'))

    profile: Optional[Json[Profile]]
    content: str = Field(validation_alias=AliasChoices('msg', 'content'))
    type: ChatType = Field(validation_alias=AliasChoices('msgTypeCode', 'messageTypeCode'))
    extras: Optional[Json[E]]

    created_time: datetime.datetime = Field(validation_alias=AliasChoices('ctime', 'createTime'))
    updated_time: Optional[datetime.datetime] = Field(validation_alias=AliasChoices('utime', 'updateTime'))
    time: datetime.datetime = Field(validation_alias=AliasChoices('msgTime', 'messageTime'))


class MessageDetail(Message[E], Generic[E]):
    member_count: int = Field(validation_alias=AliasChoices('mbrCnt', 'memberCount'))
    message_status: Optional[str] = Field(validation_alias=AliasChoices('msgStatueType', 'messageStatusType'))

    # message_tid: ???
    # session: bool

    @property
    def is_blind(self) -> bool:
        return self.message_status == 'BLIND'


class ChatMessage(Message[Extra]):
    pass


class NoticeExtra(Extra):
    register_profile: Profile


class NoticeMessage(Message[NoticeExtra]):
    pass


class DonationExtra(Extra):
    user_id_hash: str
    nickname: str
    verified_mark: bool
    donation_amount: int
    # WIP


class DonationMessage(Message[NoticeExtra]):
    pass


class SystemExtraParameter(ChzzkModel):
    register_nickname: str
    target_nickname: str
    register_chat_profile: Profile
    target_profile: Profile


class SystemExtra(ChzzkModel):
    description: str
    style_type: int
    visible_roles: list[str]
    params: Optional[SystemExtraParameter]


class SystemMessage(ChatMessage[SystemExtra]):
    pass