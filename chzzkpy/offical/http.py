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

from ahttp_client import Session, request, get, post, put, BodyJson, Query, Header, Path
from ahttp_client.extension import pydantic_response_model
from ahttp_client.request import RequestCore

from .authorization import AccessToken
from .base_model import Content, SearchResult
from .category import CATEGORY_TYPE, Category
from .channel import Channel
from .chat import ChatSetting
from .error import (
    LoginRequired,
    BadRequestException,
    UnauthorizedException,
    ForbiddenException,
    NotFoundException,
    TooManyRequestsException,
    HTTPException,
)
from .live import BrodecastSetting, Live
from .session import SessionKey

_log = logging.getLogger(__name__)


class ChzzkOpenAPISession(Session):
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        loop: Optional[asyncio.AbstractEventLoop] = None,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        super().__init__(base_url="https://openapi.chzzk.naver.com", loop=loop)

    async def before_request(
        self, request: RequestCore, path: str
    ) -> tuple[RequestCore, str]:
        _log.debug(f"Path({path}) was called.")

        if hasattr(request.func, "__authorization_configuration__"):
            authorization_configuration = request.func.__authorization_configuration__

            if authorization_configuration["user"]:
                for key, value in request.headers.items():
                    if not isinstance(value, AccessToken):
                        continue

                    access_token = request.headers.pop(key)
                    request.headers["Authorization"] = (
                        f"{access_token.token_type} {access_token.access_token}"
                    )
                    break
                else:
                    if not authorization_configuration["client"]:
                        raise LoginRequired()

            if authorization_configuration["client"]:
                request.headers["Client-Id"] = self.client_id
                request.headers["Client-Secret"] = self.client_secret

        request.headers["Content-Type"] = "application/json"
        return request, path

    async def after_request(self, response: aiohttp.ClientResponse):
        if response.status == 400:
            raise BadRequestException(response.reason)
        elif response.status == 401:
            data = await response.json()
            raise UnauthorizedException(data.get("message"))
        elif response.status == 403:
            data = await response.json()
            raise ForbiddenException(data.get("message"))
        elif response.status == 404:
            data = await response.json()
            raise NotFoundException(data.get("message"))
        elif response.status == 429:
            raise TooManyRequestsException(response.reason)
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

    @staticmethod
    def authorization_configuration(is_client: bool = False, is_user: bool = False):
        def decorator(func):
            func.__authorization_configuration__ = {
                "client": is_client,
                "user": is_user,
            }
            return func

        return decorator

    @overload
    async def generate_access_token(
        self,
        grant_type: Annotated[Literal["authorization_code"], BodyJson.to_camel()],
        client_id: Annotated[str, BodyJson.to_camel()],
        client_secret: Annotated[str, BodyJson.to_camel()],
        code: Annotated[Optional[str], BodyJson.to_camel()],
        state: Annotated[Optional[str], BodyJson.to_camel()],
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
    @authorization_configuration(is_client=True, is_user=False)
    async def generate_access_token(
        self,
        grant_type: Annotated[
            Literal["authorization_code", "refresh_token"], BodyJson.to_camel()
        ],
        client_id: Annotated[str, BodyJson.to_camel()],
        client_secret: Annotated[str, BodyJson.to_camel()],
        code: Annotated[Optional[str], BodyJson.to_camel()] = None,
        state: Annotated[Optional[str], BodyJson.to_camel()] = None,
        refresh_token: Annotated[Optional[str], BodyJson.to_camel()] = None,
    ) -> Content[AccessToken]:
        pass

    @post("/auth/v1/token/revoke", directly_response=True)
    @authorization_configuration(is_client=True, is_user=False)
    async def revoke_access_token(
        self,
        client_id: Annotated[str, BodyJson.to_camel()],
        client_secret: Annotated[str, BodyJson.to_camel()],
        token: Annotated[Optional[str], BodyJson.to_camel()],
        token_type_hint: Annotated[
            Literal["access_token", "refresh_token"], BodyJson.to_camel()
        ] = "access_token",
    ) -> None:
        pass

    @pydantic_response_model()
    @post("/open/v1/channels", directly_response=True)
    @authorization_configuration(is_client=True, is_user=False)
    async def get_channel(
        self, channel_ids: Annotated[str, Query.to_camel()]
    ) -> Content[SearchResult[Channel]]:
        pass

    @pydantic_response_model()
    @post("/open/v1/categories/search", directly_response=True)
    @authorization_configuration(is_client=True, is_user=False)
    async def get_category(
        self, query: Annotated[str, Query], size: Annotated[Optional[int], Query] = 20
    ) -> Content[SearchResult[Category]]:
        pass

    @pydantic_response_model()
    @get("/open/v1/sessions/auth/client", directly_response=True)
    @authorization_configuration(is_client=True, is_user=False)
    async def generate_client_session(self) -> Content[SessionKey]:
        pass

    @pydantic_response_model()
    @get("/open/v1/sessions/auth", directly_response=True)
    @authorization_configuration(is_client=False, is_user=True)
    async def generate_user_session(
        self, token: Annotated[Optional[AccessToken], Header] = None
    ) -> Content[SessionKey]:
        pass

    @pydantic_response_model()
    @post("/open/v1/sessions/events/subscribe/{event}", directly_response=True)
    @authorization_configuration(is_client=True, is_user=True)
    async def subcribe_event(
        self,
        event: Annotated[str, Path],
        session_key: Annotated[str, Query.to_camel()],
        token: Annotated[Optional[AccessToken], Header] = None,
    ) -> Content[None]:
        pass

    @pydantic_response_model()
    @post("/open/v1/sessions/events/unsubscribe/{event}", directly_response=True)
    @authorization_configuration(is_client=True, is_user=True)
    async def unsubcribe_event(
        self,
        event: Annotated[str, Path],
        session_key: Annotated[str, Query.to_camel()],
        token: Annotated[Optional[AccessToken], Header] = None,
    ) -> Content[None]:
        pass

    @pydantic_response_model()
    @get("/open/v1/users/me", directly_response=True)
    @authorization_configuration(is_client=False, is_user=True)
    async def get_user_self(
        self,
        token: Annotated[AccessToken, Header],
    ) -> Content[Channel]:
        pass

    @pydantic_response_model()
    @post("/open/v1/chats/send", directly_response=True)
    @authorization_configuration(is_client=False, is_user=True)
    async def create_message(
        self, token: Annotated[AccessToken, Header], message: Annotated[str, BodyJson]
    ) -> Content[dict[str, str]]:
        pass

    @post("/open/v1/chats/notice", directly_response=True)
    @authorization_configuration(is_client=False, is_user=True)
    async def create_notice(
        self,
        token: Annotated[AccessToken, Header],
        message: Annotated[Optional[str], BodyJson] = None,
        message_id: Annotated[Optional[str], BodyJson.to_camel()] = None,
    ) -> None:
        pass

    @pydantic_response_model()
    @get("/open/v1/chats/settings", directly_response=True)
    @authorization_configuration(is_client=False, is_user=True)
    async def get_chat_setting(
        self,
        token: Annotated[AccessToken, Header],
    ) -> Content[ChatSetting]:
        pass

    @put("/open/v1/chats/settings", directly_response=True)
    @authorization_configuration(is_client=False, is_user=True)
    async def set_chat_setting(
        self,
        token: Annotated[AccessToken, Header],
        chat_available_condition: Annotated[
            Literal["NONE", "REAL_NAME"], BodyJson.to_camel()
        ],
        chat_available_group: Annotated[
            Literal["ALL", "FOLLOWER", "MANAGER", "SUBSCRIBER"], BodyJson.to_camel()
        ],
        min_follower_minute: Annotated[int, BodyJson.to_camel()],
        allow_subscriber_in_follower_mode: Annotated[bool, BodyJson.to_camel()],
    ) -> None:
        pass

    @pydantic_response_model()
    @get("/open/v1/lives/setting", directly_response=True)
    @authorization_configuration(is_client=False, is_user=True)
    async def get_live_setting(
        self, token: Annotated[AccessToken, Header]
    ) -> Content[BrodecastSetting]:
        pass

    @request("patch", "/open/v1/lives/setting", directly_response=True)
    @authorization_configuration(is_client=False, is_user=True)
    async def set_live_setting(
        self,
        token: Annotated[AccessToken, Header],
        default_live_title: Annotated[Optional[str], BodyJson.to_camel()] = None,
        category_type: Annotated[Optional[CATEGORY_TYPE], BodyJson.to_camel()] = None,
        category_id: Annotated[Optional[str], BodyJson.to_camel()] = None,
        tags: Annotated[Optional[list[str]], BodyJson.to_camel()] = None,
    ) -> None:
        pass

    @pydantic_response_model()
    @get("/open/v1/streams/key", directly_response=True)
    @authorization_configuration(is_client=False, is_user=True)
    async def get_stream_key(
        self, token: Annotated[AccessToken, Header]
    ) -> Content[dict[str, str]]:
        pass

    @pydantic_response_model()
    @get("/open/v1/lives", directly_response=True)
    @authorization_configuration(is_client=True, is_user=False)
    async def get_lives(
        self,
        size: Annotated[Optional[int], Query] = 20,
        next: Annotated[Optional[str], Query] = None,
    ) -> Content[SearchResult[Live]]:
        pass
