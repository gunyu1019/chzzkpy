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
from typing import Annotated, Any, Optional

from pydantic import BeforeValidator, ConfigDict, Field

from .base_model import ChzzkModel
from .channel import PartialChannel


class PartialVideo(ChzzkModel):
    id: Optional[str] = Field(alias="videoId")
    number: int = Field(alias="videoNo")
    title: str = Field(alias="videoTitle")
    type: str = Field(alias="videoType")
    duration: int
    publish_date: Annotated[
        Optional[datetime.datetime],
        BeforeValidator(ChzzkModel.special_date_parsing_validator),
    ] = None
    thumbnail_image_url: Optional[str]


class Video(PartialVideo):
    model_config = ConfigDict(frozen=False)

    adult: bool
    category_type: Optional[str]
    channel: Optional[PartialChannel] = None
    channel_id: str
    # publish_date_at: int # div/1000
    read_count: int
    video_category: Optional[str]
    video_category_value: str
