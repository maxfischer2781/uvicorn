import asyncio
import os
import signal
import subprocess
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
    """Test interrupting a Server that is run explicitly inside asyncio"""

    async def interrupt_running(srv: Server):
        while not srv.started:
            await asyncio.sleep(0.01)
        os.kill(os.getpid(), signal.SIGINT)

    server = Server(Config(app=dummy_app, loop="asyncio"))
    asyncio.create_task(interrupt_running(server))
    with pytest.raises(graceful_sigint):
        await server.serve()
    # set by the server's graceful exit handler
    assert server.should_exit


def test_asyncio_server_interrupt_process():
    """Test interrupting an asyncio application that also runs a Server"""

    # minimal example for running a Server alongside another asyncio task
    # adapted from https://github.com/encode/uvicorn/issues/1579
    program = """\
import asyncio
from uvicorn import Config, Server

try:
    import coverage
    coverage.process_startup()
except ImportError:
    pass

async def dummy_app(scope, receive, send): pass

async def main():
    await asyncio.gather(
        Server(Config(app=dummy_app)).serve(),
        asyncio.sleep(10),
    )

asyncio.run(main())
"""
    try:  # pragma: no cover
        interrupt_sig = signal.CTRL_C_EVENT
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
    except AttributeError:
        interrupt_sig = signal.SIGINT
        creationflags = 0
    process = subprocess.Popen(
        [sys.executable, "-c", program],
        creationflags=creationflags,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
    )
    with process:
        for line in process.stdout:
            if b"Press CTRL+C to quit" in line:
                break
        else:  # pragma: no cover
            pytest.fail("uvicorn Server did not enable interrupt handler")
        # send interrupt signal now that the server is running
        process.send_signal(interrupt_sig)
        try:
            process.communicate(timeout=1)
        except subprocess.TimeoutExpired:  # pragma: no cover
            process.terminate()
            raise
        else:
            assert process.poll() is not None, "program did not stop after interrupt"
            assert process.returncode != 0, "program did not report interrupt"
