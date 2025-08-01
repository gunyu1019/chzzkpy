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
import webbrowser

from typing import Optional, TYPE_CHECKING
from yarl import URL

if TYPE_CHECKING:
    from .authorization import AccessToken
    from .client import Client


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
        self._stop_event = asyncio.Event()

    async def handle(self, request: aiohttp.web.Request):
        code = request.query.get("code")
        state = request.query.get("state")

        if state is None or code is None:
            return aiohttp.web.Response(
                text="Missing requirement parameter. Please try again!"
            )

        if state != self._authorize_state:
            return aiohttp.web.Response(text="Invaild state code. Please try again!")

        self._response = await self.client.generate_access_token(
            code, state=self._authorize_state
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

        await self._runner.setup()

        self._site = aiohttp.web.TCPSite(
            self._runner, self.remote_host, self.remote_port
        )
        await self._site.start()

        open_result = self._open_webbrowser(url)
        if not open_result:
            print("Failed to open the browser. Please join this url and process login.")
        else:
            print(
                "If you haven't opened your browser, please join this url and process login."
            )
        print(url)
        await self._stop_event.wait()

        await self.close()
        return self._response
