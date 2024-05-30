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
from typing import Literal, Any, Optional
from pydantic import Field, Json
from .base_model import ChzzkModel


class LivePollingStatus(ChzzkModel):
    status: str
    is_publishing: bool
    playable_status: str
    traffic_throttling: int
    call_period_millisecond: int = Field(alias="callPeriodMilliSecond")


class LiveStatus(ChzzkModel):
    live_title: str
    status: Literal["OPEN", "CLOSE"]
    concurrent_user_count: int
    accumulate_count: int
    paid_promotion: bool
    adult: bool
    chat_channel_id: str
    category_type: Optional[str]
    live_category: Optional[str]
    live_category_value: str
    live_polling_status: Json[LivePollingStatus] = Field(alias="livePollingStatusJson")
    fault_status: Any  # typing: ???
    user_adult_status: str
    chat_active: bool
    chat_available_group: str
    chat_available_condition: str
    min_follower_minute: int


class BaseLive(ChzzkModel):
    live_id: int
    live_title: str
    live_image_url: str
    accumulate_count: int
    adult: bool
    chat_channel_id: str
    category_type: Optional[str]
    concurrent_user_count: int
    default_thumbnail_image_url: Optional[str]
    live_category: str
    live_category_value: str

    # live_playback: Json[LivePlayback] = Field(alias="livePlaybackJson") WIP
    live_polling_status: Json[LivePollingStatus] = Field(alias="livePollingStatusJson")
    open_date: datetime.datetime

    tags: list[str]


# This class used at search.
class Live(BaseLive):
    channel_id: str


class LiveDetail(BaseLive):
    status: Literal["OPEN", "CLOSE"]
    close_date: datetime.datetime
    chat_active: bool
    chat_available_group: str
    chat_available_condition: str
    paid_promotion: bool
    min_follower_minute: int
    user_adult_status: Optional[str]