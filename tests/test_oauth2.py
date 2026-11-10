"""MIT License

Copyright (c) 2024-2025 gunyu1019

Tests for the OAuth2 login helper (`ChzzkOAuth2Client`) of the official chzzkpy package.

Logins that share a port are processed one after another, and a flow that fails or is
cancelled must give back the port and the lock. Every flow here runs the real local web
server on a free localhost port. Nothing leaves the machine: the browser is replaced by a
`FakeBrowser` that sends the redirect request itself, and the token exchange is stubbed.
"""

import asyncio
import socket
import time
from typing import Optional

import aiohttp
import aiohttp.web
import pytest
from yarl import URL

from chzzkpy import AccessToken, Client
from chzzkpy import oauth2
from chzzkpy.oauth2 import ChzzkOAuth2Client

CLIENT_ID = "client-id"
CLIENT_SECRET = "client-secret"
HOST = "127.0.0.1"
TIMEOUT = 10


def find_free_port() -> int:
    with socket.socket() as sock:
        sock.bind((HOST, 0))
        return sock.getsockname()[1]


def is_listening(port: int) -> bool:
    try:
        socket.create_connection((HOST, port), timeout=1).close()
    except OSError:
        return False
    return True


class FakeBrowser:
    """Plays the user: gets the authorization URL and follows the redirect back."""

    def __init__(self, events: list[str]):
        self.events = events
        # States whose redirect is not sent automatically; a test sends it itself.
        self.hold: set[str] = set()
        self.urls: dict[str, str] = {}
        self.replies: list[tuple[int, str]] = []
        self._tasks: list[asyncio.Task] = []

    def open(self, url: str) -> bool:
        state = URL(url).query["state"]
        self.urls[state] = url
        self.events.append(f"open:{state}")

        if state not in self.hold:
            self._tasks.append(
                asyncio.get_running_loop().create_task(self.redirect(state))
            )
        return True

    async def redirect(
        self, flow: str, /, **overrides: Optional[str]
    ) -> tuple[int, str]:
        """Send the redirect request of `flow` (its state); a `None` override drops a parameter."""
        query = URL(self.urls[flow]).query
        params = {"code": f"code-{flow}", "state": flow, **overrides}
        params = {key: value for key, value in params.items() if value is not None}

        timeout = aiohttp.ClientTimeout(total=TIMEOUT)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(
                URL(query["redirectUri"]).with_query(params)
            ) as response:
                reply = (response.status, await response.text())

        self.replies.append(reply)
        return reply

    async def opened(self, state: str):
        deadline = time.monotonic() + TIMEOUT
        while state not in self.urls:
            assert (
                time.monotonic() < deadline
            ), f"The flow {state!r} never opened the browser."
            await asyncio.sleep(0.01)

    async def settle(self):
        await asyncio.gather(*self._tasks)

    async def exchanging(self, state: str):
        deadline = time.monotonic() + TIMEOUT
        while f"exchange:{state}" not in self.events:
            assert (
                time.monotonic() < deadline
            ), f"The flow {state!r} never exchanged its code."
            await asyncio.sleep(0.01)


def make_flow(
    port: int,
    events: list[str],
    error: Optional[Exception] = None,
    gate: Optional[asyncio.Event] = None,
    **options,
) -> ChzzkOAuth2Client:
    """A flow of its own `Client`, whose token exchange is stubbed.

    The exchange fails with `error`, and waits for `gate` to be set before it ends.
    """
    client = Client(CLIENT_ID, CLIENT_SECRET)

    async def generate_access_token(code: str, state: str) -> AccessToken:
        events.append(f"exchange:{state}")
        if gate is not None:
            await gate.wait()
        if error is not None:
            raise error
        return AccessToken(
            access_token=f"access-{state}",
            refresh_token=f"refresh-{state}",
            expires_in=86400,
        )

    client.generate_access_token = generate_access_token
    return ChzzkOAuth2Client(client, remote_host=HOST, remote_port=port, **options)


@pytest.fixture
def port() -> int:
    return find_free_port()


@pytest.fixture
def events(monkeypatch) -> list[str]:
    log = []
    original_close = ChzzkOAuth2Client.close

    async def close(self):
        await original_close(self)
        log.append(f"closed:{self._authorize_state}")

    monkeypatch.setattr(ChzzkOAuth2Client, "close", close)
    return log


@pytest.fixture
def browser(monkeypatch, events) -> FakeBrowser:
    fake = FakeBrowser(events)
    monkeypatch.setattr(ChzzkOAuth2Client, "_open_webbrowser", fake.open)
    return fake


