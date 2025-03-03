import asyncio

from ahttp_client import get, post, put, delete, Query, Path, BodyJson
from ahttp_client.extension import get_pydantic_response_model
from typing import Annotated, Any, Optional

from .access_token import AccessToken
from .profile import Profile
from ..base_model import Content
from ..http import ChzzkSession, ChzzkAPISession, NaverGameAPISession
from ..user import PartialUser


class ChzzkAPIChatSession(ChzzkAPISession):
    def __init__(self, loop: Optional[asyncio.AbstractEventLoop] = None):
        super().__init__(loop=loop)

    @get_pydantic_response_model()
    @post(
        "/manage/v1/channels/{channel_id}/temporary-restrict-users",
        directly_response=True,
    )
    @ChzzkSession.configuration(login_able=True, login_required=True)
    async def temporary_restrict(
        self,
        channel_id: Annotated[str, Path],
        chat_channel_id: Annotated[str, BodyJson.to_camel()],
        target_id: Annotated[str, BodyJson.to_camel()],
    ) -> Content[PartialUser]:
        pass

    @put(
        "/manage/v1/channels/{channel_id}/donations/mission/reject",
        directly_response=True,
    )
    @ChzzkSession.configuration(login_able=True, login_required=True)
    async def mission_request_reject(
        self,
        channel_id: Annotated[str, Path],
        mission_donation_id: Annotated[str, BodyJson.to_camel()],
    ) -> Content[dict[str, Any]]:
        pass

    @put(
        "/manage/v1/channels/{channel_id}/donations/mission/approve",
        directly_response=True,
    )
    @ChzzkSession.configuration(login_able=True, login_required=True)
    async def mission_request_approve(
        self,
        channel_id: Annotated[str, Path],
        mission_donation_id: Annotated[str, BodyJson.to_camel()],
    ) -> Content[dict[str, Any]]:
        pass


class NaverGameChatSession(NaverGameAPISession):
    def __init__(self, loop: Optional[asyncio.AbstractEventLoop] = None):
        super().__init__(loop=loop)

    @get_pydantic_response_model()
    @get("/nng_main/v1/chats/access-token", directly_response=True)
    @ChzzkSession.configuration(login_able=True)
    @Query.default_query("chatType", "STREAMING")
    async def chat_access_token(
        self, channel_id: Annotated[str, Query.to_camel()]
    ) -> Content[AccessToken]:
        pass

    @get_pydantic_response_model()
    @delete("/nng_main/v1/chats/notices", directly_response=True)
    @ChzzkSession.configuration(login_able=True, login_required=True)
    @Query.default_query("chatType", "STREAMING")
    async def delete_notice_message(
        self, channel_id: Annotated[str, BodyJson.to_camel()]
    ) -> Content[None]:
        pass

    @get_pydantic_response_model()
    @post("/nng_main/v1/chats/notices", directly_response=True)
    @ChzzkSession.configuration(login_able=True, login_required=True)
    @Query.default_query("chatType", "STREAMING")
    async def set_notice_message(
        self,
        channel_id: Annotated[str, BodyJson.to_camel()],
        extras: Annotated[str, BodyJson],
        message: Annotated[str, BodyJson],
        message_time: Annotated[int, BodyJson.to_camel()],
        message_user_id_hash: Annotated[int, BodyJson.to_camel()],
        streaming_channel_id: Annotated[int, BodyJson.to_camel()],
    ) -> Content[None]:
        return

    @get_pydantic_response_model()
    @post("/nng_main/v1/chats/blind-message", directly_response=True)
    @ChzzkSession.configuration(login_able=True, login_required=True)
    @Query.default_query("chatType", "STREAMING")
    async def blind_message(
        self,
        channel_id: Annotated[str, BodyJson.to_camel()],
        message: Annotated[str, BodyJson],
        message_time: Annotated[int, BodyJson.to_camel()],
        message_user_id_hash: Annotated[int, BodyJson.to_camel()],
        streaming_channel_id: Annotated[int, BodyJson.to_camel()],
    ) -> Content[None]:
        pass

    @get_pydantic_response_model()
    @get(
        "/nng_main/v1/chats/{chat_channel_id}/users/{user_id}/profile-card",
        directly_response=True,
    )
    @ChzzkSession.configuration(login_able=True, login_required=True)
    @Query.default_query("chatType", "STREAMING")
    async def profile_card(
        self,
        chat_channel_id: Annotated[str, Path],
        user_id: Annotated[str, Path],
    ) -> Content[Profile]:
        pass
