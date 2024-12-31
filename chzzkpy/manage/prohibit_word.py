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

from ..base_model import ChzzkModel, ManagerClientAccessable


class ProhibitWord(ChzzkModel, ManagerClientAccessable):
    created_date: datetime.datetime
    nickname: str
    prohibit_word: str
    prohibit_word_no: int

    @ManagerClientAccessable.based_manage_client
    async def remove(self):
        """Remove this prohibit word."""
        await self._manage_client.remove_prohibit_word(self)

    @ManagerClientAccessable.based_manage_client
    async def edit(self, word: str):
        """Modify this prohibit word.

        Parameters
        ----------
        word : str
            A new word to prohibit.
        """
        data = await self._manage_client.edit_prohibit_word(self, word)
        return data


class ProhibitWordResponse(ChzzkModel):
    prohibit_word_list: list[ProhibitWord]
