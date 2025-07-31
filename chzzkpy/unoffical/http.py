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

from .base_model import Content
from .error import LoginRequired, HTTPException, NotFoundException
from .live import LiveStatus, LiveDetail
from .search import TopSearchResult
from .user import User

_log = logging.getLogger(__name__)
_user_agent: Final[str] = (
    "Mozilla/5.0 (Windows NT 6.3; Win64; x64) AppleWebKit/537.36"
    "(KHTML, like Gecko) Chrome/37.0.2049.0 Safari/537.36"
)


class ChzzkSession(Session):
    def __init__(self, base_url: str, loop: Optional[asyncio.AbstractEventLoop] = None):
        super().__init__(base_url=base_url, loop=loop)

        self._authorization_key = None
        self._session_key = None

    def login(self, authorization_key: str, session_key: str):
        self._authorization_key = authorization_key
        self._session_key = session_key

    @property
    def has_login(self) -> bool:
        return self._authorization_key is not None and self._session_key is not None

    @staticmethod
    def configuration(login_able: bool = False, login_required: bool = False):
        def decorator(func):
            func.__login_able__ = login_able
            func.__login_required__ = login_required
            return func

        return decorator

    async def before_request(
        self, request: RequestCore, path: str
    ) -> tuple[RequestCore, str]:
        _log.debug(f"Path({path}) was called.")

        # Authorization
        if getattr(request.func, "__login_able__", False):
            if self.has_login:
                if "Cookie" not in request.headers.keys():
                    request.headers["Cookie"] = ""
                request.headers["Cookie"] += self._token
            elif getattr(request.func, "__login_required__", False):
                raise LoginRequired()

        # Add User-Agent to avoid blocking
        if "User-Agent" not in request.headers:
            request.headers["User-Agent"] = _user_agent

        return request, path

    async def after_request(self, response: aiohttp.ClientResponse):
        if response.status == 404:
            data = await response.json()
            raise NotFoundException(data.get("message"))
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

    @property
    def _token(self) -> str:
        return f"NID_SES={self._session_key}; NID_AUT={self._authorization_key}"


class ChzzkAPISession(ChzzkSession):
    def __init__(self, loop: Optional[asyncio.AbstractEventLoop] = None):
        super().__init__(base_url="https://api.chzzk.naver.com", loop=loop)

    @get_pydantic_response_model()
    @get("/polling/v2/channels/{channel_id}/live-status", directly_response=True)
    @ChzzkSession.configuration(login_able=True, login_required=False)
    async def live_status(
        self, channel_id: Annotated[str, Path]
    ) -> Content[Optional[LiveStatus]]:
        pass

    @get_pydantic_response_model()
    @get("/service/v2/channels/{channel_id}/live-detail", directly_response=True)
    @ChzzkSession.configuration(login_able=True, login_required=True)
    async def live_detail(
        self, channel_id: Annotated[str, Path]
    ) -> Content[LiveDetail]:
        pass

    @get_pydantic_response_model()
    @get("/service/v1/search/channels", directly_response=True)
    async def search_channel(
        self,
        keyword: Annotated[str, Query],
        offset: Annotated[int, Query] = 0,
        size: Annotated[int, Query] = 13,
    ) -> Content[TopSearchResult]:
        pass

    @get_pydantic_response_model()
    @get("/service/v1/search/lives", directly_response=True)
    async def search_live(
        self,
        keyword: Annotated[str, Query],
        offset: Annotated[int, Query] = 0,
        size: Annotated[int, Query] = 13,
    ) -> Content[TopSearchResult]:
        pass

    @get_pydantic_response_model()
    @get("/service/v1/search/videos", directly_response=True)
    async def search_video(
        self,
        keyword: Annotated[str, Query],
        offset: Annotated[int, Query] = 0,
        size: Annotated[int, Query] = 13,
    ) -> Content[TopSearchResult]:
        pass

    @get_pydantic_response_model()
    @get("/service/v1/search/channels/auto-complete", directly_response=True)
    async def autocomplete(
        self,
        keyword: Annotated[str, Query],
        offset: Annotated[int, Query] = 0,
        size: Annotated[int, Query] = 13,
    ) -> Content[TopSearchResult]:
        pass


class NaverGameAPISession(ChzzkSession):
    def __init__(self, loop: Optional[asyncio.AbstractEventLoop] = None):
        super().__init__(base_url="https://comm-api.game.naver.com", loop=loop)

    @get_pydantic_response_model()
    @get("/nng_main/v1/user/getUserStatus", directly_response=True)
    @ChzzkSession.configuration(login_able=True, login_required=True)
    async def user(self) -> Content[User]:
        pass
