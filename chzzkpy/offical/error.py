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

from typing import Any, Literal

from ..error import ChzzkpyException
from ..error import LoginRequired
from ..error import BadRequestException
from ..error import UnauthorizedException
from ..error import ForbiddenException
from ..error import NotFoundException
from ..error import TooManyRequestsException
from ..error import HTTPException


class ChatConnectFailed(ChzzkpyException):
    def __init__(self, message: str):
        super(ChatConnectFailed, self).__init__(message)

    @classmethod
    def websocket_upgrade_failed(cls):
        return cls("WebSocket upgrade failed: no PONG packet")

    @classmethod
    def polling_connect_failed(cls, status: int):
        return cls(f"Unexpected status code {status} in connect polling")

    @classmethod
    def max_connection(cls):
        return cls("Maximum number of sessions allowed to connect has been exceeded.")


class ReceiveErrorPacket(ChzzkpyException):
    def __init__(self, transport: Literal["polling", "websocket"], data: Any):
        super().__init__(
            f"{transport} type of connection received packet with an error. "
            f" (data: {self.code})"
        )

        self.current_transport = transport
        self.data = data
