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

import asyncio
import datetime

from functools import wraps
from typing import Optional, TYPE_CHECKING
from yarl import URL

from .enums import APIScope
from .http import ChzzkOpenAPISession

if TYPE_CHECKING:
    from typing import Self

    from .authorization import AccessToken
    from .channel import Channel


class _LoopSentinel:
    __slots__ = ()

    def __getattr__(self, attr: str) -> None:
        msg = (
            'loop attribute cannot be accessed in non-async contexts. '
            'Consider using either an asynchronous main function and passing it to asyncio.run'
        )
        raise AttributeError(msg)


class Client:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        loop: Optional[asyncio.AbstractEventLoop] = None,
    ):
        self.loop = loop or _LoopSentinel()
        self.client_id = client_id
        self.client_secret = client_secret

        self.http = ChzzkOpenAPISession(
            loop=self.loop,
            client_id=client_id,
            client_secret=client_secret
        )
        self.user_client = []
    
    async def __aenter__(self) -> Self:
        await self._async_setup_hook()
        return self
    
    async def _async_setup_hook(self) -> None:
        loop = asyncio.get_running_loop()
        self.loop = loop
        self.http.loop = loop

    @staticmethod
    def initial_async_setup(func):
        @wraps(func)
        async def wrppaer(self: Self, *args, **kwargs):
            if self.loop is _LoopSentinel:
                await self._async_setup_hook()
            return await func(*args, **kwargs)
        return wrppaer

    def generate_authorization_token_url(self, redirect_url: str, state: list[APIScope]) -> str:
        default_url = URL.build(scheme="https", authority="chzzk.naver.com", path="/account-interlock")
        default_url = default_url.with_query({
            "clientId": self.client_id,
            "redirectUri": redirect_url,
            "state": ",".join(state)
        })
        return default_url.geturl()

    @initial_async_setup
    async def generate_access_token(self, code: str, state: list[APIScope]) -> AccessToken:
        result = await self.http.generate_access_token(
            grant_type="authorization_code",
            client_id=self.client_id,
            client_secret=self.client_secret,
            code=code,
            state=",".join(state)
        )
        return result.content

    async def generate_user_client(self, code: str, state: list[APIScope]) -> UserClient:
        access_token = await self.generate_access_token(code, state)
        user_cls = UserClient(self, access_token)
        self.user_client.append(user_cls)
        return user_cls
    
    async def get_channel(self, channel_ids: list[str]) -> list[Channel]:
        result = await self.http.get_channel(channel_ids=",".join(channel_ids))
        return result.content.data


class UserClient:
    def __init__(
        self,
        parent: Client,
        access_token: AccessToken
    ):
        self.parent_client = parent
        self.loop = self.parent_client.loop
        self.http = self.parent_client.http

        self.access_token = access_token
        self._token_generated_at = datetime.datetime.now()
    
    @property
    def is_expired(self) -> bool:
        return (datetime.datetime.now() - self._token_generated_at).hours > self.access_token.expires_in
    
    async def refresh(self):
        refresh_token = await self.http.generate_access_token(
            grant_type="refresh_token",
            client_id=self.client_id,
            client_secret=self.client_secret,
            refresh_token=self.access_token.refresh_token,
        )
        self.access_token = refresh_token.data
        self._token_generated_at = datetime.datetime.now()
        return
    
    async def revoke(self):
        await self.http.revoke_access_token(
            client_id=self.client_id,
            client_secret=self.client_secret,
            token=self.access_token.access_token,
        )
        return
        