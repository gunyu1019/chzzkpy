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
import functools
import logging
from typing import Annotated, Final, Optional, Literal

from ahttp_client import Session, get, post, put, delete, Path, Query
from ahttp_client.extension import get_pydantic_response_model
from ahttp_client.request import RequestCore

from .base_model import ChzzkModel, Content
from .channel import Channel
from .error import LoginRequired, HTTPException, NotFound
from .manage import ChatAcitivityCount, ProhibitWordResponse, ChatRule, Stream, ManageResult, Follower, Subcriber
from .live import LiveStatus, LiveDetail
from .search import TopSearchResult
from .user import ParticleUser, User

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
            raise NotFound(data.get("message"))
        elif response.status >= 400:
            data = await response.json()
            raise HTTPException(code=data["code"], message=data["message"])
        return response

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

        self.temporary_restrict.before_hook(self.query_to_json)
        self.restrict.before_hook(self.query_to_json)
        self.set_role.before_hook(self.query_to_json)
        self.add_prohibit_word.before_hook(self.query_to_json)
        self.edit_prohibit_word.before_hook(self.query_to_json)
        self.set_chat_rule.before_hook(self.query_to_json)


    @get_pydantic_response_model()
    @get("/polling/v2/channels/{channel_id}/live-status", directly_response=True)
    async def live_status(
        self, channel_id: Annotated[str, Path]
    ) -> Content[Optional[LiveStatus]]:
        pass

    @get_pydantic_response_model()
    @get("/service/v2/channels/{channel_id}/live-detail", directly_response=True)
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

    # Manage Feature

    @get_pydantic_response_model()
    @post("/manage/v1/channels/{channel_id}/temporary-restrict-users", directory_response=True)
    @ChzzkSession.configuration(login_able=True, login_required=True)
    async def temporary_restrict(
        self,
        channel_id: Annotated[str, Path],
        chat_channel_id: Annotated[str, Query.to_camel()],
        target_id: Annotated[str, Query.to_camel()]
    ) -> Content[ParticleUser]:
        pass
    
    @get_pydantic_response_model()
    @post("/manage/v1/channels/{channel_id}/restrict-users", directory_response=True)
    @ChzzkSession.configuration(login_able=True, login_required=True)
    async def restrict(
        self,
        channel_id: Annotated[str, Path],
        target_id: Annotated[str, Query.to_camel()]
    ) -> Content[ParticleUser]:
        pass
    
    @get_pydantic_response_model()
    @delete("/manage/v1/channels/{channel_id}/restrict-users/{target_id}", directory_response=True)
    @ChzzkSession.configuration(login_able=True, login_required=True)
    async def remove_restrict(
        self,
        channel_id: Annotated[str, Path],
        target_id: Annotated[str, Path]
    ) -> Content[ParticleUser]:
        pass
    
    @get_pydantic_response_model()
    @post("/manage/v1/channels/{channel_id}/streaming-roles", directory_response=True)
    @ChzzkSession.configuration(login_able=True, login_required=True)
    async def set_role(
        self,
        channel_id: Annotated[str, Path],
        target_id: Annotated[str, Query.to_camel()],
        user_role_type: Annotated[
            Literal['streaming_chat_manager', 'streaming_channel_manager'],
            Query.to_camel()
        ],
    ) -> Content[ParticleUser]:
        pass
    
    @get_pydantic_response_model()
    @delete("/manage/v1/channels/{channel_id}/streaming-roles/{target_id}", directory_response=True)
    @ChzzkSession.configuration(login_able=True, login_required=True)
    async def remove_role(
        self,
        channel_id: Annotated[str, Path],
        target_id: Annotated[str, Path],
    ) -> Content[None]:
        pass
    
    @get_pydantic_response_model()
    @get("/manage/v1/channels/{channel_id}/chats/prohibit-words", directory_response=True)
    @ChzzkSession.configuration(login_able=True, login_required=True)
    async def get_prohibit_words(
        self,
        channel_id: Annotated[str, Path],
    ) -> Content[ProhibitWordResponse]:
        pass
    
    @get_pydantic_response_model()
    @post("/manage/v1/channels/{channel_id}/chats/prohibit-words", directory_response=True)
    @ChzzkSession.configuration(login_able=True, login_required=True)
    async def add_prohibit_word(
        self,
        channel_id: Annotated[str, Path],
        prohibit_word: Annotated[str, Query.to_camel()]
    ) -> Content[None]:
        pass
    
    @get_pydantic_response_model()
    @delete("/manage/v1/channels/{channel_id}/chats/prohibit-words/{prohibit_word_number}", directory_response=True)
    @ChzzkSession.configuration(login_able=True, login_required=True)
    async def remove_prohibit_word(
        self,
        channel_id: Annotated[str, Path],
        prohibit_word_number: Annotated[str, Path]
    ) -> Content[None]:
        pass
    
    @get_pydantic_response_model()
    @delete("/manage/v1/channels/{channel_id}/chats/prohibit-words", directory_response=True)
    @ChzzkSession.configuration(login_able=True, login_required=True)
    async def remove_prohibit_word_all(
        self,
        channel_id: Annotated[str, Path],
    ) -> Content[None]:
        pass
    
    @get_pydantic_response_model()
    @put("/manage/v1/channels/{channel_id}/chats/prohibit-words/{prohibit_word_number}", directory_response=True)
    @ChzzkSession.configuration(login_able=True, login_required=True)
    async def edit_prohibit_word(
        self,
        channel_id: Annotated[str, Path],
        prohibit_word_number: Annotated[str, Path],
        prohibit_word: Annotated[str, Query.to_camel()]
    ) -> Content[None]:
        pass
    
    @get_pydantic_response_model()
    @get("/manage/v1/channels/{channel_id}/streams", directory_response=True)
    @ChzzkSession.configuration(login_able=True, login_required=True)
    async def stream(
        self,
        channel_id: Annotated[str, Path],
    ) -> Content[Stream]:
        pass
    
    @get_pydantic_response_model()
    @get("/manage/v1/channels/{channel_id}/chat-rules", directory_response=True)
    @ChzzkSession.configuration(login_able=True, login_required=True)
    async def get_chat_rule(
        self,
        channel_id: Annotated[str, Path],
    ) -> Content[ChatRule]:
        pass
    
    @get_pydantic_response_model()
    @put("/manage/v1/channels/{channel_id}/chat-rules", directory_response=True)
    @ChzzkSession.configuration(login_able=True, login_required=True)
    async def set_chat_rule(
        self,
        channel_id: Annotated[str, Path],
        rule: Annotated[str, Query.to_camel()]
    ) -> Content[None]:
        pass
    
    @get_pydantic_response_model()
    @get("/manage/v1/channels/{channel_id}/users/{target_id}/chat-activity-count", directory_response=True)
    @ChzzkSession.configuration(login_able=True, login_required=True)
    async def get_chat_activity_count(
        self,
        channel_id: Annotated[str, Path],
        target_id: Annotated[str, Path],
    ) -> Content[ChatAcitivityCount]:
        pass
    
    @get_pydantic_response_model()
    @get("/manage/v1/channels/{channel_id}/subscribers", directory_response=True)
    @ChzzkSession.configuration(login_able=True, login_required=True)
    async def subcribers(
        self,
        channel_id: Annotated[str, Path],
        page: Annotated[int, Query.to_camel()] = 0,
        size: Annotated[int, Query.to_camel()] = 50,
        sort_type: Annotated[Optional[Literal['RECENT', 'LONGER']], Query.to_camel()] = 'RECENT',
        publish_period: Annotated[Optional[Literal['1', '3', '6']], Query.to_camel()] = None,
        tier: Annotated[Optional[Literal['TIER_1', 'TIER_2']], Query.to_camel()] = None,
        user_nickname: Annotated[Optional[str], Query.to_camel()] = None
    ) -> Content[ManageResult[Subcriber]]:
        pass
    
    @get_pydantic_response_model()
    @get("/manage/v1/channels/{channel_id}/followers", directory_response=True)
    @ChzzkSession.configuration(login_able=True, login_required=True)
    async def followers(
        self,
        channel_id: Annotated[str, Path],
        page: Annotated[int, Query.to_camel()] = 0,
        size: Annotated[int, Query.to_camel()] = 50,
        sort_type: Annotated[Optional[Literal['RECENT', 'LONGER']], Query.to_camel()] = 'RECENT',
    ) -> Content[ManageResult[Follower]]:
        pass

class NaverGameAPISession(ChzzkSession):
    def __init__(self, loop: Optional[asyncio.AbstractEventLoop] = None):
        super().__init__(base_url="https://comm-api.game.naver.com", loop=loop)

    @get_pydantic_response_model()
    @get("/nng_main/v1/user/getUserStatus", directly_response=True)
    @ChzzkSession.configuration(login_able=True, login_required=True)
    async def user(self) -> Content[User]:
        pass
