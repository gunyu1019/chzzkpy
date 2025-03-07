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

from pydantic import PrivateAttr
from typing import Generic, Optional, TypeVar, TYPE_CHECKING

from ..base_model import ChzzkModel
from ..base_model import Content

if TYPE_CHECKING:
    from typing import Any, Callable, Coroutine, Optional

T = TypeVar("T")


class SearchResult(ChzzkModel, Generic[T]):
    data: list[T]

    _page: Optional[dict[str]] = PrivateAttr(default=None)
    _next_method: Optional[Callable[..., Coroutine[Any, Any, Content[T]]]] = (
        PrivateAttr(default=None)
    )
    _next_method_arguments: Optional[tuple[Any]] = PrivateAttr(default=None)
    _next_method_key_argument: Optional[dict[str, Any]] = PrivateAttr(default=None)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "page" in kwargs.keys():
            self._page = kwargs.pop("page")

    async def next(self) -> Optional[SearchResult]:
        if self._page is None or self._next_method is None:
            raise RuntimeError(f"This search result has only one result.")
        next_id = self._page["next"]
        next_method_arguments = self._next_method_arguments or tuple()
        next_method_key_argument = self._next_method_key_argument or dict()

        result = await self._next_method(
            *next_method_arguments, next=next_id, **next_method_key_argument
        )
        data = result.content
        data._next_method = self._next_method
        data._next_method_arguments = self._next_method_arguments
        data._next_method_key_argument = self._next_method_key_argument
        return data
