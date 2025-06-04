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
from enum import Enum
from typing import Annotated, Any, Optional, Literal, TYPE_CHECKING

from pydantic import BeforeValidator

from .base_model import ChzzkModel, ManagerClientAccessable

if TYPE_CHECKING:
    from .manage.chat_activity_count import ChatActivityCount


class UserRole(Enum):
    common_user = "common_user"
    streamer = "streamer"
    chat_manager = "streaming_chat_manager"
    channel_manager = "streaming_channel_manager"
    settlement_manager = "streaming_settlement_manager"
    manager = "manager"


class PartialUser(ChzzkModel, ManagerClientAccessable):
    user_id_hash: Optional[str]
    nickname: Optional[str]
    profile_image_url: Optional[str] = None
    verified_mark: bool = False

    @ManagerClientAccessable.based_manage_client
    async def add_restrict(
        self,
        days: Literal[1, 3, 7, 15, 30, 90] | None = 7,
        reason: Optional[str] = None,
    ):
        """Add this user to restrict activity."""
        result = await self._manage_client.add_restrict(self, days=days, reason=reason)
        return result

    @ManagerClientAccessable.based_manage_client
    async def edit_restrict(
        self,
        days: Literal[1, 3, 7, 15, 30, 90] | None = 7,
        reason: Optional[str] = None,
    ):
        """Modify this user to restrict activity."""
        result = await self._manage_client.edit_restrict(self, days=days, reason=reason)
        return result

    @ManagerClientAccessable.based_manage_client
    async def remove_restrict(self):
        """Remove this user to restrict activity."""
        await self._manage_client.remove_restrict(self)

    @ManagerClientAccessable.based_manage_client
    async def add_role(self, role: UserRole):
        """Add a broadcast permission to this user.

        Parameters
        ----------
        role : UserRole
            A enumeration class containing broadcast role.
            It can only set the role to :attr:`UserRole.chat_manager`,
            :attr:`UserRole.settlement_manager`, or :attr:`UserRole.channel_manager`.
            Giving any other role will cause a :exc:`TypeError` exception.
        """
        result = await self._manage_client.add_role(self, role)
        return result

    @ManagerClientAccessable.based_manage_client
    async def remove_role(self):
        """Remove a broadcast permission to this user."""
        await self._manage_client.remove_role(self)

    @ManagerClientAccessable.based_manage_client
    async def chat_activity_count(self) -> ChatActivityCount:
        """Get chat activity count of this user.

        Returns
        -------
        ChatActivityCount
            Returns a chat activity count object contains the count of temporary activity restrictions,
            the count of activity restrictions, and the count of chats.
        """
        data = await self._manage_client.chat_activity_count(self)
        return data


class User(PartialUser):
    has_profile: bool
    penalties: Optional[list[Any]]  # typing: ???
    official_noti_agree: bool
    official_noti_agree_updated_date: Annotated[
        Optional[datetime.datetime],
        BeforeValidator(ChzzkModel.special_date_parsing_validator),
    ]  # Example: YYYY-MM-DDTHH:MM:SS.SSS+09
    logged_in: Optional[bool]
