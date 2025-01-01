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

from typing import Any, Optional
from pydantic import computed_field, Field, PrivateAttr

from ..base_model import ChzzkModel
from ..user import UserRole, PartialUser


class Badge(ChzzkModel):
    name: Optional[str] = None
    image_url: Optional[str] = None


class StreamingProperty(ChzzkModel):
    _following_dt: Optional[dict[str, str]] = PrivateAttr(default=None)
    _real_time_donation_ranking_dt: Optional[dict[str, str]] = PrivateAttr(default=None)

    def __init__(self, **kwargs):
        super(ChzzkModel, self).__init__(**kwargs)
        self._following_dt = kwargs.pop("following", None)
        self._real_time_donation_ranking_dt = kwargs.pop(
            "realTimeDonationRanking", None
        )

    @computed_field
    @property
    def following_date(self) -> Optional[str]:
        if self._following_dt is None:
            return
        return self._following_dt["followDate"]

    @computed_field
    @property
    def donation_ranking_badge(self) -> Optional[Badge]:
        if (
            self._real_time_donation_ranking_dt is None
            or "badge" not in self._real_time_donation_ranking_dt.keys()
        ):
            return
        return Badge.model_validate_json(self._real_time_donation_ranking_dt["badge"])


class ActivityBadge(Badge):
    badge_no: int
    badge_id: str
    description: Optional[str] = None
    activated: bool


class Profile(PartialUser):
    activity_badges: list[ActivityBadge] = Field(default_factory=list)
    user_role: Optional[UserRole] = Field(alias="userRoleCode", default=None)
    _badge: Optional[dict[str, str]] = PrivateAttr(default=None)
    _title: Optional[dict[str, str]] = PrivateAttr(default=None)
    streaming_property: Optional[StreamingProperty] = None

    def __init__(self, **kwargs):
        super(ChzzkModel, self).__init__(**kwargs)
        self._badge = kwargs.pop("badge", None)
        self._title = kwargs.pop("title", None)

    @computed_field
    @property
    def color(self) -> Optional[str]:
        if self._title is None:
            return
        return self._title["color"]

    @computed_field
    @property
    def badge(self) -> Optional[Badge]:
        if self._badge is None and self._title is None:
            return
        _badge = self._badge or dict()
        _title = self._title or dict()
        return Badge(
            name=_title.get("name", None), image_url=_badge.get("imageUrl", None)
        )
