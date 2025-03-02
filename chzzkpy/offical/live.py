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

from typing import Optional, Literal
from pydantic import Field, PrivateAttr, computed_field

from .base_model import ChzzkModel
from .category import Category
from .channel import Channel



class Live(ChzzkModel):
    live_id: int
    live_title: str
    live_image_url: str = Field(alias="liveThumbnailImageUrl")
    concurrent_user_count: int
    open_date: datetime.datetime
    adult: bool
    tags: list[str]

    _category_id: Optional[str] = PrivateAttr(default=None)
    _category_name: Optional[str] = PrivateAttr(default=None)
    _category_type: Optional[Literal["GAME", "SPORT", "ETC"]] = PrivateAttr(default=None)
    
    _channel_id: Optional[str] = PrivateAttr(default=None)
    _channel_name: Optional[str] = PrivateAttr(default=None)
    _channel_image: Optional[str] = PrivateAttr(default=None)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._category_id = kwargs.pop("liveCategory")
        self._category_name = kwargs.pop("liveCategoryValue")
        self._category_type = kwargs.pop("categoryType")

        self._channel_id = kwargs.pop("channelId")
        self._channel_name = kwargs.pop("channelName")
        self._channel_image = kwargs.pop("channelImageUrl")

    @computed_field
    @property
    def category(self) -> Category:
        return Category(
            id=self._category_id,
            name=self._category_name,
            type=self._category_type,
        )

    @computed_field
    @property
    def channel(self) -> Channel:
        return Channel(
            id=self._channel_id,
            name=self._channel_name,
            image=self._channel_image,
        )


class BrodecastSetting(ChzzkModel):
    title: str = Field(alias="defaultLiveTitle")
    category: Category
    tags: list[str]
