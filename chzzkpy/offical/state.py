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
import inspect
import json
from typing import Callable, Any, TYPE_CHECKING, Optional

from .enums import EnginePacketType, SocketPacketType
from .message import Donation, Message

if TYPE_CHECKING:
    from .authorization import AccessToken
    from .http import ChzzkOpenAPISession


class ConnectionState:
    def __init__(
        self,
        dispatch: Callable[..., Any],
        handler: dict[str, Callable[..., Any]],
        http: ChzzkOpenAPISession,
        access_token: Optional[AccessToken] = None,
        debug_mode: bool = False
    ):
        self.dispatch = dispatch
        self.handler = handler
        self.http = http

        self.gateway_parsers: dict[SocketPacketType | EnginePacketType, Callable[..., Any]] = dict()
        self.event_parsers: dict[str, Callable[..., Any]] = dict()

        self.gateway_id: Optional[str] = None

        self.debug_mode = debug_mode
        self.access_token = access_token

        for _, func in inspect.getmembers(self):
            if hasattr(func, "__gateway_parsing__") and func.__gateway_parsing__:
                self.gateway_parsers[
                    func.__parsing_socket_packet__ or 
                    func.__parsing_engine_packet__
                ] = func

        for _, func in inspect.getmembers(self):
            if hasattr(func, "__event_parsing__"):
                self.event_parsers[
                    func.__event_parsing__
                ] = func

    @staticmethod
    def gateway_parsable(
        engine_packet_type: EnginePacketType, 
        socket_packet_type: Optional[SocketPacketType] = None
    ):
        def decorator(func: Callable[..., Any]):
            func.__gateway_parsing__ = True
            func.__parsing_engine_packet__ = engine_packet_type
            func.__parsing_socket_packet__ = socket_packet_type
            return func

        return decorator

    @staticmethod
    def event_parsable(
        event_name: str
    ):
        def decorator(func: Callable[..., Any]):
            func.__event_parsing__ = event_name
            return func

        return decorator

    async def call_handler(self, key: str, *args: Any, **kwargs: Any):
        if key not in self.handler:
            return 
        func = self.handler[key]

        if asyncio.iscoroutinefunction(func):
            await func(*args, **kwargs)
        else:
            func(*args, **kwargs)

    @gateway_parsable(EnginePacketType.MESSAGE, SocketPacketType.EVENT)
    async def _handle_evnet(self, data: list[Any]):
        event = str(data[0]).lower()
        arguments = data[1:]

        event_func = self.event_parsers.get(event)
        if event_func is not None:
            await event_func(*arguments)

        if not self.debug_mode:
            return
        self.dispatch("socket_event", event, *data)
        return
    
    @gateway_parsable(EnginePacketType.OPEN)
    async def _handle_eio_connect(self, open_packet: dict[str, Any]):
        sid = open_packet["sid"]
        self.gateway_id = sid
        if not self.debug_mode:
            return
        self.dispatch("engine_connect", sid)
        return
    
    @gateway_parsable(EnginePacketType.MESSAGE, SocketPacketType.CONNECT)
    async def _handle_connect(self, _):
        if not self.debug_mode:
            return
        self.dispatch("socket_connect")
        return
    
    @gateway_parsable(EnginePacketType.MESSAGE, SocketPacketType.DISCONNECT)
    async def _handle_disconnect(self, _):
        if not self.debug_mode:
            return
        self.dispatch("socket_disconnect")
        return
    
    @event_parsable("system")
    async def _handle_system(self, raw_data):
        data = json.loads(raw_data)
        event_type = data["type"]
        event_data = data["data"]

        if event_type == "connected":
            session_id = event_data["sessionKey"]
            self.dispatch("connect", session_id)
            await self.call_handler("connect", session_id)
        elif event_type == "subscribed":
            self.dispatch("permission_invoked")
        elif event_type == "unsubscribed":
            self.dispatch("permission_reinvoked")
        elif event_type == "revoked":
            self.dispatch("permission_reinvoked_force")
        return
    
    @event_parsable("chat")
    async def _handle_chat(self, raw_data):
        data = json.loads(raw_data)
        message = Message.model_validate(data)
        self.dispatch("chat", message)
        return
    
    @event_parsable("donation")
    async def _handle_donation(self, raw_data):
        data = json.loads(raw_data)
        message = Donation.model_validate(data)
        self.dispatch("donation", message)
        return
