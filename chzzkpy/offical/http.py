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
from typing import Annotated, Optional, Literal, overload

from ahttp_client import Session, get, post, BodyJson
from ahttp_client.extension import pydantic_response_model
from ahttp_client.request import RequestCore

from .authorization import AccessToken
from .base_model import Content
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

    @overload
    async def generate_access_token(
        self,
        grant_type: Annotated[Literal["authorization_code"], BodyJson.to_camel()],
        client_id: Annotated[str, BodyJson.to_camel()],
        client_secret: Annotated[str, BodyJson.to_camel()],
        code: Annotated[Optional[str], BodyJson.to_camel()],
        state: Annotated[Optional[str], BodyJson.to_camel()]
    ) -> Content[AccessToken]:
        pass

    @overload
    async def generate_access_token(
        self,
        grant_type: Annotated[Literal["refresh_token"], BodyJson.to_camel()],
        client_id: Annotated[str, BodyJson.to_camel()],
        client_secret: Annotated[str, BodyJson.to_camel()],
        refresh_token: Annotated[Optional[str], BodyJson.to_camel()],
    ) -> Content[AccessToken]:
        pass
    
    @pydantic_response_model()
    @post("/auth/v1/token", directly_response=True)
    async def generate_access_token(
        self,
        grant_type: Annotated[Literal["authorization_code", "refresh_token"], BodyJson.to_camel()],
        client_id: Annotated[str, BodyJson.to_camel()],
        client_secret: Annotated[str, BodyJson.to_camel()],
        code: Annotated[Optional[str], BodyJson.to_camel()] = None,
        state: Annotated[Optional[str], BodyJson.to_camel()] = None,
        refresh_token: Annotated[Optional[str], BodyJson.to_camel()] = None,
    ) -> Content[AccessToken]:
        pass

    @post("/auth/v1/token/revoke", directly_response=True)
    async def revoke_access_token(
        self,
        client_id: Annotated[str, BodyJson.to_camel()],
        client_secret: Annotated[str, BodyJson.to_camel()],
        token: Annotated[Optional[str], BodyJson.to_camel()],
        token_type_hint: Annotated[Literal["access_token", "refresh_token"], BodyJson.to_camel()] = "access_token",
    ) -> None:
        pass
