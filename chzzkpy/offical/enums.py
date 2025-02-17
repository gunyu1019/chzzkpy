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

from enum import StrEnum, Enum
from typing import TypeVar, Any

E = TypeVar("E", bound="Enum")


class APIScope(StrEnum):
    GET_STREAMKEY = "방송 스트림키 조회"
    GET_SETUP = "방송 설정 조회"
    GET_USER = "유저 조회"
    GET_CHAT_SETUP = "채팅 설정 조회"
    GET_DONATION = "후원 조회"
    GET_MESSAGE = "채팅 메시지 조회"
    SET_SETUP = "방송 설정 변경"
    SET_CHAT_SETUP = "채팅 설정 변경"
    WRITE_MESSAGE = "채팅 메시지 쓰기"
    WRITE_ANNOUNCEMENTS = "채팅 공지 쓰기"


def get_enum(cls: type[E], val: Any) -> E:
    enum_val = [i for i in cls if i.value == val]
    if len(enum_val) == 0:
        return val
    return enum_val[0]
