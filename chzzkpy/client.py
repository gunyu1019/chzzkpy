"""MIT License

Copyright (c) 2024-2025 gunyu1019

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
import random

from functools import partial, wraps
from typing import Any, overload, TYPE_CHECKING
from yarl import URL

from .authorization import AccessToken
from .chat import ChatSetting
from .error import ChatConnectFailed, ForbiddenException, UnauthorizedException
from .flags import UserPermission
from .gateway import ChzzkGateway
from .http import ChzzkOpenAPISession
from .live import BrodecastSetting, Live
from .message import SentMessage, Message
from .oauth2 import ChzzkOAuth2Client
from .state import ConnectionState

if TYPE_CHECKING:
    from aiohttp.web import Response as webResponse
    from types import TracebackType
    from typing import Self, Literal, Optional, Callable, Coroutine

    from .base_model import SearchResult, ChannelSearchResult
    from .channel import Channel, ChannelPermission, FollowerInfo, SubscriberInfo
    from .category import Category
    from .enums import FollowingPeriod
    from .restriction import RestrictUser
    from .session import EventSubscribeMessage


class _LoopSentinel:
    __slots__ = ()

    def __getattr__(self, attr: str) -> None:
        msg = (
            "loop attribute cannot be accessed in non-async contexts. "
            "Consider using either an asynchronous main function and passing it to asyncio.run"
        )
        raise AttributeError(msg)


_log = logging.getLogger(__name__)

_SUBSCRIBED_EVENT_TIMEOUT = 10.0
# The wait before a reconnection attempt starts at the initial delay and doubles up to the maximum.
_RECONNECT_INITIAL_DELAY = 1.0
_RECONNECT_MAX_DELAY = 60.0


def _reconnect_delay(delay: float) -> float:
    """Returns how long to wait before a reconnection attempt: ``delay`` with jitter."""
    return random.uniform(delay / 2, delay)


def _consume_exception(future: asyncio.Future) -> None:
    # The exception is raised by a blocking connect() if one is waiting for it.
    if not future.cancelled():
        future.exception()


async def _connect_gateway(
    url: str, state: ConnectionState, loop: asyncio.AbstractEventLoop, ssl: bool = True
) -> ChzzkGateway:
    # The gateway doesn't close its aiohttp session; _close_gateway() does.
    session = aiohttp.ClientSession(loop=loop)
    try:
        return await ChzzkGateway.connect(
            url=url, state=state, loop=loop, session=session, ssl=ssl
        )
    except BaseException:
        await session.close()
        raise


async def _close_gateway(gateway: ChzzkGateway) -> None:
    try:
        await gateway.disconnect()
    finally:
        await gateway.session.close()


def _close_gateway_in_background(
    gateway: ChzzkGateway, tasks: set[asyncio.Task]
) -> asyncio.Task:
    """Closes ``gateway`` in a task that is kept in ``tasks`` until it's done.
    Cancelling whoever waits for the task doesn't stop the closing."""

    async def close():
        try:
            await _close_gateway(gateway)
        except Exception:
            _log.exception("Failed to close the connection.")

    task = gateway.loop.create_task(close())
    tasks.add(task)
    task.add_done_callback(tasks.discard)
    return task


async def _wait_closed(tasks: set[asyncio.Task]) -> None:
    """Waits until the gateways closed by :func:`_close_gateway_in_background` are closed."""
    if len(tasks) > 0:
        await asyncio.wait(set(tasks))


async def _wait_until_ready(ready: asyncio.Future, read_task: asyncio.Task) -> Any:
    """Waits until ``ready`` is done, unless the connection read by ``read_task`` ends first."""
    await asyncio.wait((ready, read_task), return_when=asyncio.FIRST_COMPLETED)
    if read_task.done():
        reason = None if read_task.cancelled() else read_task.exception()
        raise ChatConnectFailed.session_closed_before_ready() from reason
    return ready.result()


