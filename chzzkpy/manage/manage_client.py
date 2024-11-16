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

from typing import List, TYPE_CHECKING
from ..error import LoginRequired
from .http import ChzzkManageSession


if TYPE_CHECKING:
    from ..client import Client
    from .prohibit_word import ProhibitWord


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
            session_key=self.client._api_session._session_key
        )

    async def close(self):
        """Closes the connection to chzzk."""
        await self._http.close()
        await super().close()
        return
    
    async def get_prohibit_words(self) -> List[ProhibitWord]:
        data = await self._http.get_prohibit_words(self.channel_id)
        return data.content.prohibit_words
    
    async def add_prohibit_word(self, word: str) -> bool:
        result = await self._http.add_prohibit_word(word)
        return result.code == 200
