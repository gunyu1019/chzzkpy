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
import aiohttp
import datetime
import logging

from functools import wraps
from typing import Any, Callable, Coroutine, Optional, TYPE_CHECKING
from yarl import URL

from .error import ForbiddenException
from .gateway import ChzzkGateway
from .http import ChzzkOpenAPISession
from .state import ConnectionState


if TYPE_CHECKING:
    from typing import Self

    from .authorization import AccessToken
    from .channel import Channel
    from .flags import UserPermission


class _LoopSentinel:
    __slots__ = ()

    def __getattr__(self, attr: str) -> None:
        msg = (
            'loop attribute cannot be accessed in non-async contexts. '
            'Consider using either an asynchronous main function and passing it to asyncio.run'
        )
        raise AttributeError(msg)
    

_log = logging.getLogger(__name__)


class BaseEventManager:
    def __init__(self, loop: asyncio.AbstractEventLoop):
        self.loop = loop
        self._listeners: dict[str, list[tuple[asyncio.Future, Callable[..., bool]]]] = dict()
        self._extra_event: dict[str, list[Callable[..., Coroutine[Any, Any, Any]]]] = dict()
    

    def wait_for(
        self,
        event: str,
        check: Optional[Callable[..., bool]] = None,
        timeout: Optional[float] = None,
    ):
        """Waits for a WebSocket event to be dispatched.

        Parameters
        ----------
        event : str
            The event name.
            For a list of events, read :method:`event`
        check : Optional[Callable[..., bool]],
            A predicate to check what to wait for. The arguments must meet the
            parameters of the event being waited for.
        timeout : Optional[float]
            The number of seconds to wait before timing out and raising
            :exc:`asyncio.TimeoutError`.

        """
        future = self.loop.create_future()

        if check is None:

            def _check(*_):
                return True

            check = _check
        event_name = event.lower()

        if event_name not in self._listeners.keys():
            self._listeners[event_name] = list()
        self._listeners[event_name].append((future, check))
        return asyncio.wait_for(future, timeout=timeout)

    def event(
        self, coro: Callable[..., Coroutine[Any, Any, Any]]
    ) -> Callable[..., Coroutine[Any, Any, Any]]:
        """A decorator that registers an event to listen to.
        The function must be corutine. Else client cause TypeError
        """
        if not asyncio.iscoroutinefunction(coro):
            raise TypeError("function must be a coroutine.")

        event_name = coro.__name__
        if event_name not in self._listeners.keys():
            self._extra_event[event_name] = list()
        self._extra_event[event_name].append(coro)
        return coro

    def dispatch(self, event: str, *args: Any, **kwargs) -> None:
        _log.debug("Dispatching event %s", event)
        method = "on_" + event

        # wait-for listeners
        if event in self._listeners.keys():
            listeners = self._listeners[event]
            _new_listeners = []

            for index, (future, condition) in enumerate(listeners):
                if future.cancelled():
                    continue

                try:
                    result = condition(*args, **kwargs)
                except Exception as e:
                    future.set_exception(e)
                    continue
                if result:
                    match len(args):
                        case 0:
                            future.set_result(None)
                        case 1:
                            future.set_result(args[0])
                        case _:
                            future.set_result(args)

                _new_listeners.append((future, condition))
            self._listeners[event] = _new_listeners

        # event-listener
        if method not in self._extra_event.keys():
            return

        for coroutine_function in self._extra_event[method]:
            self._schedule_event(coroutine_function, method, *args, **kwargs)

    async def _run_event(
        self,
        coro: Callable[..., Coroutine[Any, Any, Any]],
        event_name: str,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        try:
            await coro(*args, **kwargs)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            try:
                _log.exception("Ignoring exception in %s", event_name)
                self.dispatch("error", exc, *args, **kwargs)
            except asyncio.CancelledError:
                pass

    def _schedule_event(
        self,
        coro: Callable[..., Coroutine[Any, Any, Any]],
        event_name: str,
        *args: Any,
        **kwargs: Any,
    ) -> asyncio.Task:
        wrapped = self._run_event(coro, event_name, *args, **kwargs)
        # Schedules the task
        return self.loop.create_task(wrapped, name=f"chzzk.py: {event_name}")


class Client(BaseEventManager):
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        loop: Optional[asyncio.AbstractEventLoop] = None,
    ):
        self.loop = loop or _LoopSentinel()
        self.client_id = client_id
        self.client_secret = client_secret

        self.http: Optional[ChzzkOpenAPISession] = None
        self.user_client = []

        self._listeners: dict[str, list[tuple[asyncio.Future, Callable[..., bool]]]] = dict()
        self._extra_event: dict[str, list[Callable[..., Coroutine[Any, Any, Any]]]] = dict()

        self._ready = asyncio.Event()

        handler = {"connect": self._ready.set}
        self._connection = ConnectionState(
            dispatch=self.dispatch, handler=handler, http=self.http
        )
        self._gateway: Optional[ChzzkGateway] = None
    
    async def __aenter__(self) -> Self:
        await self._async_setup_hook()
        return self
    
    async def _async_setup_hook(self) -> None:
        self.loop = loop = asyncio.get_running_loop()
        self.http = ChzzkOpenAPISession(
            loop=loop,
            client_id=self.client_id,
            client_secret=self.client_secret
        )

    @staticmethod
    def initial_async_setup(func):
        @wraps(func)
        async def wrapper(self: Self, *args, **kwargs):
            if isinstance(self.loop, _LoopSentinel):
                await self._async_setup_hook()
            return await func(self, *args, **kwargs)
        return wrapper

    def generate_authorization_token_url(self, redirect_url: str, state: str) -> str:
        default_url = URL.build(scheme="https", authority="chzzk.naver.com", path="/account-interlock")
        default_url = default_url.with_query({
            "clientId": self.client_id,
            "redirectUri": redirect_url,
            "state": state
        })
        return default_url.geturl()

    @initial_async_setup
    async def generate_access_token(self, code: str, state: str) -> AccessToken:
        result = await self.http.generate_access_token(
            grant_type="authorization_code",
            client_id=self.client_id,
            client_secret=self.client_secret,
            code=code,
            state=state
        )
        return result.content

    async def generate_user_client(self, code: str, state: str) -> UserClient:
        access_token = await self.generate_access_token(code, state)
        user_cls = UserClient(self, access_token)
        try:
            await user_cls.fetch_self()
        except ForbiddenException:
            pass
        self.user_client.append(user_cls)
        return user_cls
    
    @initial_async_setup
    async def get_channel(self, channel_ids: list[str]) -> list[Channel]:
        result = await self.http.get_channel(channel_ids=",".join(channel_ids))
        return result.content.data
    
    @initial_async_setup
    async def get_category(self, query: str, size: Optional[int] = 20) -> list[Channel]:
        result = await self.http.get_category(query=query, size=size)
        return result.content.data


