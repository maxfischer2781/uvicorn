import asyncio
import os
import signal
import sys

import pytest

from uvicorn.config import Config
from uvicorn.server import Server


class CaughtSigint(Exception):
    pass


@pytest.fixture
def graceful_sigint():
    """Fixture that replaces SIGINT handling with a normal exception"""

    def raise_handler(*args):
        raise CaughtSigint

    original_handler = signal.signal(signal.SIGINT, raise_handler)
    yield CaughtSigint
    signal.signal(signal.SIGINT, original_handler)


async def dummy_app(scope, receive, send):
    pass


@pytest.mark.anyio
@pytest.mark.skipif(sys.platform == "win32", reason="require unix-like signal handling")
async def test_server_interrupt(graceful_sigint):
    async def interrupt_running(srv: Server):
        while not srv.started:
            await asyncio.sleep(0.01)
        os.kill(os.getpid(), signal.SIGINT)

    server = Server(
        Config(
            app=dummy_app,
            loop="asyncio",
            limit_max_requests=1,
        )
    )
    asyncio.create_task(interrupt_running(server))
    with pytest.raises(graceful_sigint):
        await server.serve()
    # set by the server's graceful exit handler
    assert server.should_exit
