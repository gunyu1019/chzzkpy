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

import datetime

from typing import Optional, Literal
from pydantic import AliasChoices, Field

from ..base_model import ChzzkModel


class DonationRank(ChzzkModel):
    user_id_hash: str
    nickname: str = Field(validation_alias=AliasChoices("nickname", "nickName"))
    verified_mark: bool
    donation_amount: int
    ranking: int


class BaseDonation(ChzzkModel):
    is_anonymous: bool = True
    pay_type: str
    pay_amount: int = 0
    donation_type: str
    weekly_rank_list: Optional[list[DonationRank]] = Field(default_factory=list)
    donation_user_weekly_rank: Optional[DonationRank] = None
    verified_mark: Optional[bool] = False


class ChatDonation(BaseDonation):
    donation_type: Literal["CHAT"]


class VideoDonation(BaseDonation):
    donation_type: Literal["VIDEO"]


class MissionDonation(BaseDonation):
    donation_type: Literal["MISSION"]
    mission_donation_id: Optional[str] = None
    mission_donation_type: Optional[str] = None  # ALONE / GROUP
    mission_text: str
    total_pay_amount: int

    donation_id: Optional[str]  # ???
    participation_count: int

    user_id_hash: Optional[str] = None
    nickname: Optional[str] = None
    anonymous_token: Optional[str] = None

    mission_created_time: datetime.datetime
    mission_start_time: Optional[datetime.datetime] = None
    mission_end_time: Optional[datetime.datetime] = None
    duration_time: int = 0

    status: str | Literal["PENDING", "REJECTED", "APPROVED", "COMPLETED"] = None
    success: bool = False


class MissionParticipationDonation(BaseDonation):
    donation_type: Literal["MISSION_PARTICIPATION"]
    mission_donation_id: Optional[str] = None
    mission_donation_type: Optional[str] = None  # PARTICIPATION
    mission_text: str
    total_pay_amount: int

    related_mission_donation_id: str
    donation_id: Optional[str]  # ???
    participation_count: int

    user_id_hash: Optional[str] = None
    nickname: Optional[str] = None
    anonymous_token: Optional[str] = None

    status: str | Literal["PENDING", "REJECTED", "APPROVED", "COMPLETED"] = None
    success: bool = False
