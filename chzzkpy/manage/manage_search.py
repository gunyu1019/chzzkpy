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

import datetime

from typing import Annotated, List, Optional, Generic, TypeVar
from pydantic import BeforeValidator, Field

from ..base_model import ChzzkModel, ManagerClientAccessable
from ..user import PartialUser
from ..video import PartialVideo

T = TypeVar("T")


class ManageResult(ChzzkModel, Generic[T]):
    page: int
    size: int
    total_count: int
    total_pages: int
    data: List[T]

    def __iter__(self):
        return self.data.__iter__()

    def __len__(self):
        return self.total_count

    def __getitem__(self, index: int):
        return self.data[index]


class FollowingInfo(ChzzkModel):
    following: bool
    notification: bool
    follow_date: Optional[datetime.datetime]


class ManageSubcriber(ChzzkModel):  # incomplete data
    user_id_hash: Optional[str]
    nickname: Optional[str]
    profile_image_url: Optional[str]
    verified_mark: bool = False

    total_month: int
    tier: str
    publish_period: int
    twitch_month: Optional[int] = None
    created_date: datetime.datetime


class ManageFollower(ChzzkModel):
    user: PartialUser
    following: FollowingInfo
    channel_following: FollowingInfo


class RestrictUser(PartialUser, ManagerClientAccessable):
    seq: int
    execute_nickname: str
    created_date: datetime.datetime
    release_date: Optional[datetime.datetime] = None
    memo: str = ""

    @property
    def restrict_days(self) -> Optional[int]:
        """Get restrict days"""
        if self.release_date is None:
            return
        return (self.release_date - self.created_date).days


class UnrestrictRequest(ChzzkModel, ManagerClientAccessable):
    request_no: int
    restrict_seq: int
    user: PartialUser = Field(alias="userResponse")
    vindication: str
    created_date: datetime.datetime

    @ManagerClientAccessable.based_manage_client
    async def approve(self):
        """Approve this unrestrict activity request."""
        await self._manage_client.remove_restrict(self.user_id_hash)

    @ManagerClientAccessable.based_manage_client
    async def reject(self, reason: str):
        """Deny this unrestrict activity request."""
        await self._manage_client._http.reject_unrestrict_request(
            channel_id=self.channel_id, request_number=self.request_no, judgment=reason
        )


class ManageVideo(PartialVideo):
    live_id: Optional[int] = None
    created_date: Annotated[
        datetime.datetime, BeforeValidator(ChzzkModel.special_date_parsing_validator)
    ]
    like_count: int
    read_count: int
    comment_count: int
    vod_status: str
    exposure: bool
    publish: bool
    publish_type: str
    manual_publishable: bool
    exposure_button: str
    live_accumulate_count: int = 0
    live_unique_view_count: int = 0
    live_open_date: Annotated[
        Optional[datetime.datetime],
        BeforeValidator(ChzzkModel.special_date_parsing_validator),
    ] = None
    deleted: bool
    # download
    # deletedBy: Type Unknown??? // Nullable
