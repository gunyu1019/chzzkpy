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

from typing import List, Optional, TYPE_CHECKING
from ..error import LoginRequired
from ..user import ParticleUser
from .http import ChzzkManageSession
from .chat_activity_count import ChatAcitivityCount
from .prohibit_word import ProhibitWord
from .stream import Stream

if TYPE_CHECKING:
    from ..client import Client


class ManageClient:
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
        data = await self._http.get_prohibit_words(self.channel_id)
        return data.content.prohibit_words

    async def get_prohbit_word(self, word: str) -> Optional[ProhibitWord]:
        data = await self.get_prohibit_words()
        prohibit_words = [x for x in data if x.prohibit_word == word]
        if len(prohibit_words) <= 0:
            return
        return prohibit_words[0]

    async def add_prohibit_word(self, word: str) -> Optional[ProhibitWord]:
        await self._http.add_prohibit_word(self.channel_id, word)
        return await self.get_prohbit_word(word)

    async def edit_prohibit_word(
        self, prohibit_word: ProhibitWord | int, word: str
    ) -> Optional[ProhibitWord]:
        if isinstance(prohibit_word, ProhibitWord):
            prohibit_word_number = prohibit_word.prohibit_word_no
        else:
            prohibit_word_number = prohibit_word

        await self._http.edit_prohibit_word(self.channel_id, prohibit_word_number, word)
        return await self.get_prohbit_word(word)

    async def remove_prohibit_word(self, prohibit_word: ProhibitWord | int) -> bool:
        if isinstance(prohibit_word, ProhibitWord):
            prohibit_word_number = prohibit_word.prohibit_word_no
        else:
            prohibit_word_number = prohibit_word

        result = await self._http.remove_prohibit_word(
            self.channel_id, prohibit_word_number
        )
        return result.code == 200

    async def remove_prohibit_words(self) -> bool:
        result = await self._http.remove_prohibit_word_all(self.channel_id)
        return result.code == 200

    async def get_chat_rule(self) -> str:
        data = await self._http.get_chat_rule(self.channel_id)
        return data.content.rule

    async def set_chat_rule(self, word: str) -> bool:
        result = await self._http.set_chat_rule(self.channel_id, word)
        return result.code == 200

    async def stream(self) -> Stream:
        data = await self._http.stream()
        return data.content

    async def add_restrict(self, user: str | ParticleUser) -> ParticleUser:
        target_id = user
        if isinstance(user, ParticleUser):
            target_id = user.user_id_hash

        data = await self._http.restrict(
            channel_id=self.channel_id, target_id=target_id
        )
        return data.content

    async def remove_restrict(self, user: str | ParticleUser) -> ParticleUser:
        target_id = user
        if isinstance(user, ParticleUser):
            target_id = user.user_id_hash

        data = await self._http.remove_restrict(
            channel_id=self.channel_id, target_id=target_id
        )
        return data.content

    async def chat_activity_count(self, user: str | ParticleUser) -> ChatAcitivityCount:
        user_id = user
        if isinstance(user, ParticleUser):
            user_id = user.user_id_hash

        data = await self._http.chat_activity_count(
            channel_id=self.channel_id, target_id=user_id
        )
        return data.content
