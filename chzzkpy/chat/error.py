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

import aiohttp
from typing import Optional
from ..error import ChzzkpyException


class ChatConnectFailed(ChzzkpyException):
    def __init__(self, message: str):
        super(ChatConnectFailed, self).__init__(message)

    @classmethod
    def channel_is_null(cls, channel_id: str):
        return cls(
            f"Client can't retrieve the channel live-status. "
            f"Is the channel({channel_id}) broadcasting live?"
        )

    @classmethod
    def chat_channel_is_null(cls):
        return cls(
            "Missing Chat ID to connect to chat."
            "Make sure this client can connect to chat."
        )

    @classmethod
    def adult_channel(cls, channel_id: str):
        return cls(
            f"Adult verification is required to connect to chat on this channel({channel_id})."
            f"Please use login(), or proceed to adult verification."
        )


class ConnectionClosed(Exception):
    def __init__(
        self, socket: aiohttp.ClientWebSocketResponse, code: Optional[int] = None
    ):
        self.code: int = code or socket.close_code or -1
        self.reason: str = ""
        super().__init__(f"WebSocket closed with {self.code}")


class WebSocketClosure(Exception):
    pass


class ReconnectWebsocket(Exception):
    pass
