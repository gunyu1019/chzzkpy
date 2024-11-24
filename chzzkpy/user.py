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
from enum import Enum
from typing import Annotated, Any, Optional, Self, TYPE_CHECKING

from pydantic import BeforeValidator

from .base_model import ChzzkModel
from .manage.manage_model import ManagerClientAccessable

if TYPE_CHECKING:
    from .manage.chat_activity_count import ChatAcitivityCount


class UserRole(Enum):
    common_user = "common_user"
    streamer = "streamer"
    chat_manager = "streaming_chat_manager"
    channel_manager = "streaming_channel_manager"
    settlement_manager = "streaming_settlement_manager"
    manager = "manager"


class ParticleUser(ChzzkModel, ManagerClientAccessable):
    user_id_hash: Optional[str]
    nickname: Optional[str]
    profile_image_url: Optional[str]
    verified_mark: bool = False

    @ManagerClientAccessable.based_manage_client
    async def add_restrict(self) -> Self:
        result = await self._manage_client.add_restrict(self)
        return result
    
    @ManagerClientAccessable.based_manage_client
    async def remove_restrict(self):
        await self._manage_client.remove_restrict(self)
        
    @ManagerClientAccessable.based_manage_client
    async def add_role(self, role: UserRole) -> Self:
        result = await self._manage_client.add_role(self, role)
        return result
    
    @ManagerClientAccessable.based_manage_client
    async def remove_role(self):
        await self._manage_client.remove_role(self)
    
    @ManagerClientAccessable.based_manage_client
    async def chat_activity_count(self) -> ChatAcitivityCount:
        data = await self._manage_client.chat_activity_count(self)
        return data


class User(ParticleUser):
    has_profile: bool
    penalties: Optional[list[Any]]  # typing: ???
    official_noti_agree: bool
    official_noti_agree_updated_date: Annotated[
        Optional[datetime.datetime],
        BeforeValidator(ChzzkModel.special_date_parsing_validator),
    ]  # Example: YYYY-MM-DDTHH:MM:SS.SSS+09
    logged_in: Optional[bool]
