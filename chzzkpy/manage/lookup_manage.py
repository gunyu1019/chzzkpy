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

from typing import List, Optional, Generic, TypeVar

from ..base_model import ChzzkModel
from ..user import ParticleUser

T = TypeVar("T")


class ManageResult(ChzzkModel, Generic[T]):
    page: int
    size: int
    total_count: int
    total_page: int
    data: List[T]


class FollowingInfo(ChzzkModel):
    following: bool
    notification: bool
    follow_date: datetime.datetime


class Subcriber(ChzzkModel):  # incomplete data
    user_id_hash: Optional[str]
    nickname: Optional[str]
    profile_image_url: Optional[str]
    verified_mark: bool = False

    total_month: int
    tier: str
    publish_period: int
    twitch_month: Optional[int] = None
    created_date: datetime.datetime


class Follower(ChzzkModel):
    user: ParticleUser
    following: FollowingInfo
    channel_following: FollowingInfo
