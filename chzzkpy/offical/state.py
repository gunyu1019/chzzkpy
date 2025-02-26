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

if TYPE_CHECKING:
    from .client import Client
    from .enums import EnginePacketType, SocketPacketType


class ConnectionState:
    def __init__(
        self,
        dispatch: Callable[..., Any],
        handler: dict[str, Callable[..., Any]]
    ):
        self.dispatch = dispatch
        self.handler = handler

    @staticmethod
    def parsable(
        engine_packet_type: EnginePacketType, 
        socket_packet_type: Optional[SocketPacketType] = None
    ):
        def decorator(func: Callable[..., Any]):
            func.__parsing_eventable__ = True
            func.__parsing_engine_packet__ = engine_packet_type
            func.__parsing_socket_packet__ = socket_packet_type
            return func

        return decorator

    def call_handler(self, key: str, *args: Any, **kwargs: Any):
        if key in self.handler:
            func = self.handler[key]
            func(*args, **kwargs)