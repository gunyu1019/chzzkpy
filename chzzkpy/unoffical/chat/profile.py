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


class SubscriptionInfo(ChzzkModel):
    _badge: Optional[dict[str, str]] = PrivateAttr(default=None)
    accumulative_month: int
    tier: int

    def __init__(self, **kwargs):
        badge = kwargs.pop("badge", None)
        super(ChzzkModel, self).__init__(**kwargs)
        self._badge = badge

    @computed_field
    @property
    def badge(self) -> Optional[Badge]:
        _badge = self._badge or dict()
        if "imageUrl" not in self._badge.keys():
            return
        return Badge(image_url=_badge["imageUrl"])


class StreamingProperty(ChzzkModel):
    _following_dt: Optional[dict[str, str]] = PrivateAttr(default=None)
    _real_time_donation_ranking_dt: Optional[dict[str, str]] = PrivateAttr(default=None)
    _nickname_color: Optional[dict[str, str]] = PrivateAttr(default=None)
    _subscription: Optional[dict[str, str]] = PrivateAttr(default=None)

    def __init__(self, **kwargs):
        following_dt = kwargs.pop("following", None)
        real_time_donation_ranking_dt = kwargs.pop("realTimeDonationRanking", None)
        nickname_color = kwargs.pop("nicknameColor", None)
        subscription = kwargs.pop("subscription", None)
        super(ChzzkModel, self).__init__(**kwargs)
        self._following_dt = following_dt
        self._real_time_donation_ranking_dt = real_time_donation_ranking_dt
        self._nickname_color = nickname_color
        self._subscription = subscription

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

    @computed_field
    @property
    def nickname_color(self) -> Optional[str]:
        if (
            self._nickname_color is None
            or "colorCode" not in self._nickname_color.keys()
        ):
            return
        return self._nickname_color["colorCode"]

    @computed_field
    @property
    def subscription(self) -> Optional[SubscriptionInfo]:
        if self._subscription is None:
            return
        return SubscriptionInfo.model_validate(self._subscription)


class ActivityBadge(Badge):
    badge_no: int
    badge_id: str
    description: Optional[str] = None
    activated: bool


class ViewerBadge(ChzzkModel):
    type: Optional[str] = None
    _badge_data: dict[str, str] = PrivateAttr(default=None)

    def __init__(self, **kwargs):
        badge_data = kwargs.pop("badge", None) or dict()
        super(ChzzkModel, self).__init__(**kwargs)
        self._badge_data = badge_data

    @computed_field
    @property
    def image_url(self) -> Optional[str]:
        badge_data = self._badge_data
        if "imageUrl" not in badge_data.keys():
            return
        return badge_data["imageUrl"]

    @computed_field
    @property
    def scope(self) -> Optional[str]:
        badge_data = self._badge_data
        if "scope" not in badge_data.keys():
            return
        return badge_data["scope"]

    @computed_field
    @property
    def badge_id(self) -> Optional[str]:
        badge_data = self._badge_data
        if "badge_id" not in badge_data.keys():
            return
        return badge_data["badge_id"]


class Profile(PartialUser):
    activity_badges: list[ActivityBadge] = Field(default_factory=list)
    user_role: Optional[UserRole] = Field(alias="userRoleCode", default=None)
    _badge: Optional[dict[str, str]] = PrivateAttr(default=None)
    _title: Optional[dict[str, str]] = PrivateAttr(default=None)
    viewer_badges: list[ViewerBadge] = Field(default_factory=list)
    streaming_property: Optional[StreamingProperty] = None

    def __init__(self, **kwargs):
        bagde_data = kwargs.pop("badge", None)
        title_data = kwargs.pop("title", None)
        super(ChzzkModel, self).__init__(**kwargs)
        self._badge = bagde_data
        self._title = title_data

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