@pytest.mark.asyncio
class TestSerializedLogin:
    async def test_flows_on_same_port_run_one_after_another(
        self, port, events, browser
    ):
        flows = [make_flow(port, events) for _ in range(3)]

        tokens = await asyncio.wait_for(
            asyncio.gather(
                *(flow.process_oauth2(name) for flow, name in zip(flows, "abc"))
            ),
            TIMEOUT,
        )

        assert [token.access_token for token in tokens] == [
            "access-a",
            "access-b",
            "access-c",
        ]
        assert events == [
            f"{step}:{name}"
            for name in "abc"
            for step in ("open", "exchange", "closed")
        ]
        assert not is_listening(port)
        assert not oauth2._login_locks

    async def test_flows_on_different_ports_do_not_wait_for_each_other(
        self, port, events, browser
    ):
        browser.hold.add("slow")
        slow = asyncio.create_task(make_flow(port, events).process_oauth2("slow"))
        await browser.opened("slow")

        fast = make_flow(find_free_port(), events)
        token = await asyncio.wait_for(fast.process_oauth2("fast"), TIMEOUT)

        assert token.access_token == "access-fast"
        assert not slow.done()

        await browser.redirect("slow")
        assert (await asyncio.wait_for(slow, TIMEOUT)).access_token == "access-slow"

    async def test_lock_is_not_shared_between_event_loops(self, port):
        async def enter():
            async with oauth2._login_lock(port):
                return True

        def run_in_other_loop():
            return asyncio.run(asyncio.wait_for(enter(), 2))

        async with oauth2._login_lock(port):
            assert await asyncio.to_thread(run_in_other_loop)

        assert not oauth2._login_locks


@pytest.mark.asyncio
class TestFailedFlow:
    async def test_failed_exchange_raises_and_frees_port(self, port, events, browser):
        error = ValueError("exchange failed")

        with pytest.raises(ValueError) as exc_info:
            await asyncio.wait_for(
                make_flow(port, events, error).process_oauth2("failing"), TIMEOUT
            )
        await browser.settle()

        assert exc_info.value is error
        assert browser.replies == [(500, "Failed to login. Please run login() again.")]
        assert events == ["open:failing", "exchange:failing", "closed:failing"]
        assert not is_listening(port)
        assert not oauth2._login_locks

        token = await asyncio.wait_for(
            make_flow(port, events).process_oauth2("next"), TIMEOUT
        )
        assert token.access_token == "access-next"

    async def test_failed_exchange_lets_queued_flow_proceed(
        self, port, events, browser
    ):
        error = ValueError("exchange failed")
        first = make_flow(port, events, error)
        second = make_flow(port, events)

        results = await asyncio.wait_for(
            asyncio.gather(
                first.process_oauth2("first"),
                second.process_oauth2("second"),
                return_exceptions=True,
            ),
            TIMEOUT,
        )

        assert results[0] is error
        assert results[1].access_token == "access-second"
        assert events.index("closed:first") < events.index("open:second")

    async def test_failed_bind_raises_and_releases_lock(self, port, events, browser):
        with socket.socket() as blocker:
            blocker.bind((HOST, port))
            blocker.listen()

            with pytest.raises(OSError):
                await asyncio.wait_for(
                    make_flow(port, events).process_oauth2("blocked"), TIMEOUT
                )

        assert "open:blocked" not in events
        assert not oauth2._login_locks

        token = await asyncio.wait_for(
            make_flow(port, events).process_oauth2("next"), TIMEOUT
        )
        assert token.access_token == "access-next"


@pytest.mark.asyncio
class TestCancelledFlow:
    async def test_cancelled_flow_closes_server_and_releases_lock(
        self, port, events, browser
    ):
        browser.hold.add("waiting")
        waiting = asyncio.create_task(make_flow(port, events).process_oauth2("waiting"))
        await browser.opened("waiting")
        assert is_listening(port)

        waiting.cancel()
        await asyncio.wait({waiting}, timeout=TIMEOUT)

        assert waiting.cancelled()
        assert events == ["open:waiting", "closed:waiting"]
        assert not is_listening(port)
        assert not oauth2._login_locks

        token = await asyncio.wait_for(
            make_flow(port, events).process_oauth2("next"), TIMEOUT
        )
        assert token.access_token == "access-next"

    async def test_cancelled_flow_lets_queued_flow_proceed(self, port, events, browser):
        browser.hold.add("holder")
        holder = asyncio.create_task(make_flow(port, events).process_oauth2("holder"))
        await browser.opened("holder")
        queued = asyncio.create_task(make_flow(port, events).process_oauth2("queued"))
        await asyncio.sleep(0.1)
        assert "open:queued" not in events

        holder.cancel()
        token = await asyncio.wait_for(queued, TIMEOUT)

        assert holder.cancelled()
        assert token.access_token == "access-queued"
        assert events == [
            "open:holder",
            "closed:holder",
            "open:queued",
            "exchange:queued",
            "closed:queued",
        ]
        assert not oauth2._login_locks

    async def test_cancelled_queued_flow_does_not_break_the_lock(
        self, port, events, browser
    ):
        browser.hold.add("holder")
        holder = asyncio.create_task(make_flow(port, events).process_oauth2("holder"))
        await browser.opened("holder")
        dropped = asyncio.create_task(make_flow(port, events).process_oauth2("dropped"))
        queued = asyncio.create_task(make_flow(port, events).process_oauth2("queued"))
        await asyncio.sleep(0.1)

        dropped.cancel()
        await asyncio.wait({dropped}, timeout=TIMEOUT)
        assert dropped.cancelled()
        assert not queued.done()

        await browser.redirect("holder")
        tokens = await asyncio.wait_for(asyncio.gather(holder, queued), TIMEOUT)

        assert [token.access_token for token in tokens] == [
            "access-holder",
            "access-queued",
        ]
        assert not any(event.endswith(":dropped") for event in events)
        assert not oauth2._login_locks


