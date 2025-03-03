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

import asyncio

from ahttp_client import request, get, post, put, delete, Path, Query, BodyJson
from ahttp_client.extension import get_pydantic_response_model
from typing import Annotated, Optional, Literal

from ..base_model import Content
from ..http import ChzzkSession
from ..user import PartialUser
from .chat_activity_count import ChatActivityCount
from .chat_rule import ChatRule
from .manage_search import (
    ManageResult,
    ManageFollower,
    ManageSubcriber,
    RestrictUser,
    UnrestrictRequest,
    ManageVideo,
)
from .prohibit_word import ProhibitWordResponse
from .stream import Stream


class ChzzkManageSession(ChzzkSession):
    def __init__(self, loop: Optional[asyncio.AbstractEventLoop] = None):
        super().__init__(base_url="https://api.chzzk.naver.com", loop=loop)

    @get_pydantic_response_model()
    @get(
        "/manage/v1/channels/{channel_id}/restrict-users/{target_id}/validate",
        directly_response=True,
    )
    @ChzzkSession.configuration(login_able=True, login_required=True)
    async def validate_restrict(
        self, channel_id: Annotated[str, Path], target_id: Annotated[str, Path]
    ) -> Content[str]:
        pass

    @get_pydantic_response_model()
    @post("/manage/v1/channels/{channel_id}/restrict-users", directly_response=True)
    @ChzzkSession.configuration(login_able=True, login_required=True)
    async def add_restrict(
        self,
        channel_id: Annotated[str, Path],
        target_id: Annotated[str, BodyJson.to_camel()],
        memo: Annotated[str, BodyJson] = "",
        restrict_days: Annotated[
            Literal[1, 3, 7, 15, 30, 90] | None, BodyJson.to_camel()
        ] = 7,
    ) -> Content[RestrictUser]:
        pass

    @get_pydantic_response_model()
    @request(
        "PATCH",
        "/manage/v1/channels/{channel_id}/restrict-users/{target_id}",
        directly_response=True,
    )
    @ChzzkSession.configuration(login_able=True, login_required=True)
    async def edit_restrict(
        self,
        channel_id: Annotated[str, Path],
        target_id: Annotated[str, Path],
        memo: Annotated[str, BodyJson] = "",
        restrict_days: Annotated[
            Literal[1, 3, 7, 15, 30, 90] | None, BodyJson.to_camel()
        ] = 7,
    ) -> Content[RestrictUser]:
        pass

    @get_pydantic_response_model()
    @delete(
        "/manage/v1/channels/{channel_id}/restrict-users/{target_id}",
        directly_response=True,
    )
    @ChzzkSession.configuration(login_able=True, login_required=True)
    async def remove_restrict(
        self, channel_id: Annotated[str, Path], target_id: Annotated[str, Path]
    ) -> Content[None]:
        pass

    @get_pydantic_response_model()
    @post("/manage/v1/channels/{channel_id}/streaming-roles", directly_response=True)
    @ChzzkSession.configuration(login_able=True, login_required=True)
    async def add_role(
        self,
        channel_id: Annotated[str, Path],
        target_id: Annotated[str, BodyJson.to_camel()],
        user_role_type: Annotated[
            Literal[
                "STREAMING_CHAT_MANAGER",
                "STREAMING_CHANNEL_MANAGER",
                "STREAMING_STATTLE_MANAGER",
            ],
            BodyJson.to_camel(),
        ],
    ) -> Content[PartialUser]:
        pass

    @get_pydantic_response_model()
    @delete(
        "/manage/v1/channels/{channel_id}/streaming-roles/{target_id}",
        directly_response=True,
    )
    @ChzzkSession.configuration(login_able=True, login_required=True)
    async def remove_role(
        self,
        channel_id: Annotated[str, Path],
        target_id: Annotated[str, Path],
    ) -> Content[None]:
        pass

    @get_pydantic_response_model()
    @get(
        "/manage/v1/channels/{channel_id}/chats/prohibit-words", directly_response=True
    )
    @ChzzkSession.configuration(login_able=True, login_required=True)
    async def get_prohibit_words(
        self,
        channel_id: Annotated[str, Path],
    ) -> Content[ProhibitWordResponse]:
        pass

    @get_pydantic_response_model()
    @post(
        "/manage/v1/channels/{channel_id}/chats/prohibit-words", directly_response=True
    )
    @ChzzkSession.configuration(login_able=True, login_required=True)
    async def add_prohibit_word(
        self,
        channel_id: Annotated[str, Path],
        prohibit_word: Annotated[str, BodyJson.to_camel()],
    ) -> Content[None]:
        pass

    @get_pydantic_response_model()
    @delete(
        "/manage/v1/channels/{channel_id}/chats/prohibit-words/{prohibit_word_number}",
        directly_response=True,
    )
    @ChzzkSession.configuration(login_able=True, login_required=True)
    async def remove_prohibit_word(
        self,
        channel_id: Annotated[str, Path],
        prohibit_word_number: Annotated[str, Path],
    ) -> Content[None]:
        pass

    @get_pydantic_response_model()
    @delete(
        "/manage/v1/channels/{channel_id}/chats/prohibit-words", directly_response=True
    )
    @ChzzkSession.configuration(login_able=True, login_required=True)
    async def remove_prohibit_word_all(
        self,
        channel_id: Annotated[str, Path],
    ) -> Content[None]:
        pass

    @get_pydantic_response_model()
    @put(
        "/manage/v1/channels/{channel_id}/chats/prohibit-words/{prohibit_word_number}",
        directly_response=True,
    )
    @ChzzkSession.configuration(login_able=True, login_required=True)
    async def edit_prohibit_word(
        self,
        channel_id: Annotated[str, Path],
        prohibit_word_number: Annotated[str, Path],
        prohibit_word: Annotated[str, BodyJson.to_camel()],
    ) -> Content[None]:
        pass

    @get_pydantic_response_model()
    @get("/manage/v1/channels/{channel_id}/streams", directly_response=True)
    @ChzzkSession.configuration(login_able=True, login_required=True)
    async def stream(
        self,
        channel_id: Annotated[str, Path],
    ) -> Content[Stream]:
        pass

    @get_pydantic_response_model()
    @get("/manage/v1/channels/{channel_id}/chat-rules", directly_response=True)
    @ChzzkSession.configuration(login_able=True, login_required=True)
    async def get_chat_rule(
        self,
        channel_id: Annotated[str, Path],
    ) -> Content[ChatRule]:
        pass

    @get_pydantic_response_model()
    @put("/manage/v1/channels/{channel_id}/chat-rules", directly_response=True)
    @ChzzkSession.configuration(login_able=True, login_required=True)
    async def set_chat_rule(
        self,
        channel_id: Annotated[str, Path],
        rule: Annotated[str, BodyJson.to_camel()],
    ) -> Content[None]:
        pass

    @get_pydantic_response_model()
    @get(
        "/manage/v1/channels/{channel_id}/users/{target_id}/chat-activity-count",
        directly_response=True,
    )
    @ChzzkSession.configuration(login_able=True, login_required=True)
    async def chat_activity_count(
        self,
        channel_id: Annotated[str, Path],
        target_id: Annotated[str, Path],
    ) -> Content[ChatActivityCount]:
        pass

    @get_pydantic_response_model()
    @get("/manage/v1/channels/{channel_id}/subscribers", directly_response=True)
    @ChzzkSession.configuration(login_able=True, login_required=True)
    async def subcribers(
        self,
        channel_id: Annotated[str, Path],
        page: Annotated[int, Query.to_camel()] = 0,
        size: Annotated[int, Query.to_camel()] = 50,
        sort_type: Annotated[
            Optional[Literal["RECENT", "LONGER"]], Query.to_camel()
        ] = "RECENT",
        publish_period: Annotated[Optional[Literal[1, 3, 6]], Query.to_camel()] = None,
        tier: Annotated[Optional[Literal["TIER_1", "TIER_2"]], Query.to_camel()] = None,
        nickname: Annotated[Optional[str], Query.to_camel()] = None,
    ) -> Content[ManageResult[ManageSubcriber]]:
        pass

    @get_pydantic_response_model()
    @get("/manage/v1/channels/{channel_id}/followers", directly_response=True)
    @ChzzkSession.configuration(login_able=True, login_required=True)
    async def followers(
        self,
        channel_id: Annotated[str, Path],
        page: Annotated[int, Query.to_camel()] = 0,
        size: Annotated[int, Query.to_camel()] = 50,
        sort_type: Annotated[
            Optional[Literal["RECENT", "LONGER"]], Query.to_camel()
        ] = "RECENT",
    ) -> Content[ManageResult[ManageFollower]]:
        pass

    @get_pydantic_response_model()
    @get("/manage/v1/channels/{channel_id}/restrict-users", directly_response=True)
    @ChzzkSession.configuration(login_able=True, login_required=True)
    async def restricts(
        self,
        channel_id: Annotated[str, Path],
        page: Annotated[int, Query.to_camel()] = 0,
        size: Annotated[int, Query.to_camel()] = 50,
        user_nickname: Annotated[Optional[str], Query.to_camel()] = None,
    ) -> Content[ManageResult[RestrictUser]]:
        pass

    @get_pydantic_response_model()
    @get(
        "/manage/v1/channels/{channel_id}/restrict-release-requests",
        directly_response=True,
    )
    @ChzzkSession.configuration(login_able=True, login_required=True)
    async def unrestrict_requests(
        self,
        channel_id: Annotated[str, Path],
        page: Annotated[int, Query.to_camel()] = 0,
        size: Annotated[int, Query.to_camel()] = 50,
        user_nickname: Annotated[Optional[str], Query.to_camel()] = "",
    ) -> Content[ManageResult[UnrestrictRequest]]:
        pass

    @get_pydantic_response_model()
    @get("/manage/v1/channels/{channel_id}/videos", directly_response=True)
    @ChzzkSession.configuration(login_able=True, login_required=True)
    async def videos(
        self,
        channel_id: Annotated[str, Path],
        video_type: Annotated[Literal["UPLOAD", "REPLAY"], Query.to_camel()],
        page: Annotated[int, Query.to_camel()] = 0,
        size: Annotated[int, Query.to_camel()] = 50,
    ) -> Content[ManageResult[ManageVideo]]:
        pass

    @get_pydantic_response_model()
    @put(
        "/manage/v1/channels/{channel_id}/restrict-release-requests/{request_number}/reject",
        directly_response=True,
    )
    @ChzzkSession.configuration(login_able=True, login_required=True)
    async def reject_unrestrict_request(
        self,
        channel_id: Annotated[str, Path],
        request_number: Annotated[int, Path],
        judgment: Annotated[str, BodyJson.to_camel()],
    ) -> Content[UnrestrictRequest]:
        pass
