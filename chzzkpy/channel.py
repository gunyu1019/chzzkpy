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

import datetime
from pydantic import Field
from typing import Optional, Literal

from .base_model import ChzzkModel


class Channel(ChzzkModel):
    id: str = Field(alias="channelId")
    name: str = Field(alias="channelName")
    image: Optional[str] = Field(alias="channelImageUrl", default=None)

    follower_count: Optional[int] = 0
    verified_mark: bool = False


class ChannelPermission(ChzzkModel):
    user_id: str = Field(alias="managerChannelId")
    user_name: str = Field(alias="managerChannelName")
    role: Literal[
        "STREAMING_CHANNEL_OWNER",
        "STREAMING_CHANNEL_MANAGER",
        "STREAMING_CHAT_MANAGER",
        "STREAMING_SETTLEMENT_MANAGER",
    ] = Field(alias="userRole")
    created_date: datetime.date


class FollowerInfo(ChzzkModel):
    user_id: str = Field(alias="channelId")
    user_name: str = Field(alias="channelName")
    created_date: datetime.date


class SubscriberInfo(ChzzkModel):
    user_id: str = Field(alias="channelId")
    user_name: str = Field(alias="channelName")
    month: int
    tier_no: int
    created_date: datetime.date