@pytest.mark.asyncio
class TestRedirectValidation:
    async def test_bad_redirect_keeps_waiting_until_correct_redirect(
        self, port, events, browser
    ):
        browser.hold.add("expected")
        flow = asyncio.create_task(make_flow(port, events).process_oauth2("expected"))
        await browser.opened("expected")

        assert await browser.redirect("expected", code=None) == (
            200,
            "Missing requirement parameter. Please try again!",
        )
        assert await browser.redirect("expected", state=None) == (
            200,
            "Missing requirement parameter. Please try again!",
        )
        assert await browser.redirect("expected", state="other") == (
            200,
            "Invalid state code. Please try again!",
        )
        await asyncio.sleep(0.1)

        assert not flow.done()
        assert events == ["open:expected"]
        assert is_listening(port)

        assert await browser.redirect("expected") == (200, "Success to login!")
        token = await asyncio.wait_for(flow, TIMEOUT)

        assert token.access_token == "access-expected"
        assert events == ["open:expected", "exchange:expected", "closed:expected"]
        assert not is_listening(port)


@pytest.mark.asyncio
class TestDuplicateRedirect:
    async def test_duplicate_during_exchange_does_not_exchange_again(
        self, port, events, browser
    ):
        browser.hold.add("refresh")
        gate = asyncio.Event()
        flow = asyncio.create_task(
            make_flow(port, events, gate=gate).process_oauth2("refresh")
        )
        await browser.opened("refresh")

        first = asyncio.create_task(browser.redirect("refresh"))
        await browser.exchanging("refresh")
        duplicate = await browser.redirect("refresh")

        assert duplicate == (200, "Login is already being processed. Please wait!")
        assert not flow.done()

        gate.set()
        token = await asyncio.wait_for(flow, TIMEOUT)

        assert token.access_token == "access-refresh"
        assert await first == (200, "Success to login!")
        assert events.count("exchange:refresh") == 1

    async def test_duplicate_after_success_keeps_the_token(
        self, monkeypatch, port, events, browser
    ):
        # The server is kept open after the exchange, as if the redirect was refreshed
        # right after the first one.
        close_gate = asyncio.Event()
        close = ChzzkOAuth2Client.close

        async def delayed_close(self):
            await close_gate.wait()
            await close(self)

        monkeypatch.setattr(ChzzkOAuth2Client, "close", delayed_close)

        browser.hold.add("refresh")
        success_response = aiohttp.web.Response(
            text="<b>Welcome</b>", content_type="text/html"
        )
        flow = asyncio.create_task(
            make_flow(port, events, success_response=success_response).process_oauth2(
                "refresh"
            )
        )
        await browser.opened("refresh")

        assert await browser.redirect("refresh") == (200, "<b>Welcome</b>")
        await browser.exchanging("refresh")
        assert not flow.done()
        assert is_listening(port)
        assert await browser.redirect("refresh") == (200, "<b>Welcome</b>")
        assert await browser.redirect("refresh") == (200, "<b>Welcome</b>")

        close_gate.set()
        token = await asyncio.wait_for(flow, TIMEOUT)

        assert token.access_token == "access-refresh"
        assert events.count("exchange:refresh") == 1

    async def test_duplicate_after_failure_keeps_the_error(
        self, monkeypatch, port, events, browser
    ):
        close_gate = asyncio.Event()
        close = ChzzkOAuth2Client.close

        async def delayed_close(self):
            await close_gate.wait()
            await close(self)

        monkeypatch.setattr(ChzzkOAuth2Client, "close", delayed_close)

        error = ValueError("exchange failed")
        browser.hold.add("refresh")
        flow = asyncio.create_task(
            make_flow(port, events, error).process_oauth2("refresh")
        )
        await browser.opened("refresh")

        assert await browser.redirect("refresh") == (
            500,
            "Failed to login. Please run login() again.",
        )
        assert await browser.redirect("refresh") == (
            200,
            "Login is already being processed. Please wait!",
        )

        close_gate.set()
        await asyncio.wait({flow}, timeout=TIMEOUT)

        assert flow.exception() is error
        assert events.count("exchange:refresh") == 1
