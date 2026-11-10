"""MIT License

Copyright (c) 2024-2025 gunyu1019

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

import asyncio
import aiohttp.web
import contextlib
import webbrowser

from typing import AsyncIterator, Optional, TYPE_CHECKING
from yarl import URL

if TYPE_CHECKING:
    from .authorization import AccessToken
    from .client import Client

# An asyncio.Lock is bound to the event loop it is first waited on, so locks are keyed by
# the running loop as well as the port, and dropped as soon as no login uses them.
_login_locks: dict[tuple[asyncio.AbstractEventLoop, int], list] = {}


@contextlib.asynccontextmanager
async def _login_lock(port: int) -> AsyncIterator[None]:
    key = (asyncio.get_running_loop(), port)
    entry = _login_locks.setdefault(key, [asyncio.Lock(), 0])
    entry[1] += 1
    try:
        async with entry[0]:
            yield
    finally:
        entry[1] -= 1
        if entry[1] == 0:
            del _login_locks[key]


class ChzzkOAuth2Client:
    def __init__(
        self,
        client: Client,
        remote_scheme: Optional[str] = "http",
        remote_host: str = "localhost",
        remote_port: int = 8080,
        remote_path: Optional[str] = "/",
        success_response: Optional[aiohttp.web.Resource] = None,
    ):
        self.client = client

        self.remote_scheme = remote_scheme
        self.remote_host = remote_host
        self.remote_path = remote_path
        self.remote_port = remote_port

        self.success_response = success_response or aiohttp.web.Response(
            text="Success to login!"
        )

        self._application = aiohttp.web.Application()
        self._runner = aiohttp.web.AppRunner(self._application)
        self._site: Optional[aiohttp.web.TCPSite] = None

        self._application.router.add_get(self.remote_path, handler=self.handle)

        self._authorize_state: Optional[str] = None
        self._response: Optional[AccessToken] = None
        self._error: Optional[Exception] = None
        self._exchange_started = False
        self._stop_event = asyncio.Event()

    async def handle(self, request: aiohttp.web.Request):
        code = request.query.get("code")
        state = request.query.get("state")

        if state is None or code is None:
            return aiohttp.web.Response(
                text="Missing requirement parameter. Please try again!"
            )

        if state != self._authorize_state:
            return aiohttp.web.Response(text="Invalid state code. Please try again!")

        if self._exchange_started:
            # Only the first valid redirect exchanges the code, e.g. not a refreshed page.
            if self._response is None:
                return aiohttp.web.Response(
                    text="Login is already being processed. Please wait!"
                )
            # A response can be sent only once, so the repeated one gets a copy.
            return aiohttp.web.Response(
                body=self.success_response.body,
                status=self.success_response.status,
                content_type=self.success_response.content_type,
                charset=self.success_response.charset,
            )
        self._exchange_started = True

        try:
            self._response = await self.client.generate_access_token(
                code, state=self._authorize_state
            )
        except Exception as e:
            self._error = e
            self._stop_event.set()
            return aiohttp.web.Response(
                text="Failed to login. Please run login() again.", status=500
            )
        self._stop_event.set()
        return self.success_response

    def _open_webbrowser(self, url: str) -> bool:
        return webbrowser.open(url)

    @property
    def is_server_run(self) -> bool:
        return self._site is not None

    async def close(self):
        if not self.is_server_run:
            raise RuntimeError("A local web server is not enabled.")

        await self._site.stop()
        await self._runner.cleanup()

        self._stop_event.clear()

    async def process_oauth2(
        self, state: str, redirect_url: Optional[str] = None
    ) -> AccessToken:
        if self.is_server_run:
            raise RuntimeError("The OAuth2 login process is already in progress.")

        self._authorize_state = state

        redirect_url = (
            redirect_url
            or URL.build(
                scheme=self.remote_scheme,
                host=self.remote_host,
                path=self.remote_path,
                port=self.remote_port,
            ).__str__()
        )
        url = self.client.generate_authorization_token_url(
            redirect_url=redirect_url, state=state
        )

        # Logins sharing a port cannot run at once; each one waits for the previous one.
        async with _login_lock(self.remote_port):
            try:
                await self._runner.setup()

                self._site = aiohttp.web.TCPSite(
                    self._runner, self.remote_host, self.remote_port
                )
                await self._site.start()

                open_result = self._open_webbrowser(url)
                if not open_result:
                    print(
                        "Failed to open the browser. Please join this url and process login."
                    )
                else:
                    print(
                        "If you haven't opened your browser, please join this url and process login."
                    )
                print(url)
                await self._stop_event.wait()
            finally:
                if self.is_server_run:
                    await self.close()

        if self._error is not None:
            raise self._error
        return self._response