class UserClient:
    def __init__(
        self,
        parent: Client,
        access_token: AccessToken
    ):
        self.parent_client = parent
        self.dispatch = self.parent_client.dispatch
        self.loop = self.parent_client.loop
        self.http = self.parent_client.http

        self.access_token = access_token
        self._token_generated_at = datetime.datetime.now()

        self._gateway: Optional[ChzzkGateway] = None
        self._gateway_ready = asyncio.Event()
        self._gateway_id: Optional[str] = None
        self._session_id: Optional[str] = None

        self.channel_id: Optional[str] = None
        self.channel_name: Optional[str] = None

        handler = {"connect": self.__on_connected}
        self.state = ConnectionState(dispatch=self.dispatch, handler=handler, http=self.http)
    
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
    
    async def fetch_self(self) -> Channel:
        raw_user_self = await self.http.get_user_self(token=self.access_token)
        user_self = raw_user_self.content
        self.channel_id = user_self.id
        self.channel_name = user_self.name
        return user_self
    
    async def send_message(self, content: str) -> str:
        message_id = await self.http.create_message(content)
        return message_id.content
    
    @property
    def is_connected(self) -> bool:
        if self._gateway is None:
            return False
        return self._gateway.is_connected
    
    def __on_connected(self, session_id: str):
        self._session_id = session_id
        self._gateway_ready.set()
        return
    
    async def wait_until_connect(self):
        await self._gateway_ready.wait()
        return
        
    async def connect(self, permission: UserPermission, addition_connect: bool = False):
        session_key = await self.http.generate_user_session(token=self.access_token)
        self._gateway = await ChzzkGateway.connect(
            url=session_key.content.url,
            state=self.state,
            loop=self.loop,
            session=aiohttp.ClientSession(loop=self.loop)
        )
        task = self._gateway.read_in_background()
        await self._gateway_ready.wait()
        self._gateway_id = self._gateway.session_id
        for (permission_name, condition) in permission:
            if not condition:
                continue

            await self.http.subcribe_event(event=permission_name, session_key=self._session_id, token=self.access_token)
            _log.debug(f"Subscribe {permission_name.upper()} Event")
        if not addition_connect:
            await task
        return 

    async def disconnect(self):
        if self._gateway is None:
            return
        await self._gateway.disconnect()

        self._gateway = None
        self._gateway_id = None
        self._session_id = None
        self._gateway_ready.clear()
