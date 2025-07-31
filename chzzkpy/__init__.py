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

from .authorization import AccessToken
from .category import Category
from .channel import Channel
from .client import Client, UserClient
from .error import *
from .flags import UserPermission
from .message import Donation, Profile, Message


try:
    from .unoffical import *
except ModuleNotFoundError:
    pass


__title__ = "chzzkpy"
__author__ = "gunyu1019"
__license__ = "MIT"
__copyright__ = "Copyright 2024-present gunyu1019"
__version__ = "2.1.0-beta1"  # version_info.to_string()


class VersionInfo(NamedTuple):
    major: int
    minor: int
    micro: int
    release_level: Optional[Literal["alpha", "beta", "candidate", "final"]]
    serial: int

    def to_string(self) -> str:
        _version_info = f"{self.major}.{self.minor}.{self.micro}"
        if self.release_level is not None:
            _version_info += "-{}".format(self.release_level) + str(self.serial)
        return _version_info


version_info: VersionInfo = VersionInfo(
    major=2, minor=1, micro=0, release_level="beta", serial=1
)
