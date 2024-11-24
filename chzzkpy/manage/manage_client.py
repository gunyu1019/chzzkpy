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

from typing import List, Literal, Optional, TYPE_CHECKING
from ..error import LoginRequired
from ..user import ParticleUser, UserRole
from .enums import SortType, SubscriberTier
from .http import ChzzkManageSession
from .chat_activity_count import ChatAcitivityCount
from .prohibit_word import ProhibitWord
from .stream import Stream
from .manage_search import ManageResult, ManageSubcriber, ManageFollower, RestrictUser, ManageVideo

if TYPE_CHECKING:
    from ..client import Client


class ManageClient:
    """Represent a client that provides broadcast management functionality."""
    def __init__(self, channel_id: str, client: Client):
        self.channel_id = channel_id
        self.client = client

        # All manage feature needs login.
        if not self._http.has_login:
            raise LoginRequired()

        self._http = ChzzkManageSession(self.client.loop)
        self._http.login(
            authorization_key=self.client._api_session._authorization_key,
            session_key=self.client._api_session._session_key,
        )

    async def close(self):
        """Closes the connection to chzzk."""
        await self._http.close()
        await super().close()
        return

    async def get_prohibit_words(self) -> List[ProhibitWord]:
        """Get prohibit words in chat.

        Returns
        -------
        List[ProhibitWord]
            Returns the prohibit words.
        """
        data = await self._http.get_prohibit_words(self.channel_id)
        return data.content.prohibit_words

    async def get_prohbit_word(self, word: str) -> Optional[ProhibitWord]:
        """Get prohibit word with word.
        When word does not contain prohibit word, returns None. 

        Parameters
        ----------
        word : str
            A word to find prohibit word.

        Returns
        -------
        Optional[ProhibitWord]
            When word contains prohibit words, return :class:`ProhibitWord` object.
        """
        data = await self.get_prohibit_words()
        prohibit_words = [x for x in data if x.prohibit_word == word]
        if len(prohibit_words) <= 0:
            return
        return prohibit_words[0]

    async def add_prohibit_word(self, word: str) -> Optional[ProhibitWord]:
        """Add a prohibit word at chat.

        Parameters
        ----------
        word : str
            A word to prohibit.

        Returns
        -------
        Optional[ProhibitWord]
            Returns the generated prohibit word.
        """
        await self._http.add_prohibit_word(self.channel_id, word)
        return await self.get_prohbit_word(word)

    async def edit_prohibit_word(
        self, prohibit_word: ProhibitWord | int, word: str
    ) -> Optional[ProhibitWord]:
        """Modify a prohibit word.

        Parameters
        ----------
        prohibit_word : ProhibitWord | int
            The prohibit word object to modify.
            Instead, it can be prohibit word id.
        word : str
            A new word to prohibit.

        Returns
        -------
        Optional[ProhibitWord]
            Returns the modified prohibit word.
        """
        if isinstance(prohibit_word, ProhibitWord):
            prohibit_word_number = prohibit_word.prohibit_word_no
        else:
            prohibit_word_number = prohibit_word

        await self._http.edit_prohibit_word(self.channel_id, prohibit_word_number, word)
        return await self.get_prohbit_word(word)

    async def remove_prohibit_word(self, prohibit_word: ProhibitWord | int) -> None:
        """Remove a prohibit word.

        Parameters
        ----------
        prohibit_word : ProhibitWord | int
            The prohibit word object to remove.
            Instead, it can be prohibit word id.
        """
        if isinstance(prohibit_word, ProhibitWord):
            prohibit_word_number = prohibit_word.prohibit_word_no
        else:
            prohibit_word_number = prohibit_word

        await self._http.remove_prohibit_word(self.channel_id, prohibit_word_number)

    async def remove_prohibit_words(self) -> None:
        """Remove all prohibit words."""
        await self._http.remove_prohibit_word_all(self.channel_id)

    async def get_chat_rule(self) -> str:
        """Get chat rule of broadcast.

        Returns
        -------
        str
            Returns a chat rule.
        """
        data = await self._http.get_chat_rule(self.channel_id)
        return data.content.rule

    async def set_chat_rule(self, word: str) -> None:
        """Set chat rule of broadcast.

        Parameters
        ----------
        word : str
            A new chat rule to set up.
        """
        await self._http.set_chat_rule(self.channel_id, word)

    async def stream(self) -> Stream:
        """Get a stream key required for streamming.

        Returns
        -------
        Stream
            Return a stream key for streamming.
        """
        data = await self._http.stream()
        return data.content

    async def add_restrict(self, user: str | ParticleUser) -> ParticleUser:
        """Add an user to restrict activity.

        Parameters
        ----------
        user : str | ParticleUser
            A user object to add restrict activity.
            Instead, it can be user id or nickname.

        Returns
        -------
        ParticleUser
            Returns an object containning activity-restricted users.
        """
        target_id = user
        if isinstance(user, ParticleUser):
            target_id = user.user_id_hash

        data = await self._http.add_restrict(
            channel_id=self.channel_id, target_id=target_id
        )
        return data.content

    async def remove_restrict(self, user: str | ParticleUser) -> None:
        """Remove an user to restrict activity.

        Parameters
        ----------
        user : str | ParticleUser
            A user object to remove restrict activity.
            Instead, it can be user id or nickname.

        Returns
        -------
        ParticleUser
            Returns an user whose activity is unrestricted.
        """
        target_id = user
        if isinstance(user, ParticleUser):
            target_id = user.user_id_hash

        await self._http.remove_restrict(
            channel_id=self.channel_id, target_id=target_id
        )

    async def add_role(self, user: str | ParticleUser, role: UserRole) -> ParticleUser:
        user_id = user
        if isinstance(user, ParticleUser):
            user_id = user.user_id_hash

        if role in [UserRole.common_user, UserRole.streamer, UserRole.manager]:
            raise TypeError(f"You cannot give role({role.name}) to user.")

        data = await self._http.add_role(
            channel_id=self.channel_id, target_id=user_id, role=role.value
        )
        return data.content

    async def remove_role(self, user: str | ParticleUser) -> None:
        user_id = user
        if isinstance(user, ParticleUser):
            user_id = user.user_id_hash

        await self._http.remove_role(channel_id=self.channel_id, target_id=user_id)

    async def chat_activity_count(self, user: str | ParticleUser) -> ChatAcitivityCount:
        user_id = user
        if isinstance(user, ParticleUser):
            user_id = user.user_id_hash

        data = await self._http.chat_activity_count(
            channel_id=self.channel_id, target_id=user_id
        )
        return data.content

    async def subcribers(
        self,
        page: int = 0,
        size: int = 50,
        sort_type: SortType = SortType.recent,
        publish_period: Optional[Literal[1, 3, 6]] = None,
        tier: Optional[SubscriberTier] = None,
        nickname: Optional[str] = None,
    ) -> ManageResult[ManageSubcriber]:
        data = await self._http.subcribers(
            channel_id=self.channel_id,
            page=page,
            size=size,
            sort_type=sort_type.value,
            publish_period=publish_period,
            tier=None if tier is not None else tier.value,
            user_nickname=nickname,
        )
        return data.content

    async def followers(
        self, page: int = 0, size: int = 50, sort_type: SortType = SortType.recent
    ) -> ManageResult[ManageFollower]:
        data = await self._http.followers(
            channel_id=self.channel_id, page=page, size=size, sort_type=sort_type.value
        )
        return data.content

    async def restrict(
        self, page: int = 0, size: int = 50, nickname: Optional[str] = None
    ) -> ManageResult[RestrictUser]:
        data = await self._http.restricts(
            channel_id=self.channel_id, page=page, size=size, user_nickname=nickname
        )
        return data.content
    
    async def live_replay(self, page: int = 0, size: int = 50) -> ManageResult[ManageVideo]:
        data = await self._http.videos(
            channel_id=self.channel_id,
            video_type="REPLAY",
            page=page, size=size
        )
        return data.content
    
    async def videos(self, page: int = 0, size: int = 50) -> ManageResult[ManageVideo]:
        data = await self._http.videos(
            channel_id=self.channel_id,
            video_type="UPLOAD",
            page=page, size=size
        )
        return data.content