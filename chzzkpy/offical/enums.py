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

from enum import IntEnum, Enum
from typing import TypeVar, Any

E = TypeVar("E", bound="Enum")


class EnginePacketType(Enum):
    OPEN = 0
    CLOSE = 1
    PING = 2
    PONG = 3
    MESSAGE = 4
    UPGRADE = 5
    NOOP = 6


class SocketPacketType(Enum):
    CONNECT = 0
    DISCONNECT = 1
    EVENT = 2
    ACK = 3
    CONNECT_ERROR = 4
    BINARY_EVENT = 5
    BINARY_ACK = 6


class FollowingPeriod(IntEnum):
    NONE = 0
    FIVE_MINUTE = 5
    TEN_MINUTE = 10
    HALF_HOUR = 30
    HOUR = 60
    DAY = 1440
    WEEK = 10080
    MONTH = 43200


def get_enum(cls: type[E], val: Any) -> E:
    enum_val = [i for i in cls if i.value == val]
    if len(enum_val) == 0:
        return val
    return enum_val[0]
