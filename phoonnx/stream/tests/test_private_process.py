"""OVOS_TTS_PRIVATE=1 in a real process: what the server writes to its log, and how it exits."""
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

pytest.importorskip("ovos_tts_server")
pytest.importorskip("uvicorn")

SERVER = Path(__file__).resolve().parent / "private_server.py"
SECRET = "SECRETWORDQQ"


class Server:
    def __init__(self, tmp_path, **env):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]
        self.log = tmp_path / "server.log"
        full = {k: v for k, v in os.environ.items() if not k.startswith(("OVOS_", "XDG_"))}
        full.update(env, XDG_CONFIG_HOME=str(tmp_path / "config"), HOME=str(tmp_path))
        self.out = open(self.log, "wb")
        self.process = subprocess.Popen([sys.executable, str(SERVER), str(self.port), str(tmp_path)],
                                        env=full, stdout=self.out, stderr=subprocess.STDOUT)
        deadline = time.monotonic() + 60
        while True:
            try:
                self.get("/status")
                return
            except (urllib.error.URLError, ConnectionError):
                assert self.process.poll() is None, self.log.read_text()
                assert time.monotonic() < deadline, "the server never answered"
                time.sleep(0.2)

    def get(self, path, **query):
        url = f"http://127.0.0.1:{self.port}{path}"
        if query:
            url += "?" + urllib.parse.urlencode(query)
        try:
            with urllib.request.urlopen(url, timeout=30) as answer:
                return answer.status, answer.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()

    def stop(self):
        """SIGTERM, and what the process leaves: its exit status and everything it logged."""
        if self.process.poll() is None:
            self.process.send_signal(signal.SIGTERM)
        status = self.process.wait(30)
        self.out.close()
        return status, self.log.read_text()


@pytest.fixture
def servers(tmp_path):
    made = []

    def start(name, **env):
        folder = tmp_path / name
        folder.mkdir()
        made.append(server := Server(folder, **env))
        return server

    yield start
    for server in made:
        if server.process.poll() is None:
            server.process.kill()
            server.process.wait()


def ask_everything(server):
    assert server.get("/v2/synthesize", utterance=f"say {SECRET} now")[0] == 200
    assert server.get("/v2/synthesize", utterance=f"lose {SECRET}", lost="1")[0] == 200
    return server.get("/v2/synthesize", utterance=f"fail on {SECRET}", boom="1")


def test_a_control_server_logs_the_words(servers):
    server = servers("open", OVOS_DEFAULT_LOG_LEVEL="DEBUG")
    ask_everything(server)
    _, log = server.stop()
    assert SECRET in log  # so the next test can fail
    # Each way the text can reach the log is there in the open server, so that the private one's
    # silence is a result: phoonnx's number error, a library's own logger, the root logger, the
    # last-resort handler, asyncio's "never retrieved".
    for line in ("failed to pronounce number", "cannot read", "root says", "module-level logging call",
                 "Task exception was never retrieved", "task cannot say", "unread written form"):
        assert line in log, line


def test_a_private_server_logs_no_word_of_the_text(servers):
    # DEBUG is asked for, and the exception carries the text in its message.
    server = servers("private", OVOS_TTS_PRIVATE="1", OVOS_DEFAULT_LOG_LEVEL="DEBUG")
    status, body = ask_everything(server)
    assert status == 500 and body == b'{"error":"internal"}'
    _, log = server.stop()
    assert SECRET not in log and "secretword" not in log.lower()
    assert "GET /v2/synthesize" not in log  # no access log line either
    assert "ValueError" in log  # the type of what failed is kept, for the operator
    for line in ("pronounce", "cannot read", "root says", "module-level", "never retrieved", "task cannot",
                 "unread written form", "saying"):
        assert line not in log, line


def test_a_private_server_logs_no_word_at_the_default_level_either(servers):
    server = servers("private-info", OVOS_TTS_PRIVATE="1")
    ask_everything(server)
    _, log = server.stop()
    assert SECRET not in log


def test_a_private_server_logs_nothing_even_when_asked_for_everything(servers):
    server = servers("private-all", OVOS_TTS_PRIVATE="1", OVOS_DEFAULT_LOG_LEVEL="DEBUG", PYTHONASYNCIODEBUG="1",
                     PYTHONWARNINGS="default")
    ask_everything(server)
    _, log = server.stop()
    assert SECRET not in log


def test_the_exit_status_after_a_recycle(servers):
    """A recycle ends in SIGTERM, and uvicorn then leaves by the signal it caught: 143 for a
    process that has a parent, as in a shell. A container's process is PID 1, to which the kernel
    delivers no signal that has the default action, so there it exits 0 (measured in the image)."""
    server = servers("recycle", OVOS_TTS_PRIVATE="1", OVOS_TTS_RECYCLE_MB="1")
    assert server.get("/v2/synthesize", utterance="over the line")[0] == 200
    status, _ = server.get("/status")
    assert status == 503  # draining
    code = server.process.wait(30)
    server.out.close()
    assert code in (0, -signal.SIGTERM), code  # -15 is what a shell reports as 143
    assert code == -signal.SIGTERM, "uvicorn changed how it leaves after SIGTERM: update the runbook"
