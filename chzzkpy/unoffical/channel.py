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

from typing import Optional

from pydantic import BeforeValidator, Field

from .base_model import ChzzkModel


class ChannelPersonalData(ChzzkModel):
    private_user_block: bool = False


class PartialChannel(ChzzkModel):
    id: str = Field(alias="channelId")
    name: str = Field(alias="channelName")
    image: Optional[str] = Field(alias="channelImageUrl")
    verified_mark: bool = False
    personal_data: Optional[ChannelPersonalData] = None


class Channel(PartialChannel):
    description: str = Field(alias="channelDescription")
    follower: int = Field("followerCount")
    open_live: bool
