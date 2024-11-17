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

from ahttp_client import get, post, put, delete, Path, Query
from ahttp_client.extension import get_pydantic_response_model
from typing import Annotated, Optional, Literal

from ..base_model import Content
from ..http import ChzzkSession
from ..user import ParticleUser
from .chat_activity_count import ChatAcitivityCount
from .chat_rule import ChatRule
from .lookup_manage import ManageResult, Follower, Subcriber
from .prohibit_word import ProhibitWordResponse
from .stream import Stream


class ChzzkManageSession(ChzzkSession):
    def __init__(self, loop: Optional[asyncio.AbstractEventLoop] = None):
        super().__init__(base_url="https://api.chzzk.naver.com", loop=loop)

        self.restrict.before_hook(self.query_to_json)
        self.set_role.before_hook(self.query_to_json)
        self.add_prohibit_word.before_hook(self.query_to_json)
        self.edit_prohibit_word.before_hook(self.query_to_json)
        self.set_chat_rule.before_hook(self.query_to_json)

    @get_pydantic_response_model()
    @post("/manage/v1/channels/{channel_id}/restrict-users", directory_response=True)
    @ChzzkSession.configuration(login_able=True, login_required=True)
    async def restrict(
        self,
        channel_id: Annotated[str, Path],
        target_id: Annotated[str, Query.to_camel()],
    ) -> Content[ParticleUser]:
        pass

    @get_pydantic_response_model()
    @delete(
        "/manage/v1/channels/{channel_id}/restrict-users/{target_id}",
        directory_response=True,
    )
    @ChzzkSession.configuration(login_able=True, login_required=True)
    async def remove_restrict(
        self, channel_id: Annotated[str, Path], target_id: Annotated[str, Path]
    ) -> Content[None]:
        pass

    @get_pydantic_response_model()
    @post("/manage/v1/channels/{channel_id}/streaming-roles", directory_response=True)
    @ChzzkSession.configuration(login_able=True, login_required=True)
    async def add_role(
        self,
        channel_id: Annotated[str, Path],
        target_id: Annotated[str, Query.to_camel()],
        user_role_type: Annotated[
            Literal["streaming_chat_manager", "streaming_channel_manager"],
            Query.to_camel(),
        ],
    ) -> Content[ParticleUser]:
        pass

    @get_pydantic_response_model()
    @delete(
        "/manage/v1/channels/{channel_id}/streaming-roles/{target_id}",
        directory_response=True,
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
        "/manage/v1/channels/{channel_id}/chats/prohibit-words", directory_response=True
    )
    @ChzzkSession.configuration(login_able=True, login_required=True)
    async def get_prohibit_words(
        self,
        channel_id: Annotated[str, Path],
    ) -> Content[ProhibitWordResponse]:
        pass

    @get_pydantic_response_model()
    @post(
        "/manage/v1/channels/{channel_id}/chats/prohibit-words", directory_response=True
    )
    @ChzzkSession.configuration(login_able=True, login_required=True)
    async def add_prohibit_word(
        self,
        channel_id: Annotated[str, Path],
        prohibit_word: Annotated[str, Query.to_camel()],
    ) -> Content[None]:
        pass

    @get_pydantic_response_model()
    @delete(
        "/manage/v1/channels/{channel_id}/chats/prohibit-words/{prohibit_word_number}",
        directory_response=True,
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
        "/manage/v1/channels/{channel_id}/chats/prohibit-words", directory_response=True
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
        directory_response=True,
    )
    @ChzzkSession.configuration(login_able=True, login_required=True)
    async def edit_prohibit_word(
        self,
        channel_id: Annotated[str, Path],
        prohibit_word_number: Annotated[str, Path],
        prohibit_word: Annotated[str, Query.to_camel()],
    ) -> Content[None]:
        pass

    @get_pydantic_response_model()
    @get("/manage/v1/channels/{channel_id}/streams", directory_response=True)
    @ChzzkSession.configuration(login_able=True, login_required=True)
    async def stream(
        self,
        channel_id: Annotated[str, Path],
    ) -> Content[Stream]:
        pass

    @get_pydantic_response_model()
    @get("/manage/v1/channels/{channel_id}/chat-rules", directory_response=True)
    @ChzzkSession.configuration(login_able=True, login_required=True)
    async def get_chat_rule(
        self,
        channel_id: Annotated[str, Path],
    ) -> Content[ChatRule]:
        pass

    @get_pydantic_response_model()
    @put("/manage/v1/channels/{channel_id}/chat-rules", directory_response=True)
    @ChzzkSession.configuration(login_able=True, login_required=True)
    async def set_chat_rule(
        self, channel_id: Annotated[str, Path], rule: Annotated[str, Query.to_camel()]
    ) -> Content[None]:
        pass

    @get_pydantic_response_model()
    @get(
        "/manage/v1/channels/{channel_id}/users/{target_id}/chat-activity-count",
        directory_response=True,
    )
    @ChzzkSession.configuration(login_able=True, login_required=True)
    async def chat_activity_count(
        self,
        channel_id: Annotated[str, Path],
        target_id: Annotated[str, Path],
    ) -> Content[ChatAcitivityCount]:
        pass

    @get_pydantic_response_model()
    @get("/manage/v1/channels/{channel_id}/subscribers", directory_response=True)
    @ChzzkSession.configuration(login_able=True, login_required=True)
    async def subcribers(
        self,
        channel_id: Annotated[str, Path],
        page: Annotated[int, Query.to_camel()] = 0,
        size: Annotated[int, Query.to_camel()] = 50,
        sort_type: Annotated[
            Optional[Literal["RECENT", "LONGER"]], Query.to_camel()
        ] = "RECENT",
        publish_period: Annotated[
            Optional[Literal["1", "3", "6"]], Query.to_camel()
        ] = None,
        tier: Annotated[Optional[Literal["TIER_1", "TIER_2"]], Query.to_camel()] = None,
        user_nickname: Annotated[Optional[str], Query.to_camel()] = None,
    ) -> Content[ManageResult[Subcriber]]:
        pass

    @get_pydantic_response_model()
    @get("/manage/v1/channels/{channel_id}/followers", directory_response=True)
    @ChzzkSession.configuration(login_able=True, login_required=True)
    async def followers(
        self,
        channel_id: Annotated[str, Path],
        page: Annotated[int, Query.to_camel()] = 0,
        size: Annotated[int, Query.to_camel()] = 50,
        sort_type: Annotated[
            Optional[Literal["RECENT", "LONGER"]], Query.to_camel()
        ] = "RECENT",
    ) -> Content[ManageResult[Follower]]:
        pass
