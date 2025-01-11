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
import json
import logging
import time
from typing import Any, Callable, Optional, Literal, TYPE_CHECKING

import aiohttp

from .enums import ChatCmd, get_enum, ChatType
from .error import ConnectionClosed, WebSocketClosure, ReconnectWebsocket

if TYPE_CHECKING:
    from typing_extensions import Self

    from .chat_client import ChatClient
    from .state import ConnectionState

_log = logging.getLogger(__name__)


class ChzzkWebSocket:
    def __init__(
        self,
        socket: aiohttp.ClientWebSocketResponse,
        loop: asyncio.AbstractEventLoop,
    ):
        self.socket: aiohttp.ClientWebSocketResponse = socket
        self.loop: asyncio.AbstractEventLoop = loop
        self.session_id: Optional[str] = None

        self._max_timeout: float = 60.0

        self._event_hook: dict[ChatCmd, Optional[Callable[..., Any]]] = {
            key: None for key in list(ChatCmd)
        }

    def set_hook(self, cmd: ChatCmd, coro_func: Callable[..., Any]):
        self._event_hook[cmd] = coro_func

    def remove_hook(self, cmd: ChatCmd):
        self._event_hook[cmd] = None

    async def close(self):
        self.session_id = None
        await self.socket.close()

    @classmethod
    async def new_session(
        cls,
        loop: asyncio.AbstractEventLoop,
        session: aiohttp.ClientSession,
        channel_id: str,
        session_id: Optional[str] = None,
    ) -> Self:
        server_id = abs(sum([ord(x) for x in channel_id])) % 9 + 1
        url = f"wss://kr-ss{server_id}.chat.naver.com/chat"
        socket: aiohttp.ClientWebSocketResponse = await session.ws_connect(url)

        websocket = cls(socket, loop)
        websocket.session_id = session_id
        return websocket

    @classmethod
    async def from_client(
        cls,
        client: "ChatClient",
        state: "ConnectionState",
        session_id: Optional[str] = None,
    ) -> Self:
        websocket = await cls.new_session(
            loop=client.loop,
            session=client.ws_session,
            channel_id=client.chat_channel_id,
            session_id=session_id,
        )
        for cmd, parsing_func in state.parsers.items():
            if parsing_func is None:
                continue
            websocket.set_hook(cmd, parsing_func)
        return websocket

    @property
    def default_body(self) -> dict[str, str]:
        return {"svcid": "game", "ver": "2"}

    def _can_handle_close(self, code: Optional[int] = None) -> bool:
        if code is None:
            code = self.socket.close_code
        return code != 1000

    async def poll_event(self):
        try:
            msg = await self.socket.receive(timeout=58.0)
            if msg.type is aiohttp.WSMsgType.TEXT:
                data = msg.json()
                await self.received_message(data)
            elif msg.type is aiohttp.WSMsgType.ERROR:
                _log.debug("Received error %s", msg)
                raise WebSocketClosure
            elif msg.type in (
                aiohttp.WSMsgType.CLOSED,
                aiohttp.WSMsgType.CLOSING,
                aiohttp.WSMsgType.CLOSE,
            ):
                _log.debug("Received %s", msg)
                raise WebSocketClosure
        except asyncio.TimeoutError:
            await self.send_ping()
            _log.debug("Timeout receiving packet. Send to ping for keep-alive")
        except WebSocketClosure:
            code = self.socket.close_code
            if self._can_handle_close(code):
                raise ReconnectWebsocket()
            else:
                raise ConnectionClosed(self.socket, code)

    async def received_message(self, data: dict[str, Any]) -> None:
        cmd: int = data["cmd"]
        body = data.get("bdy")

        # service_id = data['svcid']
        # channel_id = data['cid']
        # version = data['ver']
        # tid: ? = data.get('tid')

        cmd_type = get_enum(ChatCmd, cmd)
        _log.debug("Received Message: %s", data)

        if cmd_type == ChatCmd.CONNECTED:
            self.session_id = body["sid"]
        elif cmd_type == ChatCmd.PING:
            await self.send_pong()
            return

        func = self._event_hook.get(cmd_type)
        if func is not None:
            func(body)

    async def send(self, data: str) -> None:
        _log.debug("Sending data: %s", data)
        await self.socket.send_str(data)

    async def send_json(self, data: dict[str, Any]) -> None:
        _log.debug("Sending JSON: %s", json.dumps(data))
        await self.socket.send_json(data)

    async def send_pong(self):
        await self.send_json({"cmd": ChatCmd.PONG, "ver": 2})

    async def send_ping(self):
        await self.send_json({"cmd": ChatCmd.PING, "ver": 2})

    async def send_open(
        self,
        access_token: str,
        chat_channel_id: str,
        mode: Literal["SEND", "READ"],
        user_id: Optional[str] = None,
    ):
        data: dict[str, Any] = {
            "bdy": {
                "accTkn": access_token,
                "auth": mode,
                "devType": 2001,
                "uid": user_id,
            },
            "cid": chat_channel_id,
            "cmd": ChatCmd.CONNECT,
            "tid": 1,
        }
        data.update(self.default_body)
        await self.send_json(data)

    async def send_chat(self, message: str, chat_channel_id: str):
        extra: dict[str, Any] = {
            "chatType": "STREAMING",
            "emojis": "",
            "osType": "PC",
            "streamingChannelId": chat_channel_id,
        }

        data: dict[str, Any] = {
            "bdy": {
                "extras": json.dumps(extra),
                "msg": message,
                "msgTime": int(time.time() * 1000),
                "msgTypeCode": ChatType.TEXT,
            },
            "retry": False,
            "cmd": ChatCmd.SEND_CHAT,
            "sid": self.session_id,
            "cid": chat_channel_id,
            "tid": 3,
        }
        data.update(self.default_body)
        await self.send_json(data)

    async def request_recent_chat(self, count: int, chat_channel_id: str):
        data: dict[str, Any] = {
            "bdy": {"recentMessageCount": count},
            "cmd": ChatCmd.REQUEST_RECENT_CHAT,
            "sid": self.session_id,
            "cid": chat_channel_id,
            "tid": 2,
        }
        data.update(self.default_body)
        await self.send_json(data)
