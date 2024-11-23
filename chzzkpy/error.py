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

from typing import Optional, Any
from .base_model import Content


class ChzzkpyException(Exception):
    pass


class LoginRequired(ChzzkpyException):
    """Exception that’s raised when a method need login."""

    def __init__(self):
        super(LoginRequired, self).__init__(
            "This method(feature) needs to login. Please use `login()` method."
        )


class NotFound(ChzzkpyException):
    """Exception that’s raised for when status code 404 occurs."""

    def __init__(self, message: Optional[str] = None):
        if message is None:
            message = "Not Found"
        super(NotFound, self).__init__(message)


class HTTPException(ChzzkpyException):
    """Exception that’s raised when an HTTP request operation fails."""

    def __init__(self, code: int, message: Optional[str] = None):
        if message is None:
            message = f"Reponsed error code ({code})"
        else:
            message += f" ({code})"
        super(HTTPException, self).__init__(message)
