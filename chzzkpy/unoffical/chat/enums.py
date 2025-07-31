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


class ChatCmd(IntEnum):
    PING = 0
    PONG = 10000
    CONNECT = 100
    CONNECTED = 10100
    REQUEST_RECENT_CHAT = 5101
    RECENT_CHAT = 15101
    EVENT = 93006
    CHAT = 93101
    SPECIAL_CHAT = 93102  # Donation / System Message
    KICK = 94005
    BLOCK = 94006
    BLIND = 94008
    NOTICE = 94010
    PENALTY = 94015
    SEND_CHAT = 3101


class ChatType(IntEnum):
    TEXT = 1
    IMAGE = 2
    STICKER = 3
    VIDEO = 4
    RICH = 5
    DONATION = 10
    SUBSCRIPTION = 11
    SUBSCRIPTION_GIFT = 12
    SYSTEM_MESSAGE = 30
    OPEN = 121


def get_enum(cls: type[E], val: Any) -> E:
    enum_val = [i for i in cls if i.value == val]
    if len(enum_val) == 0:
        return val
    return enum_val[0]
