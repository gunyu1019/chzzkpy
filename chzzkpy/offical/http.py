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

import asyncio
import aiohttp
import logging
from typing import Annotated, Final, Optional

from ahttp_client import Session, get, Path, Query
from ahttp_client.extension import get_pydantic_response_model
from ahttp_client.request import RequestCore

from .error import NotFound, HTTPException

_log = logging.getLogger(__name__)


class ChzzkSession(Session):
    def __init__(self, loop: Optional[asyncio.AbstractEventLoop] = None):
        super().__init__(base_url="https://openapi.chzzk.naver.com", loop=loop)

    async def before_request(
        self, request: RequestCore, path: str
    ) -> tuple[RequestCore, str]:
        _log.debug(f"Path({path}) was called.")

        return request, path

    async def after_request(self, response: aiohttp.ClientResponse):
        if response.status == 404:
            data = await response.json()
            raise NotFound(data.get("message"))
        elif response.status >= 400:
            data = await response.json()
            raise HTTPException(code=data["code"], message=data["message"])
        return response

    @staticmethod
    async def query_to_json(session: Session, request: RequestCore, path: str):
        copied_request_obj = request.copy()
        body = dict()
        for key, value in request.params.copy().items():
            body[key] = value
        copied_request_obj.params = dict()
        copied_request_obj.body = body
        return copied_request_obj, path