class _ClientSession:
    """A client session connected by :meth:`Client.connect`, kept across its reconnections."""

    def __init__(
        self, key: str, ssl: bool, reconnect: bool, loop: asyncio.AbstractEventLoop
    ):
        # The current session key, or the last one while reconnecting.
        self.key = key
        self.keys: list[str] = [key]
        self.ssl = ssl
        self.reconnect = reconnect
        # Events subscribed by user clients, subscribed again after reconnecting.
        self.subscriptions: dict[UserClient, UserPermission] = dict()
        self.reconnect_timer: Optional[asyncio.TimerHandle] = None
        self.reconnect_task: Optional[asyncio.Task] = None
        # Done when the session has ended for good.
        self.ended: asyncio.Future = loop.create_future()
        self.ended.add_done_callback(_consume_exception)


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
          It's called with the session key, again with the new key after reconnecting.
        * `on_disconnect`: Called with the session key when the connection of a session ends,
          either by itself (before reconnecting) or by `disconnect()`.
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
        if event_name not in self._extra_event.keys():
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

            for future, condition in listeners:
                # Drop listeners that were already resolved or cancelled (e.g. timed out).
                if future.done():
                    continue

                try:
                    result = condition(*args, **kwargs)
                except Exception as e:
                    future.set_exception(e)
                    continue

                if not result:
                    _new_listeners.append((future, condition))
                    continue

                match len(args):
                    case 0:
                        future.set_result(None)
                    case 1:
                        future.set_result(args[0])
                    case _:
                        future.set_result(args)
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

        # The connected client sessions by their current session key.
        self._gateway: dict[str, ChzzkGateway] = dict()
        # Client sessions that haven't ended, including the ones reconnecting.
        self._client_sessions: list[_ClientSession] = []
        # Every session key a client session has had, so that the old keys keep working.
        self._session_keys: dict[str, _ClientSession] = dict()
        # Number of connect() calls that haven't registered their session yet.
        self._connecting = 0
        self._gateway_ready = asyncio.Event()
        self._closing_tasks: set[asyncio.Task] = set()

        # On a client session, a "subscribed" event is attributed to the one pending subscription.
        self._subscription_lock = asyncio.Lock()
        self._pending_subscription: Optional[tuple[str, UserClient, asyncio.Future]] = (
            None
        )
        self._ambiguous_sessions: set[str] = set()

    def __variable_access_token(self, channel_id: str) -> Optional[AccessToken]:
        user_client = self.get_user_client_cached(channel_id)
        if user_client is not None:
            return user_client.access_token
        return None

    def _create_connection_state(self, ready: asyncio.Future) -> ConnectionState:
        def on_connected(session_id: str):
            if not ready.done():
                ready.set_result(session_id)

        def on_subscribed(message: EventSubscribeMessage):
            if ready.done():
                self.__on_subscribed(ready.result(), message.channel_id)

        return ConnectionState(
            dispatch=self.dispatch,
            handler={"connect": on_connected, "subscribed": on_subscribed},
            http=self.http,
            variable_access_token=self.__variable_access_token,
        )

    def __on_subscribed(self, session_id: str, channel_id: str):
        if self._pending_subscription is None:
            return
        pending_session_id, user_client, subscribed = self._pending_subscription
        if pending_session_id != session_id or subscribed.done():
            return
        if self.get_user_client_cached(channel_id) is not None:
            return
        user_client.channel_id = channel_id
        subscribed.set_result(None)

    def _client_session_of(self, session_id: str) -> Optional[_ClientSession]:
        """Returns the client session that has had ``session_id`` as its session key."""
        return self._session_keys.get(session_id)

    async def _subscribe_on_client_session(
        self,
        user_client: UserClient,
        permission: UserPermission,
        session_id: str,
        subscribed_events: Optional[UserPermission] = None,
    ):
        async with self._subscription_lock:
            subscribed = self.loop.create_future()
            learnable = session_id not in self._ambiguous_sessions
            if learnable:
                self._pending_subscription = (session_id, user_client, subscribed)
            gateway = None
            try:
                requested = await user_client._subscribe_events(
                    permission, session_id, subscribed_events
                )
                gateway = self._gateway.get(session_id)
                # The event may arrive before or after the response of the subscription.
                if learnable and requested and gateway is not None:
                    # Stops waiting at once when the connection of the session ends.
                    await asyncio.wait(
                        (subscribed, gateway._read_background_loop),
                        timeout=_SUBSCRIBED_EVENT_TIMEOUT,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
            finally:
                self._pending_subscription = None

            if (
                subscribed.done()
                or not requested
                or gateway is None
                or gateway._read_background_loop.done()
                or self._gateway.get(session_id) is not gateway
            ):
                return
            # A late "subscribed" event can't be told apart from another account's.
            self._ambiguous_sessions.add(session_id)
        _log.warning(
            "Failed to get the channel ID of a user client from the subscribed event "
            "of the client session. Events of its channel can't be replied to. "
            "(The access token requires the '유저 정보 조회' API scope.)"
        )

    async def __aenter__(self) -> Self:
        await self._async_setup_hook()
        return self

    async def __aexit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc_value: Optional[BaseException],
        traceback: Optional[TracebackType],
    ) -> None:
        try:
            await self.disconnect()
            for user_client in self.user_client:
                await user_client.disconnect()
        finally:
            if self.http is not None:
                await self.http.close()

    async def _async_setup_hook(self) -> None:
        if isinstance(self.loop, _LoopSentinel):
            self.loop = asyncio.get_running_loop()

        if asyncio.current_task(self.loop) is None:
            raise RuntimeError(
                "This loop should be defined in an asynchronous context."
            )

        self.http = ChzzkOpenAPISession(
            loop=self.loop, client_id=self.client_id, client_secret=self.client_secret
        )

    @staticmethod
    def initial_async_setup(func):
        @wraps(func)
        async def wrapper(self: Self, *args, **kwargs):
            if isinstance(self.loop, _LoopSentinel) or self.http is None:
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
    async def login(
        self,
        state: Optional[str] = None,
        redirect_url: Optional[str] = None,
        remote_host: str = "localhost",
        remote_port: int = 8080,
        remote_path: str = "/",
        success_response: Optional[webResponse] = None,
        ssl: bool = False,
    ) -> UserClient:
        """Get :class:`UserClient` instance with oauth2 login process.
        This :meth:`login` provides a convenient login method using the aiohttp web server.

        Concurrent logins that use the same remote_port run one after another:
        a login starts its web server after the previous one has finished.
        If the code exchange fails, the login ends with its exception instead of waiting forever.

        Parameters
        ----------
        state: Optional[str]
            A code used in the authentication process.
        redirect_url: Optional[str]
            A redirect_url used in the authentication process.
        remote_host : str
            A host url for the temporarily operated web server, default by localhost.
            If the public environment required, enter "0.0.0.0" value to this parameter.
        remote_port : int
            A port for the temporarily operated web server, default by 8080.
        remote_path : int
            A path for the temporarily operated web server, default by '/'.
        success_response : aiohttp.web.Response
            A content to be displayed on the website after successful login.
        ssl: bool
            Whether to use http(s) during opening the web browser.

        Raises
        ------
        ChzzkpyException
            The code exchange failed, e.g. the Chzzk server rejected the code.
            The exception is raised as it is, and the login must be run again.
        """
        remote_scheme = "https" if ssl else "http"
        oauth2_client = ChzzkOAuth2Client(
            self,
            remote_scheme=remote_scheme,
            remote_host=remote_host,
            remote_port=remote_port,
            remote_path=remote_path,
            success_response=success_response,
        )

        state = state or "chzzkpy_authorization"  # Temporatry Code
        access_token = await oauth2_client.process_oauth2(state, redirect_url)
        user_client = await self.get_user_client(access_token)
        return user_client

    @initial_async_setup
    async def refresh_access_token(self, refresh_token: str) -> AccessToken:
        """Regenerate an Access Token.
        The Access Token in chzzk follows Open Authorization 2.0 protocol,
         which means that access tokens expire after a certain amount of time.

        Parameters
        ----------
        refresh_token : str
            A refresh token to re-generated access token.
        """
        refresh_token = await self.http.generate_access_token(
            grant_type="refresh_token",
            client_id=self.client_id,
            client_secret=self.client_secret,
            refresh_token=refresh_token,
        )
        return refresh_token.content

    @initial_async_setup
    async def refresh_user_client(self, refresh_token: str) -> UserClient:
        """Get :class:`UserClient` instance with refresh_token.

        Parameters
        ----------
        refresh_token : str
            A refresh token to re-generated access token.
        """
        refreshed_access_token = await self.refresh_access_token(refresh_token)
        user_cls = UserClient(self, refreshed_access_token)
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
        """Waits until a client session connected by :meth:`connect` is ready.
        It returns immediately while a client session is connected,
        and waits again after all client sessions are disconnected by :meth:`disconnect`,
        their connections have ended or they're reconnecting.
        """
        await self._gateway_ready.wait()
        return

    @initial_async_setup
    async def connect(
        self,
        addition_connect: bool = False,
        ssl: bool = True,
        *,
        reconnect: bool = True,
    ) -> str:
        """Connect to session to handle donation or chatting
        A Client session can have more than one connection. (Maximum Connection: 10)

        When the connection of a client session ends by itself (e.g. the server closes it
        or the network drops), the session is reconnected automatically, unless reconnect is False.
        A reconnected session has a new session key, but the session key returned by this method
        (and every key the session has had) keeps working with :meth:`disconnect`,
        :meth:`UserClient.subscribe` and :meth:`UserClient.unsubscribe`.
        The events user clients have subscribed on the session are subscribed on the new session.
        A session being reconnected keeps counting toward the maximum.

        Parameters
        ----------
        addition_connect : Optional[bool]
            This parameter used for multiple connections, by default False
            If addition_connect is False, the connection is completed and a main task is blocked to wait for a response.
            The main task is released when the session is disconnected by :meth:`disconnect`,
            or when its connection ends and it isn't reconnected.
            With reconnect, it stays blocked while the session is reconnected.
            Cancelling the main task disconnects the session and raises :exc:`asyncio.CancelledError`.
            However addition_connect is True, a task waiting for a response is processed in the background.
        ssl : bool
            Whether to use a secure connection (wss/https) to the session server, by default True.
        reconnect : bool
            Whether to reconnect the session when its connection ends by itself, by default True.
            Reconnecting is retried, waiting from 1 second doubling up to 60 seconds (with jitter)
            between attempts, until it succeeds or the session is disconnected by :meth:`disconnect`.
            It stops when creating a new session is rejected (401 or 403).
            When reconnect is False, a session whose connection has ended is removed
            and no longer counts toward the maximum.

        Returns
        -------
        str
            Returns the session key of the client session, if the gateway connects succeeds.
            A session ID used by subscribe, unsubscribe and disconnect method.

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
            A connection that is still being established counts toward the maximum.
        ChatConnectFailed.session_closed_before_ready
            The connection was closed before the session became ready.
        UnauthorizedException
            Raised by a blocking connect when reconnecting stopped because creating a session
            was rejected (401). ForbiddenException is raised for 403.
        """
        # A connection being established takes a slot until its session is registered.
        if len(self._client_sessions) + self._connecting >= 10:
            raise ChatConnectFailed.max_connection()

        self._connecting += 1
        try:
            session_id, gateway, task = await self._open_client_session(ssl)
            session = _ClientSession(session_id, ssl, reconnect, self.loop)
            self._client_sessions.append(session)
            self._register_gateway(session, session_id, gateway)
        finally:
            self._connecting -= 1
        task.add_done_callback(partial(self._on_connection_closed, session_id, gateway))
        if not addition_connect:
            await self._wait_until_ended(session)
        return session_id

    async def _open_client_session(
        self, ssl: bool
    ) -> tuple[str, ChzzkGateway, asyncio.Task]:
        """Connects a new client session and waits until it's ready."""
        session_key = await self.http.generate_client_session()
        ready = self.loop.create_future()
        gateway = await _connect_gateway(
            session_key.content.url,
            self._create_connection_state(ready),
            self.loop,
            ssl=ssl,
        )
        task = gateway.read_in_background()
        try:
            session_id = await _wait_until_ready(ready, task)
        except BaseException:
            await asyncio.wait(
                (_close_gateway_in_background(gateway, self._closing_tasks),)
            )
            raise
        return session_id, gateway, task

    def _register_gateway(
        self, session: _ClientSession, session_id: str, gateway: ChzzkGateway
    ) -> None:
        session.key = session_id
        if session_id not in session.keys:
            session.keys.append(session_id)
        self._session_keys[session_id] = session
        self._gateway[session_id] = gateway
        self._gateway_ready.set()

    async def _wait_until_ended(self, session: _ClientSession) -> None:
        """Waits for a blocking connect() until the client session has ended for good."""
        try:
            # The read task isn't awaited: it would swallow the cancellation of the caller.
            await asyncio.wait((session.ended,))
        except asyncio.CancelledError:
            await self._disconnect_sessions([session])
            raise
        finally:
            await _wait_closed(self._closing_tasks)
        session.ended.result()

    def _on_connection_closed(
        self, session_id: str, gateway: ChzzkGateway, read_task: asyncio.Task
    ) -> None:
        """Called when the read task of a connected client session finishes.

        Unless :meth:`disconnect` has removed the session already, its connection
        ended by itself: its gateway is removed and closed, and the session is reconnected
        or, without reconnect, removed.
        """
        reason = None if read_task.cancelled() else read_task.exception()
        if self._gateway.get(session_id) is not gateway:
            return
        session = self._session_keys[session_id]
        _log.warning(
            "The connection of client session %s has ended.",
            session_id,
            exc_info=reason,
        )
        self._remove_gateway(session_id)
        _close_gateway_in_background(gateway, self._closing_tasks)
        self.dispatch("disconnect", session_id)
        if session.reconnect:
            # The first wait is a timer, not a task: a task made while the event loop
            # shuts down (it cancels the read tasks) would be left pending.
            session.reconnect_timer = self.loop.call_later(
                _reconnect_delay(_RECONNECT_INITIAL_DELAY),
                self._start_reconnecting,
                session,
            )
        else:
            self._forget_session(session)
            self._release_session(session, reason)

    def _start_reconnecting(self, session: _ClientSession) -> None:
        session.reconnect_timer = None
        session.reconnect_task = self.loop.create_task(self._reconnect(session))

    async def _reconnect(self, session: _ClientSession) -> None:
        """Connects a client session whose connection has ended by itself again."""
        previous_id = session.key
        delay = _RECONNECT_INITIAL_DELAY
        try:
            while True:
                try:
                    session_id, gateway, task = await self._reconnect_once(session)
                except (UnauthorizedException, ForbiddenException) as exc:
                    _log.error(
                        "Stopped reconnecting client session %s: creating a session was rejected.",
                        session.key,
                        exc_info=exc,
                    )
                    session.reconnect_task = None
                    self._forget_session(session)
                    self._release_session(session, exc)
                    return
                except Exception:
                    _log.warning(
                        "Failed to reconnect client session %s, retrying.",
                        session.key,
                        exc_info=True,
                    )
                    delay = min(delay * 2, _RECONNECT_MAX_DELAY)
                    await asyncio.sleep(_reconnect_delay(delay))
                    continue
                break
        except asyncio.CancelledError:
            if session.reconnect_task is asyncio.current_task():
                # Cancelled by something else than disconnect(): it can't reconnect any more.
                session.reconnect_task = None
                self._forget_session(session)
                self._release_session(session)
            raise
        session.reconnect_task = None
        task.add_done_callback(partial(self._on_connection_closed, session_id, gateway))
        _log.info(
            "Client session %s has been reconnected as %s.", previous_id, session_id
        )

    async def _reconnect_once(
        self, session: _ClientSession
    ) -> tuple[str, ChzzkGateway, asyncio.Task]:
        session_id, gateway, task = await self._open_client_session(session.ssl)
        self._register_gateway(session, session_id, gateway)
        try:
            await self._subscribe_again(session, session_id)
        except BaseException:
            # disconnect() closes the gateway itself if it has removed it.
            if self._gateway.get(session_id) is gateway:
                self._remove_gateway(session_id)
                _close_gateway_in_background(gateway, self._closing_tasks)
                self.dispatch("disconnect", session_id)
            raise
        return session_id, gateway, task

    async def _subscribe_again(self, session: _ClientSession, session_id: str) -> None:
        """Subscribes the events user clients have subscribed on a client session
        on its new session."""
        for user_client, permission in list(session.subscriptions.items()):
            if not permission:
                continue
            try:
                await user_client._subscribe_again(
                    UserPermission(permission.value), session_id
                )
            except (UnauthorizedException, ForbiddenException):
                # Other user clients mustn't lose their events because of one access token.
                _log.error(
                    "Failed to subscribe events of a user client again on client session %s. "
                    "Its events are no longer received on the session.",
                    session_id,
                    exc_info=True,
                )
                session.subscriptions.pop(user_client, None)

    def _remove_gateway(self, session_id: str) -> ChzzkGateway:
        gateway = self._gateway.pop(session_id)
        self._ambiguous_sessions.discard(session_id)
        if len(self._gateway) <= 0:
            self._gateway_ready.clear()
        return gateway

    def _forget_session(self, session: _ClientSession) -> bool:
        """Removes a client session that has ended for good, with every key it has had.
        Returns False if it has been removed already."""
        if session not in self._client_sessions:
            return False
        self._client_sessions.remove(session)
        for key in session.keys:
            if self._session_keys.get(key) is session:
                del self._session_keys[key]
        return True

    @staticmethod
    def _release_session(
        session: _ClientSession, reason: Optional[BaseException] = None
    ) -> None:
        """Releases a blocking connect() of the session, raising ``reason`` from it."""
        if session.ended.done():
            return
        if reason is None:
            session.ended.set_result(None)
        else:
            session.ended.set_exception(reason)

    def _stop_session(
        self, session: _ClientSession
    ) -> tuple[Optional[ChzzkGateway], Optional[asyncio.Task]]:
        """Removes a client session and stops reconnecting it.
        Returns its gateway to close and its cancelled reconnection to wait for."""
        if not self._forget_session(session):
            return None, None
        if session.reconnect_timer is not None:
            session.reconnect_timer.cancel()
            session.reconnect_timer = None
        reconnect_task, session.reconnect_task = session.reconnect_task, None
        if reconnect_task is not None:
            reconnect_task.cancel()
        gateway = self._gateway.get(session.key)
        if gateway is not None:
            self._remove_gateway(session.key)
            self.dispatch("disconnect", session.key)
        return gateway, reconnect_task

    async def _disconnect_sessions(self, sessions: list[_ClientSession]) -> None:
        stopped = [self._stop_session(session) for session in sessions]
        try:
            for gateway, reconnect_task in stopped:
                if gateway is not None:
                    await _close_gateway(gateway)
                if reconnect_task is not None:
                    # A cancelled reconnection closes the connection it was making.
                    await asyncio.wait((reconnect_task,))
        finally:
            for session in sessions:
                self._release_session(session)

    async def disconnect(self, session_id: Optional[str] = None):
        """Disconnect from session.
        It also stops reconnecting the session, even during an attempt.

        Parameters
        ----------
        session_id : Optional[str]
            A session ID returned by :meth:`connect` to disconnect from session.
            Any session key the session has had after reconnecting can be used too.
            When session parameter is empty, all client sessions are disconnected.
            A session whose connection has already ended is ignored.
        """
        if session_id is None:
            sessions = list(self._client_sessions)
        else:
            session = self._client_session_of(session_id)
            sessions = [] if session is None else [session]
        await self._disconnect_sessions(sessions)
        await _wait_closed(self._closing_tasks)


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
        self._connect_lock = asyncio.Lock()
        self._closing_tasks: set[asyncio.Task] = set()

        # Options of the connection made by connect().
        self._ssl = True
        self._reconnect = True
        self._reconnect_timer: Optional[asyncio.TimerHandle] = None
        self._reconnect_task: Optional[asyncio.Task] = None
        # Done when the connection made by connect() has ended for good.
        self._ended: Optional[asyncio.Future] = None
        # Events subscribed on the user session, subscribed again after reconnecting.
        self._subscribed_events = UserPermission()

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
        elapsed = datetime.datetime.now() - self._token_generated_at
        return elapsed.total_seconds() > self.access_token.expires_in

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
            client_id=self.parent_client.client_id,
            client_secret=self.parent_client.client_secret,
            refresh_token=self.access_token.refresh_token,
        )
        self._connection.access_token = self.access_token = refresh_token.content
        self._token_generated_at = datetime.datetime.now()
        return

    async def revoke(self):
        """Revoke the access token."""
        await self.http.revoke_access_token(
            client_id=self.parent_client.client_id,
            client_secret=self.parent_client.client_secret,
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
    async def connect(
        self,
        permission: UserPermission,
        addition_connect: bool = False,
        ssl: bool = True,
        *,
        reconnect: bool = True,
    ):
        """Connect to user session to handle donation or chatting
        If the user client is already connected, the previous connection is disconnected first.

        When the connection ends by itself (e.g. the server closes it or the network drops),
        the user client is reconnected automatically, unless reconnect is False.
        A reconnected user session has a new session ID, and the events this user client has
        subscribed on its user session (``permission`` and later :meth:`subscribe` and
        :meth:`unsubscribe` calls) are subscribed on it.
        While reconnecting, :attr:`is_connected` returns False.
        Without reconnect, the user client is reset, so :attr:`is_connected` returns False
        and it can connect again.

        Parameters
        ----------
        permission: UserPermission
            The permissions to receive, such as chat or donation.
            After connecting, permission is granted via subscription method.
        addition_connect : Optional[bool]
            This parameter used for multiple connections, by default False
            If addition_connect is False, the connection is completed and a main task is blocked to wait for a response.
            The main task is released when the user client is disconnected by :meth:`disconnect`
            (or connects again), or when the connection ends and it isn't reconnected.
            With reconnect, it stays blocked while the user client is reconnected.
            Cancelling the main task disconnects the user client and raises :exc:`asyncio.CancelledError`.
            However addition_connect is True, a task waiting for a response is processed in the background.
        ssl : bool
            Whether to use a secure connection (wss/https) to the session server, by default True.
        reconnect : bool
            Whether to reconnect when the connection ends by itself, by default True.
            Reconnecting is retried, waiting from 1 second doubling up to 60 seconds (with jitter)
            between attempts, until it succeeds or the user client is disconnected by :meth:`disconnect`.
            When the access token is rejected (401 or 403), it's refreshed once by :meth:`refresh`;
            if it's still rejected, reconnecting stops.

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
        ChatConnectFailed.session_closed_before_ready
            The connection was closed before the session became ready.
        UnauthorizedException
            Raised by a blocking connect when reconnecting stopped because the access token
            was rejected (401). ForbiddenException is raised for 403.
        """
        # The connections share the state of this user client, so they're made one at a time.
        async with self._connect_lock:
            await self.disconnect()
            self._ssl = ssl
            self._reconnect = reconnect
            self._subscribed_events = UserPermission()
            gateway, task = await self._open_connection()
            session_id = self._session_id
            ended = self._ended = self.loop.create_future()
            ended.add_done_callback(_consume_exception)
            try:
                await self.subscribe(permission, session_id)
            except asyncio.CancelledError:
                await self.disconnect()
                raise
            finally:
                # Attached once subscribed, so reconnecting knows the subscribed events.
                task.add_done_callback(partial(self._on_connection_closed, gateway))
        if not addition_connect:
            await self._wait_until_ended(ended)
        return session_id

    async def _open_connection(self) -> tuple[ChzzkGateway, asyncio.Task]:
        """Connects a new user session and waits until it's ready."""
        session_key = await self.http.generate_user_session(token=self.access_token)
        self._session_id = None
        self._gateway_ready.clear()
        gateway = self._gateway = await _connect_gateway(
            session_key.content.url, self._connection, self.loop, ssl=self._ssl
        )
        task = gateway.read_in_background()
        ready = self.loop.create_task(self._gateway_ready.wait())
        try:
            await _wait_until_ready(ready, task)
        except BaseException:
            await self._discard_gateway(gateway)
            raise
        finally:
            ready.cancel()
        self._gateway_id = gateway.session_id
        return gateway, task

    async def _discard_gateway(self, gateway: ChzzkGateway) -> None:
        """Closes a connection that failed to be set up, unless :meth:`disconnect` has
        closed it already."""
        if self._gateway is not gateway:
            return
        session_id = self._session_id
        self._remove_gateway()
        self._dispatch_disconnect(session_id)
        await asyncio.wait(
            (_close_gateway_in_background(gateway, self._closing_tasks),)
        )

    async def _wait_until_ended(self, ended: asyncio.Future) -> None:
        """Waits for a blocking connect() until the connection has ended for good."""
        try:
            # The read task isn't awaited: it would swallow the cancellation of the caller.
            await asyncio.wait((ended,))
        except asyncio.CancelledError:
            if self._ended is ended:
                await self.disconnect()
            raise
        finally:
            await _wait_closed(self._closing_tasks)
        ended.result()

    def _on_connection_closed(
        self, gateway: ChzzkGateway, read_task: asyncio.Task
    ) -> None:
        """Called when the read task of the connected user session finishes.

        Unless :meth:`disconnect` has removed the gateway already, its connection
        ended by itself: the user client is reset, the gateway is closed and,
        with reconnect, it's reconnected.
        """
        reason = None if read_task.cancelled() else read_task.exception()
        if self._gateway is not gateway:
            return
        session_id = self._session_id
        _log.warning(
            "The connection of user session %s has ended.",
            session_id,
            exc_info=reason,
        )
        self._remove_gateway()
        _close_gateway_in_background(gateway, self._closing_tasks)
        self._dispatch_disconnect(session_id)
        if self._reconnect:
            # The first wait is a timer, not a task: a task made while the event loop
            # shuts down (it cancels the read tasks) would be left pending.
            self._reconnect_timer = self.loop.call_later(
                _reconnect_delay(_RECONNECT_INITIAL_DELAY), self._start_reconnecting
            )
        else:
            self._end_connection(reason)

    def _start_reconnecting(self) -> None:
        self._reconnect_timer = None
        self._reconnect_task = self.loop.create_task(self._reconnect_session())

    async def _reconnect_session(self) -> None:
        """Connects the user session again after its connection has ended by itself."""
        delay = _RECONNECT_INITIAL_DELAY
        refreshed = False
        try:
            while True:
                try:
                    try:
                        gateway, task = await self._reconnect_once()
                    except (UnauthorizedException, ForbiddenException) as exc:
                        if refreshed:
                            raise
                        refreshed = True
                        try:
                            await self.refresh()
                        except Exception:
                            _log.warning(
                                "Failed to refresh the access token.", exc_info=True
                            )
                            raise exc
                        gateway, task = await self._reconnect_once()
                except (UnauthorizedException, ForbiddenException) as exc:
                    _log.error(
                        "Stopped reconnecting the user session: the access token was rejected.",
                        exc_info=exc,
                    )
                    self._reconnect_task = None
                    self._end_connection(exc)
                    return
                except Exception:
                    _log.warning(
                        "Failed to reconnect the user session, retrying.", exc_info=True
                    )
                    delay = min(delay * 2, _RECONNECT_MAX_DELAY)
                    await asyncio.sleep(_reconnect_delay(delay))
                    continue
                break
        except asyncio.CancelledError:
            if self._reconnect_task is asyncio.current_task():
                # Cancelled by something else than disconnect(): it can't reconnect any more.
                self._reconnect_task = None
                self._end_connection()
            raise
        self._reconnect_task = None
        task.add_done_callback(partial(self._on_connection_closed, gateway))
        _log.info("User session has been reconnected as %s.", self._session_id)

    async def _reconnect_once(self) -> tuple[ChzzkGateway, asyncio.Task]:
        gateway, task = await self._open_connection()
        try:
            await self._subscribe_events(
                UserPermission(self._subscribed_events.value), self._session_id
            )
        except BaseException:
            await self._discard_gateway(gateway)
            raise
        return gateway, task

    async def _subscribe_again(
        self, permission: UserPermission, session_id: str
    ) -> None:
        """Subscribes events again on a reconnected client session.
        A rejected access token is refreshed once."""
        try:
            await self.subscribe(permission, session_id)
        except (UnauthorizedException, ForbiddenException) as exc:
            try:
                await self.refresh()
            except Exception:
                _log.warning("Failed to refresh the access token.", exc_info=True)
                raise exc
            await self.subscribe(permission, session_id)

    def _dispatch_disconnect(self, session_id: Optional[str]) -> None:
        # A connection that never became ready had no session.
        if session_id is not None:
            self.dispatch("disconnect", session_id)

    def _end_connection(self, reason: Optional[BaseException] = None) -> None:
        """Releases a blocking connect(), raising ``reason`` from it."""
        ended, self._ended = self._ended, None
        if ended is None or ended.done():
            return
        if reason is None:
            ended.set_result(None)
        else:
            ended.set_exception(reason)

    def _remove_gateway(self) -> None:
        self._gateway = None
        self._gateway_id = None
        self._session_id = None
        self._gateway_ready.clear()

    async def disconnect(self):
        """Disconnect from session.
        It also stops reconnecting, even during an attempt."""
        if self._reconnect_timer is not None:
            self._reconnect_timer.cancel()
            self._reconnect_timer = None
        reconnect_task, self._reconnect_task = self._reconnect_task, None
        if reconnect_task is not None:
            reconnect_task.cancel()
        gateway = self._gateway
        try:
            if gateway is not None:
                session_id = self._session_id
                self._remove_gateway()
                self._dispatch_disconnect(session_id)
                await _close_gateway(gateway)
            if reconnect_task is not None:
                # A cancelled reconnection closes the connection it was making.
                await asyncio.wait((reconnect_task,))
        finally:
            self._end_connection()
        await _wait_closed(self._closing_tasks)

    def _subscriptions_of(
        self, session_id: str
    ) -> tuple[str, Optional[UserPermission]]:
        """Returns the current key of a session and the events this user client has
        subscribed on it, if they're subscribed again after reconnecting."""
        client_session = self.parent_client._client_session_of(session_id)
        if client_session is not None:
            subscribed_events = client_session.subscriptions.setdefault(
                self, UserPermission()
            )
            return client_session.key, subscribed_events
        if session_id == self._session_id:
            return session_id, self._subscribed_events
        return session_id, None

    @refreshable
    async def subscribe(
        self, permission: UserPermission, session_id: Optional[str] = None
    ):
        """Subcribe to events based on UserPermission.
        Subsribed events are recived in the session.

        If the channel ID of this client is unknown (without "유저 정보 조회" API Scope),
        it's obtained from the subscription event of the session.

        The subscribed events are subscribed again when the session is reconnected.

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

        session_id, subscribed_events = self._subscriptions_of(session_id)
        if self.channel_id is None and session_id != self._session_id:
            await self.parent_client._subscribe_on_client_session(
                self, permission, session_id, subscribed_events
            )
            return
        await self._subscribe_events(permission, session_id, subscribed_events)
        return

    async def _subscribe_events(
        self,
        permission: UserPermission,
        session_id: str,
        subscribed_events: Optional[UserPermission] = None,
    ) -> bool:
        requested = False
        for permission_name, condition in permission:
            if not condition:
                continue
            await self.http.subcribe_event(
                event=permission_name, session_key=session_id, token=self.access_token
            )
            if subscribed_events is not None:
                setattr(subscribed_events, permission_name, True)
            _log.debug(f"Subscribe {permission_name.upper()} Event")
            requested = True
        return requested

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
        session_id = session_id or self._session_id
        if session_id is None:
            raise TypeError(
                "A session_id is not filled. Connect to session using UserClient.connect() method or Client.connect()."
            )

        session_id, subscribed_events = self._subscriptions_of(session_id)
        for permission_name, condition in permission:
            if not condition:
                continue

            await self.http.unsubcribe_event(
                event=permission_name, session_key=session_id, token=self.access_token
            )
            if subscribed_events is not None:
                setattr(subscribed_events, permission_name, False)
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
        slow_mode: Literal[0, 3, 5, 10, 30, 60, 120, 300] = 0,
        emoji_mode: bool = False,
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
        slow_mode : Literal[0, 3, 5, 10, 30, 60, 120, 300]
            Set user chat interval (seconds)
        emoji_mode : bool
            Apply emoji mode
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
        slow_mode: Literal[0, 3, 5, 10, 30, 60, 120, 300] = 0,
        emoji_mode: bool = False,
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
            chat_slow_mode_sec=slow_mode,
            chat_emoji_mode=emoji_mode,
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

    @refreshable
    async def add_restrict_channel(self, user_id: str) -> None:
        """Add an user to restrict activity.

        Parameters
        ----------
        user_id : str
            A channel id of user to add restrict activity.
        """
        await self.http.add_restrict_user(
            token=self.access_token, target_channel_id=user_id
        )
        return

    @refreshable
    async def remove_restrict_channel(self, user_id: str) -> None:
        """Remove an user to restrict activity.

        Parameters
        ----------
        user_id : str
            A channel id of user to remove restrict activity.
        """
        await self.http.remove_restrict_user(
            token=self.access_token, target_channel_id=user_id
        )
        return

    @refreshable
    async def get_restriction(self, size: int = 20) -> SearchResult[RestrictUser]:
        """Get users with restricted activities.

        Parameters
        ----------
        size : Optional[int], optional
            A number of lives to load at once, by default 20
        """
        result = await self.http.get_restrict_users(token=self.access_token, size=size)
        data = result.content
        data._next_method = self.http.get_restrict_users
        data._next_method_key_argument = {"size": size}
        return data

    @refreshable
    async def get_channel_administrator(self) -> list[ChannelPermission]:
        """Get users who have channel management permission."""
        result = await self.http.get_channel_administrator(token=self.access_token)
        return result.content

    @refreshable
    async def get_followers(
        self, page: int = 0, size: int = 30
    ) -> ChannelSearchResult[FollowerInfo]:
        """Get followers for this channel.

        Parameters
        ----------
        size : Optional[int]
            A number of followers to load at once, by default 30
        page : Optional[int]
            A page number to load at once, by default 0
        """
        result = await self.http.get_channel_followers(
            token=self.access_token, size=size, page=page
        )
        data = result.content
        data._next_method = self.http.get_channel_followers
        data._next_method_key_argument = {"size": size, "token": self.access_token}
        return result.content

    @refreshable
    async def get_subscribers(
        self,
        page: int = 0,
        size: int = 30,
        sort: Literal["RECENT", "LONGER"] = "RECENT",
    ) -> ChannelSearchResult[SubscriberInfo]:
        """Get subscribers for this channel.

        Parameters
        ----------
        size : Optional[int]
            A number of subscribers to load at once, by default 30
        sort : Optional[Literal['RECENT', 'LONGER']]
            A method of sorting subscribers.
        page : Optional[int]
            A page number to load at once, by default 0
        """
        result = await self.http.get_channel_subscribers(
            token=self.access_token, size=size, sort=sort, page=page
        )
        data = result.content
        data._next_method = self.http.get_channel_subscribers
        data._next_method_key_argument = {
            "size": size,
            "sort": sort,
            "token": self.access_token,
        }
        return result.content

    @refreshable
    async def add_temporary_restrict(self, user_id: str, chat_channel_id: str) -> None:
        """Add a temporary ban to a user.

        Parameters
        ----------
        user_id : str
            A channel id of user to add temporary ban.
        chat_channel_id : str
            A id of current broadcast id to add temporary ban.
            Once the broadcast ends, a chat channel id will reset, allowing the user to chat again.
        """
        await self.http.add_temporary_restrict_user(
            token=self.access_token,
            target_channel_id=user_id,
            chat_channel_id=chat_channel_id,
        )
        return None

    @refreshable
    async def remove_temporary_restrict(
        self, user_id: str, chat_channel_id: str
    ) -> None:
        """Remove a temporary ban from a user.

        Parameters
        ----------
        user_id : str
            A channel id of user to remove temporary ban.
        chat_channel_id : str
            A id of current broadcast id to remove temporary ban.
            Once the broadcast ends, a chat channel id will reset, allowing the user to chat again.
        """
        await self.http.remove_temporary_restrict_user(
            token=self.access_token,
            target_channel_id=user_id,
            chat_channel_id=chat_channel_id,
        )
        return None

    @refreshable
    async def blind_message(
        self, chat_channel_id: str, user_id: str, message_time: datetime.datetime
    ) -> None:
        """Blind the message from the channel.

        Parameters
        ----------
        chat_channel_id : str
            A id of current broadcast to blind the message.
        user_id : str
            A channel id of user to blind the message.
        message_time : datetime.datetime
            A time of message to blind.
        """
        await self.http.blind_message(
            token=self.access_token,
            chat_channel_id=chat_channel_id,
            message_time=message_time.timestamp(),
            sender_channel_id=user_id,
        )
        return None
