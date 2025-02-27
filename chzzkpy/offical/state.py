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

import logging
import inspect
from typing import Callable, Any, TYPE_CHECKING, Optional

from .enums import EnginePacketType, SocketPacketType

if TYPE_CHECKING:
    from .client import Client


class ConnectionState:
    def __init__(
        self,
        dispatch: Callable[..., Any],
        handler: dict[str, Callable[..., Any]],
        debug_mode: bool = False
    ):
        self.dispatch = dispatch
        self.handler = handler
        self.gateway_parsers: dict[SocketPacketType | EnginePacketType, Callable[..., Any]] = dict()
        self.event_parsers: dict[str, Callable[..., Any]] = dict()

        self.debug_mode = debug_mode

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

    def call_handler(self, key: str, *args: Any, **kwargs: Any):
        if key in self.handler:
            func = self.handler[key]
            func(*args, **kwargs)

    @gateway_parsable(EnginePacketType.MESSAGE, SocketPacketType.EVENT)
    async def _handle_evnet(self, data: list[Any]):
        event = str(data[0]).lower()
        arguments = data[1:]

        print(event, arguments)

        event_func = self.event_parsers.get(event)
        if event_func is not None:
            await event_func(*arguments)

        if not self.debug_mode:
            return
        self.dispatch("socket_event", event,*data)
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
    async def _handle_system(self, data):
        print(data)
        return
    
    @event_parsable("chat")
    async def _handle_chat(self, data):
        print(data)
        return
    
    @event_parsable("donation")
    async def _handle_chat(self, data):
        print(data)
        return
