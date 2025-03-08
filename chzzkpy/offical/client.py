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
from typing import Any, overload, TYPE_CHECKING
from yarl import URL

from .authorization import AccessToken
from .chat import ChatSetting
from .error import ChatConnectFailed, ForbiddenException
from .gateway import ChzzkGateway
from .http import ChzzkOpenAPISession
from .live import BrodecastSetting, Live
from .message import SentMessage
from .state import ConnectionState


if TYPE_CHECKING:
    from typing import Self, Literal, Optional, Callable, Coroutine

    from .base_model import SearchResult
    from .channel import Channel
    from .category import Category
    from .enums import FollowingPeriod
    from .flags import UserPermission


class _LoopSentinel:
    __slots__ = ()

    def __getattr__(self, attr: str) -> None:
        msg = (
            "loop attribute cannot be accessed in non-async contexts. "
            "Consider using either an asynchronous main function and passing it to asyncio.run"
        )
        raise AttributeError(msg)


_log = logging.getLogger(__name__)


class BaseEventManager:
    def __init__(self, loop: asyncio.AbstractEventLoop):
        self.loop = loop
        self._listeners: dict[str, list[tuple[asyncio.Future, Callable[..., bool]]]] = (
            dict()
        )
        self._extra_event: dict[str, list[Callable[..., Coroutine[Any, Any, Any]]]] = (
            dict()
        )

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
        The function must be coroutine. Else client cause TypeError.

        A list of events that the client can listen to.
        * `on_chat`: Called when a Message is created and sent.
        * `on_connect`: Called when the client is done preparing the data received from Chzzk.
        * `on_donation`: Called when a listener donates
        * `on_error`: Called when event raise exception

        Example
        -------
        >>> @client.event
        ... async def on_chat(message: Message):
        ...     print(message.content)
        ...     await message.send("Reply Mesage")
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
    """Represents a client to connect Chzzk (Naver Live Streaming)."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        loop: Optional[asyncio.AbstractEventLoop] = None,
    ):
        super().__init__(loop)
        self.loop = loop or _LoopSentinel()
        self.client_id = client_id
        self.client_secret = client_secret

        self.http: Optional[ChzzkOpenAPISession] = None
        self.user_client: list[UserClient] = []

        handler = {"connect": lambda _: self._gateway_ready.set()}
        self._connection = ConnectionState(
            dispatch=self.dispatch,
            handler=handler,
            http=self.http,
            variable_access_token=self.__variable_access_token,
        )

        self._gateway: dict[str, ChzzkGateway] = dict()
        self._gateway_ready = asyncio.Event()

    def __variable_access_token(self, channel_id: str) -> Optional[AccessToken]:
        user_client = self.get_user_client_cached(channel_id)
        if user_client is not None:
            return user_client.access_token
        return

    async def __aenter__(self) -> Self:
        await self._async_setup_hook()
        return self

    async def _async_setup_hook(self) -> None:
        self.loop = loop = asyncio.get_running_loop()
        self.http = ChzzkOpenAPISession(
            loop=loop, client_id=self.client_id, client_secret=self.client_secret
        )
        self._connection.http = self.http

    @staticmethod
    def initial_async_setup(func):
        @wraps(func)
        async def wrapper(self: Self, *args, **kwargs):
            if isinstance(self.loop, _LoopSentinel):
                await self._async_setup_hook()
            return await func(self, *args, **kwargs)

        return wrapper

    def generate_authorization_token_url(self, redirect_url: str, state: str) -> str:
        """Get an url to generate chzzk access token.

        Parameters
        ----------
        redirect_url : str
            Redirect URL after login.
        state : str
            A state code to use in `state` parameter of :meth:`generate_access_token` method.
        """
        default_url = URL.build(
            scheme="https", authority="chzzk.naver.com", path="/account-interlock"
        )
        default_url = default_url.with_query(
            {"clientId": self.client_id, "redirectUri": redirect_url, "state": state}
        )
        return default_url.__str__()

    @initial_async_setup
    async def generate_access_token(self, code: str, state: str) -> AccessToken:
        """Generate an Access Token.
        An access token is used by features that require user authentication. (example. creating chat, receiving chat)

        Parameters
        ----------
        code : str
            A code received from :meth:`generate_authorization_token_url`.
        state : str
            A state code.
            This value must be the same as the state of :meth:`generate_authorization_token_url`.

        Returns
        -------
        AccessToken
            A instance that contain user authentic.
        """
        result = await self.http.generate_access_token(
            grant_type="authorization_code",
            client_id=self.client_id,
            client_secret=self.client_secret,
            code=code,
            state=state,
        )
        return result.content

    async def generate_user_client(self, code: str, state: str) -> UserClient:
        """Generate user client instance.

        Parameters
        ----------
        code : str
            A code received from :meth:`generate_authorization_token_url`.
        state : str
            A state code.
            This value must be the same as the state of :meth:`generate_authorization_token_url`.
        """
        access_token = await self.generate_access_token(code, state)
        user_cls = UserClient(self, access_token)
        try:
            await user_cls.fetch_self()
        except ForbiddenException:
            pass
        self.user_client.append(user_cls)
        return user_cls

    @initial_async_setup
    async def refresh_user_client(self, refresh_token: str) -> UserClient:
        """Get :class:`UserClient` instance with refresh_token.

        Parameters
        ----------
        refresh_token : str
            A refresh token to re-generated access token.
        """
        refresh_token = await self.http.generate_access_token(
            grant_type="refresh_token",
            client_id=self.client_id,
            client_secret=self.client_secret,
            refresh_token=self.access_token.refresh_token,
        )
        user_cls = UserClient(self, refresh_token)
        try:
            await user_cls.fetch_self()
        except ForbiddenException:
            pass
        self.user_client.append(user_cls)
        return user_cls

    @initial_async_setup
    async def get_user_client(self, access_token: AccessToken) -> UserClient:
        """Generate :class:`UserClient` with prepared access token.

        Parameters
        ----------
        access_token : AccessToken
            A prepared instance of access token.
        """
        user_cls = UserClient(self, access_token)
        try:
            await user_cls.fetch_self()
        except ForbiddenException:
            pass
        self.user_client.append(user_cls)
        return user_cls

    def get_user_client_cached(self, channel_id: str) -> Optional[UserClient]:
        """Get :class:`UserClient` as channel_id.
        The channel id of :class:`UserClient` can be obtained via the subscription event of session
        or when the client has the `유저 정보 조회` scope.

        If the channel Id of :class:`UserClient` is not filled, it can't found client.

        Parameters
        ----------
        channel_id : str
            A channel ID to get :class:`UserClient`
        """
        for user_client in self.user_client:
            if user_client.channel_id != channel_id:
                continue
            return user_client
        return

    @initial_async_setup
    async def get_channel(self, channel_ids: list[str]) -> list[Channel]:
        """Get channel information.

        Parameters
        ----------
        channel_ids : list[str]
            An unique ID of the channel to lookup.
        """
        result = await self.http.get_channel(channel_ids=",".join(channel_ids))
        return result.content.data

    @initial_async_setup
    async def get_category(
        self, query: str, size: Optional[int] = 20
    ) -> list[Category]:
        """Get category information

        Parameters
        ----------
        query : str
            A name of category.
        size : Optional[int], optional
            A number of categories to load at once, by default 20
        """
        result = await self.http.get_category(query=query, size=size)
        return result.content.data

    @initial_async_setup
    async def get_live(self, size: int = 20) -> SearchResult[Live]:
        """Get live information

        Parameters
        ----------
        size : Optional[int], optional
            A number of lives to load at once, by default 20
        """
        result = await self.http.get_lives(size=size)
        data = result.content
        data._next_method = self.http.get_lives
        data._next_method_key_argument = {"size": size}
        return data

    async def wait_until_connect(self):
        """Waits until the session connected."""
        await self._gateway_ready.wait()
        return

    @initial_async_setup
    async def connect(self, addition_connect: bool = False) -> str:
        """Connect to session to handle donation or chatting
        A Client session can have more than one connection. (Maximum Connection: 10)

        Parameters
        ----------
        addition_connect : Optional[bool]
            This parameter used for multiple connections, by default False
            If addition_connect is False, the connection is completed and a main task is blocked to wait for a response.
            However addition_connect is True, a task waiting for a response is processed in the background.

        Returns
        -------
        str
            Returns an unique session ID, if the gateway connects succeeds.
            A session ID used by subscribe, unsubscribe method.

        Warning
        -------
        If the main task is empty,
        as if addition_connect parameter used for all connections is true,
        all connections are aborted.

        Raises
        ------
        ChatConnectFailed.max_connection
            A Client Session can connect up to 10 sessions.
            When connection request more than 10 sessions, ChatConnectFailed exception raised.
        """
        if len(self._gateway.keys()) > 10:
            raise ChatConnectFailed.max_connection()

        session_key = await self.http.generate_client_session()
        gateway_cls = await ChzzkGateway.connect(
            url=session_key.content.url,
            state=self._connection,
            loop=self.loop,
            session=aiohttp.ClientSession(loop=self.loop),
        )
        task = gateway_cls.read_in_background()
        await self._gateway_ready.wait()
        self._gateway[gateway_cls.session_id] = gateway_cls
        self._gateway_ready.clear()
        if not addition_connect:
            await task
        return gateway_cls.session_id

    async def disconnect(self, session_id: Optional[str] = None):
        """Disconnect from session.

        Parameters
        ----------
        session_id : Optional[str]
            A session ID to disconnect from session.
            When session parameter is empty, all client sessions are disconnected.
        """
        if len(self._gateway) <= 0:
            return

        if session_id is not None:
            await self._gateway.disconnect()
            self._gateway.pop(session_id)
            return

        for gateway in self._gateway.values():
            await gateway.disconnect()
        self._gateway = dict()


class UserClient:
    """Represents a user client to provide feature that requires user authentication."""

    def __init__(self, parent: Client, access_token: AccessToken):
        self.parent_client = parent
        self.dispatch = self.parent_client.dispatch
        self.loop = self.parent_client.loop
        self.http = self.parent_client.http

        self.access_token = access_token
        self._token_generated_at = datetime.datetime.now()

        # Resolved issue in https://github.com/gunyu1019/chzzkpy/issues/66
        if not isinstance(self.access_token, AccessToken):
            raise TypeError(
                "An invalid type of parameter was entered. The access_token parameter must be AccessToken type."
            )

        self._gateway: Optional[ChzzkGateway] = None
        self._gateway_ready = asyncio.Event()
        self._gateway_id: Optional[str] = None
        self._session_id: Optional[str] = None

        self.channel_id: Optional[str] = None
        self.channel_name: Optional[str] = None

        handler = {
            "connect": self.__on_connected,
            "channel_id_invoked": self.__on_channel_id_invoked,
        }
        self._connection = ConnectionState(
            dispatch=self.dispatch,
            handler=handler,
            http=self.http,
            access_token=self.access_token,
        )

    def __on_connected(self, session_id: str):
        self._session_id = session_id
        self._gateway_ready.set()
        return

    def __on_channel_id_invoked(self, channel_id: str):
        self.channel_id = channel_id

    @property
    def is_expired(self) -> bool:
        """An access token for user expires after a certain amount of time.
        Returns status that an access token had been expired."""
        return (
            datetime.datetime.now() - self._token_generated_at
        ).hours > self.access_token.expires_in

    @staticmethod
    def refreshable(func):
        @wraps(func)
        async def wrapper(self: Self, *args, **kwargs):
            remaining_expired_time = datetime.datetime.now() - self._token_generated_at
            if remaining_expired_time.days > 0:
                await self.refresh()
            return await func(self, *args, **kwargs)

        return wrapper

    async def refresh(self):
        """Refresh the access token."""
        refresh_token = await self.http.generate_access_token(
            grant_type="refresh_token",
            client_id=self.client_id,
            client_secret=self.client_secret,
            refresh_token=self.access_token.refresh_token,
        )
        self._connection.access_token = self.access_token = refresh_token.data
        self._token_generated_at = datetime.datetime.now()
        return

    async def revoke(self):
        """Revoke the access token."""
        await self.http.revoke_access_token(
            client_id=self.client_id,
            client_secret=self.client_secret,
            token=self.access_token.access_token,
        )
        return

    @refreshable
    async def fetch_self(self) -> Channel:
        """Get channel based on access token.
        This method required "유저 정보 조회" API Scope on the access token.

        Returns
        -------
        Channel
            A channel based on the access token.
        """
        raw_user_self = await self.http.get_user_self(token=self.access_token)
        user_self = raw_user_self.content
        self.channel_id = user_self.id
        self.channel_name = user_self.name
        return user_self

    @refreshable
    async def send_message(self, content: str) -> SentMessage:
        """Send the message to channel
        This method required "채팅 메시지 전송" API Scope on the access token.

        Parameters
        ----------
        content : str
            A content of message.
        """
        response = await self.http.create_message(
            token=self.access_token, message=content
        )
        message_id = response.content["messageId"]
        message = SentMessage(id=message_id, content=content)
        message._access_token = self.access_token
        message._state = self._connection
        return message

    @refreshable
    async def send_announcement(self, content: str):
        """Send the announcement to channel
        This method required "채팅 공지 등록" API Scope on the access token.

        Parameters
        ----------
        content : str
            A content of announcement.
        """
        await self.http.create_notice(token=self.access_token, message=content)
        return

    @property
    def is_connected(self) -> bool:
        """Returns the gateway had been connected."""
        if self._gateway is None:
            return False
        return self._gateway.is_connected

    async def wait_until_connect(self):
        """Waits until the session connected."""
        await self._gateway_ready.wait()
        return

    @refreshable
    async def connect(self, permission: UserPermission, addition_connect: bool = False):
        """Connect to user session to handle donation or chatting

        Parameters
        ----------
        permission: UserPermission
            The permissions to receive, such as chat or donation.
            After connecting, permission is granted via subscription method.
        addition_connect : Optional[bool]
            This parameter used for multiple connections, by default False
            If addition_connect is False, the connection is completed and a main task is blocked to wait for a response.
            However addition_connect is True, a task waiting for a response is processed in the background.

        Returns
        -------
        str
            Returns an unique session ID, if the gateway connects succeeds.
            A session ID used by subscribe, unsubscribe method.

        Warning
        -------
        If the main task is empty,
        as if addition_connect parameter used for all connections is true,
        all connections are aborted.
        """
        session_key = await self.http.generate_user_session(token=self.access_token)
        self._gateway = await ChzzkGateway.connect(
            url=session_key.content.url,
            state=self._connection,
            loop=self.loop,
            session=aiohttp.ClientSession(loop=self.loop),
        )
        task = self._gateway.read_in_background()
        await self._gateway_ready.wait()
        self._gateway_id = self._gateway.session_id
        await self.subscribe(permission, self._session_id)
        if not addition_connect:
            await task
        return self._session_id

    async def disconnect(self):
        """Disconnect from session."""
        if self._gateway is None:
            return
        await self._gateway.disconnect()

        self._gateway = None
        self._gateway_id = None
        self._session_id = None
        self._gateway_ready.clear()

    @refreshable
    async def subscribe(
        self, permission: UserPermission, session_id: Optional[str] = None
    ):
        """Subcribe to events based on UserPermission.
        Subsribed events are recived in the session.

        Parameters
        ----------
        permission : UserPermission
            The session subscribed evnet.
        session_id : Optional[str]
            ID of the session to receive event, by default None
            The session ID is provided as a parameter in `on_connect` event
        """
        session_id = session_id or self._session_id
        if session_id is None:
            raise TypeError(
                "A session_id is not filled. Connect to session using UserClient.connect() method or Client.connect()."
            )

        for permission_name, condition in permission:
            if not condition:
                continue
            await self.http.subcribe_event(
                event=permission_name, session_key=session_id, token=self.access_token
            )
            _log.debug(f"Subscribe {permission_name.upper()} Event")
        return

    @refreshable
    async def unsubscribe(
        self, permission: UserPermission, session_id: Optional[str] = None
    ):
        """Unsubcribe to events based on UserPermission.
        The events specified by UserPermission are no longer received.

        Parameters
        ----------
        permission : UserPermission
            The session unsubscribed evnet.
        session_id : Optional[str]
            ID of the session to block event, by default None
        """
        session_id = session_id or self._gateway_id
        if session_id is None:
            raise TypeError(
                "A session_id is not filled. Connect to session using UserClient.connect() method or Client.connect()."
            )

        for permission_name, condition in permission:
            if not condition:
                continue

            await self.http.unsubcribe_event(
                event=permission_name, session_key=session_id, token=self.access_token
            )
            _log.debug(f"Unsubscribe {permission_name.upper()} Event")
        return

    @refreshable
    async def get_chat_setting(self) -> ChatSetting:
        """Get the chat settings."""
        raw_chat_setting = await self.http.get_chat_setting(token=self.access_token)
        return raw_chat_setting.content

    @overload
    async def set_chat_setting(self, instance: ChatSetting) -> None:
        """Set the chat settings.

        Parameters
        ----------
        instance : ChatSetting
            A instance of chat setting.
        """
        ...

    @overload
    async def set_chat_setting(
        self,
        chat_available_condition: Literal["NONE", "REAL_NAME"],
        chat_available_group: Literal["ALL", "FOLLOWER", "MANAGER", "SUBSCRIBER"],
        min_follower_minute: FollowingPeriod,
        allow_subscriber_in_follower_mode: bool,
    ) -> None:
        """Set the chat settings.

        Parameters
        ----------
        chat_available_condition : Literal['NONE', 'REAL_NAME']
            Allow only users who have been authenticated.
        chat_available_group : Literal['ALL', 'FOLLOWER', 'MANAGER', 'SUBSCRIBER']
             Set the types of chat that are allowed.
        min_follower_minute : FollowingPeriod
            Allow users who follow channel to make chat available after a specified amount of time.
        allow_subscriber_in_follower_mode : bool
            Set whether subscriber will follow the minimum follow time.
        """
        ...

    @refreshable
    async def set_chat_setting(
        self,
        instance: ChatSetting = None,
        chat_available_condition: Literal["NONE", "REAL_NAME"] = None,
        chat_available_group: Literal[
            "ALL", "FOLLOWER", "MANAGER", "SUBSCRIBER"
        ] = None,
        min_follower_minute: FollowingPeriod = None,
        allow_subscriber_in_follower_mode: bool = None,
    ) -> None:
        if instance is not None:
            await self.http.set_chat_setting(
                token=self.access_token,
                chat_available_condition=instance.chat_available_condition,
                chat_available_group=instance.chat_available_group,
                min_follower_minute=instance.min_follower_minute,
                allow_subscriber_in_follower_mode=instance.allow_subscriber_in_follower_mode,
            )
            return
        await self.http.set_chat_setting(
            token=self.access_token,
            chat_available_condition=chat_available_condition,
            chat_available_group=chat_available_group,
            min_follower_minute=min_follower_minute,
            allow_subscriber_in_follower_mode=allow_subscriber_in_follower_mode,
        )
        return

    @refreshable
    async def get_live_setting(self) -> BrodecastSetting:
        """Get the live settings."""
        raw_live_setting = await self.http.get_live_setting(token=self.access_token)
        return raw_live_setting.content

    @overload
    async def set_live_setting(self, instance: BrodecastSetting) -> None:
        """Set the live settings.

        Parameters
        ----------
        instance : BrodecastSetting
            A instance of live setting.
        """
        ...

    @overload
    async def set_live_setting(
        self,
        title: Optional[str] = None,
        category: Optional[Category] = None,
        tags: Optional[list[str]] = None,
    ) -> None:
        """Set the live settings.

        Parameters
        ----------
        title : Optional[str]
            The name of brodecast.
        category : Optional[Category]
            The category of brodecast.
        tags : Optional[list[str]]
            The tags of brodecast.
        """
        ...

    @refreshable
    async def set_live_setting(
        self,
        instance: BrodecastSetting = None,
        title: Optional[str] = None,
        category: Optional[Category] = None,
        tags: Optional[list[str]] = None,
    ) -> None:
        if instance is not None:
            await self.http.set_live_setting(
                token=self.access_token,
                default_live_title=instance.title,
                category_id=instance.category.id,
                category_type=instance.category.type,
                tags=instance.tags,
            )
            return
        await self.http.set_live_setting(
            token=self.access_token,
            default_live_title=title,
            category_id=category.id if category is not None else None,
            category_type=category.type if category is not None else None,
            tags=tags,
        )
        return

    @refreshable
    async def get_stream_key(self) -> str:
        """Get the stream key to brodecast"""
        stream_key = await self.http.get_stream_key(token=self.access_token)
        return stream_key.content["streamKey"]
