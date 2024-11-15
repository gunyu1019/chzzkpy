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
import logging
from typing import Any, Optional, Callable, Coroutine, TYPE_CHECKING

import aiohttp

from .enums import ChatCmd
from .error import ChatConnectFailed
from .gateway import ChzzkWebSocket, ReconnectWebsocket
from .http import ChzzkChatSession
from .state import ConnectionState
from ..client import Client
from ..error import LoginRequired
from ..http import ChzzkAPISession

if TYPE_CHECKING:
    from .access_token import AccessToken
    from .message import ChatMessage
    from .recent_chat import RecentChat

_log = logging.getLogger(__name__)


class ChatClient(Client):
    """Represents a client to connect Chzzk (Naver Live Streaming).
    Addition, this class includes chat feature.
    """

    def __init__(
        self,
        channel_id: str,
        authorization_key: Optional[str] = None,
        session_key: Optional[str] = None,
        chat_channel_id: Optional[str] = None,
        loop: Optional[asyncio.AbstractEventLoop] = None,
    ):
        super().__init__(
            loop=loop, authorization_key=authorization_key, session_key=session_key
        )

        self.chat_channel_id: str = chat_channel_id
        self.channel_id: str = channel_id
        self.access_token: Optional[AccessToken] = None
        self.user_id: Optional[str] = None

        self.ws_session = aiohttp.ClientSession(loop=self.loop)

        self._listeners: dict[str, list[tuple[asyncio.Future, Callable[..., bool]]]] = (
            dict()
        )
        self._extra_event: dict[str, list[Callable[..., Coroutine[Any, Any, Any]]]] = (
            dict()
        )

        self._ready = asyncio.Event()

        handler = {ChatCmd.CONNECTED: self._ready.set}
        self._connection = ConnectionState(
            dispatch=self.dispatch, handler=handler, client=self
        )
        self._gateway: Optional[ChzzkWebSocket] = None

    def _session_initial_set(self):
        self._api_session = ChzzkAPISession(loop=self.loop)
        self._game_session = ChzzkChatSession(loop=self.loop)

    @property
    def is_connected(self) -> bool:
        """Specifies if the client successfully connected with chzzk."""
        return self._ready.is_set()

    def run(self, authorization_key: str = None, session_key: str = None) -> None:
        wrapper = self.start(authorization_key, session_key)
        try:
            self.loop.run_until_complete(wrapper)
        except KeyboardInterrupt:
            return

    async def start(self, authorization_key: str = None, session_key: str = None):
        try:
            if authorization_key is not None and session_key is not None:
                self.login(authorization_key=authorization_key, session_key=session_key)
            await self.connect()
        finally:
            await self.close()

    async def connect(self) -> None:
        if self.chat_channel_id is None:
            status = await self.live_status(channel_id=self.channel_id)
            if status is None:
                raise ChatConnectFailed(self.channel_id)
            self.chat_channel_id = status.chat_channel_id

        if self._game_session.has_login:
            user = await self.user()
            self.user_id = user.user_id_hash

        if self.access_token is None:
            await self._generate_access_token()

        await self.polling()

    async def close(self):
        """Close the connection to chzzk."""
        self._ready.clear()

        if self._gateway is not None:
            await self._gateway.socket.close()
        await self.ws_session.close()
        await super().close()

    async def polling(self) -> None:
        session_id: Optional[str] = None
        while not self.is_closed:
            try:
                self._gateway = await ChzzkWebSocket.from_client(
                    self, self._connection, session_id=session_id
                )

                # Initial Connection
                if session_id is None:
                    await self._gateway.send_open(
                        access_token=self.access_token.access_token,
                        chat_channel_id=self.chat_channel_id,
                        mode="READ" if self.user_id is None else "SEND",
                        user_id=self.user_id,
                    )
                    session_id = self._gateway.session_id

                while True:
                    await self._gateway.poll_event()
            except ReconnectWebsocket:
                self.dispatch("disconnect")
                continue

    # Event Handler
    async def wait_until_connected(self) -> None:
        """Waits until the client's internal cache is all ready."""
        await self._ready.wait()

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


        A list of events that the client can listen to.
        * `on_chat`: Called when a ChatMessage is created and sent.
        * `on_connect`: Called when the client is done preparing the data received from Chzzk.
        * `on_donation`: Called when a listener donates
        * `on_system_message`: Called when a system message is created and sent.
                            (Example. notice/blind message)
        * `on_recent_chat`: Called when a recent chat received.
                            This event called when `request_recent_chat` method called.
        * `on_pin` / `on_unpin`: Called when a message pinned or unpinned.
        * `on_blind`: Called when a message blocked.
        * `on_client_error`: Called when client cause exception.

        Example
        -------
        >>> @client.event
        ... async def on_chat(message: ChatMessage):
        ...     print(message.content)
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

    # API Method
    async def _generate_access_token(self) -> AccessToken:
        res = await self._game_session.chat_access_token(
            channel_id=self.chat_channel_id
        )
        self.access_token = res.content
        return self.access_token

    # Chat Method
    async def send_chat(self, message: str) -> None:
        """Send a message.

        Parameters
        ----------
        message : str
            Message to Broadcasters

        Raises
        ------
        RuntimeError
            Occurs when the client can't connect to a broadcaster's chat
        """
        if not self.is_connected:
            raise RuntimeError("Not connected to server. Please connect first.")

        if not self.user_id:
            raise LoginRequired()

        await self._gateway.send_chat(message, self.chat_channel_id)

    async def request_recent_chat(self, count: int = 50):
        """Send a request recent chat to chzzk.
        This method only makes a “request”.
        If you want to get the recent chats of participants, use the `history` method.

        Parameters
        ----------
        count : int, optional
            Number of messages to fetch from the most recent, by default 50

        Raises
        ------
        RuntimeError
            Occurs when the client can't connect to a broadcaster's chat
        """
        if not self.is_connected:
            raise RuntimeError("Not connected to server. Please connect first.")

        await self._gateway.request_recent_chat(count, self.chat_channel_id)

    async def history(self, count: int = 50) -> list[ChatMessage]:
        """Get messages the user has previously sent.

        Parameters
        ----------
        count : Optional[int]
            Number of messages to fetch from the most recent, by default 50

        Returns
        -------
        list[ChatMessage]
            Returns the user's most recently sent messages, in order of appearance
        """
        await self.request_recent_chat(count)
        recent_chat: RecentChat = await self.wait_for(
            "recent_chat", lambda x: len(x.message_list) <= count
        )
        return recent_chat.message_list

    async def set_notice_message(self, message: ChatMessage) -> None:
        """Set a pinned messsage.

        Parameters
        ----------
        message : ChatMessage
            A Chat to pin.
        """
        await self._game_session.set_notice_message(
            channel_id=self.chat_channel_id,
            extras=(
                message.extras.model_dump_json(by_alias=True)
                if message.extras is not None
                else "{}"
            ),
            message=message.content,
            message_time=int(message.created_time.timestamp() * 1000),
            message_user_id_hash=message.user_id,
            streaming_channel_id=message.extras.streaming_channel_id,
        )
        return

    async def delete_notice_message(self) -> None:
        """Delete a pinned message."""
        await self._game_session.delete_notice_message(channel_id=self.chat_channel_id)
        return

    async def blind_message(self, message: ChatMessage) -> None:
        """Blinds a chat.

        Parameters
        ----------
        message : ChatMessage
            A Chat to blind.
        """
        await self._game_session.blind_message(
            channel_id=self.chat_channel_id,
            message=message.content,
            message_time=int(message.created_time.timestamp() * 1000),
            message_user_id_hash=message.user_id,
            streaming_channel_id=message.extras.streaming_channel_id,
        )
        return
