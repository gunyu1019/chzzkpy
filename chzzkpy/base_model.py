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

from functools import wraps
from typing import Generic, TypeVar, Optional, TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Extra, PrivateAttr
from pydantic.alias_generators import to_camel

if TYPE_CHECKING:
    from .manage.manage_client import ManageClient

T = TypeVar("T")


class ChzzkModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel, frozen=True, extra=Extra.allow  # prevent exception.
    )

    @staticmethod
    def special_date_parsing_validator(value: T) -> T:
        if not isinstance(value, str):
            return value
        return value.replace("+09", "")


class Content(ChzzkModel, Generic[T]):
    code: int
    message: Optional[str]
    content: Optional[T]


class ManagerClientAccessable(BaseModel):
    _manage_client: Optional[ManageClient] = PrivateAttr(default=None)

    @staticmethod
    def based_manage_client(func):
        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            if not self.is_interactable:
                raise RuntimeError(
                    f"This {self.__class__.__name__} is intended to store data only."
                )
            return await func(self, *args, **kwargs)

        return wrapper

    @property
    def channel_id(self) -> str:
        if not self.is_interactable:
            raise RuntimeError(
                f"This {self.__class__.__name__} is intended to store data only."
            )
        return self._manage_client.channel_id

    @property
    def is_interactable(self):
        """Ensure this model has access to interact with manage client."""
        return self._manage_client is not None

    def _set_manage_client(self, client: ManageClient):
        if self.is_interactable:
            raise ValueError("Manage Client already set.")
        self._manage_client = client
        return self
