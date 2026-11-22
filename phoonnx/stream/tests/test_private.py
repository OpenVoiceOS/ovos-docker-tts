"""OVOS_TTS_PRIVATE=1: the words stay off disk and out of logs, and the server bounds its own work.

The app under test is the real `ovos_tts_server.create_app` when that package is installed (it is
in the image), over a plugin that writes its WAV the way phoonnx does; the tests skip without it.
"""
import logging
import os
import signal
import sys
import threading
import wave

import pytest

pytest.importorskip("ovos_tts_server")
from fastapi.testclient import TestClient  # noqa: E402

import ovos_tts_server  # noqa: E402
import ovos_tts_stream as s  # noqa: E402

PRIVATE_ENV = ("OVOS_TTS_PRIVATE", "OVOS_TTS_CONCURRENCY", "OVOS_TTS_RECYCLE_MB", "OVOS_TTS_NO_ARENA")


@pytest.fixture(autouse=True)
def keep_the_log_level(monkeypatch):
    """main() forces the OVOS log level to ERROR, in the environment and in LOG: undo it."""
    from ovos_utils.log import LOG

    monkeypatch.setenv("OVOS_DEFAULT_LOG_LEVEL", "INFO")
    level = LOG.level
    yield
    LOG.set_level(level)


class Plugin:
    config = {"voice": "piper/test"}


Plugin.__module__ = "phoonnx.opm"


class Wrapper:
    """What ovos-tts-server's TTSEngineWrapper offers the app; the plugin writes WAV files named
    by a hash of the words, in one shared folder, as phoonnx does, and never deletes them."""

    plugin_name = "ovos-tts-plugin-phoonnx"
    langs = ["en-us"]
    lang = "en-us"
    voices = []
    dialog_transformers = tts_transformers = None

    def __init__(self, folder, gate=None, running=None):
        self.engine = Plugin()
        self.folder, self.gate, self.running = folder, gate, running
        self.texts = []

    def synthesize(self, utterance, **params):
        self.texts.append(utterance)
        if self.running is not None:
            self.running.release()
        if self.gate is not None:
            assert self.gate.wait(10), "the test never opened the gate"
        path = self.folder / f"{abs(hash(utterance))}.wav"
        with wave.open(str(path), "wb") as out:
            out.setnchannels(1), out.setsampwidth(2), out.setframerate(22050)
            out.writeframes(b"\x01\x00" * 500)
        return str(path), None


def serve_app(monkeypatch, wrapper, **env):
    """Run main() as the entrypoint does, and return the app the server was handed."""
    for name in PRIVATE_ENV:
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    seen = {}

    def serve():
        seen["app"] = ovos_tts_server.create_app(wrapper)

    entry = type(sys)("ovos_tts_server.__main__")
    entry.main = serve
    monkeypatch.setitem(sys.modules, "ovos_tts_server.__main__", entry)
    # main() replaces module attributes of the server and uvicorn; put them back afterwards.
    import uvicorn

    monkeypatch.setattr(ovos_tts_server, "create_app", ovos_tts_server.create_app)
    monkeypatch.setattr(ovos_tts_server, "FileResponse", ovos_tts_server.FileResponse)
    monkeypatch.setattr(uvicorn, "run", uvicorn.run)
    monkeypatch.setattr(wave.Wave_write, "writeframesraw", wave.Wave_write.writeframesraw)
    s.main()
    return TestClient(seen["app"])


def wavs(folder):
    return sorted(p.name for p in folder.glob("*.wav"))


def test_private_is_off_unless_asked(monkeypatch, tmp_path):
    client = serve_app(monkeypatch, Wrapper(tmp_path))
    assert "private" not in client.get("/status").json()
    assert client.get("/v2/synthesize/json?utterance=hi").status_code == 200  # the stock routes stay


@pytest.mark.parametrize("value", ["1", "true", "YES", " on "])
def test_private_values(monkeypatch, value):
    monkeypatch.setenv("OVOS_TTS_PRIVATE", value)
    assert s._private()


@pytest.mark.parametrize("value", ["", "0", "no", "off", "2"])
def test_not_private_values(monkeypatch, value):
    monkeypatch.setenv("OVOS_TTS_PRIVATE", value)
    assert not s._private()


def test_status_says_private_and_keeps_the_rest(monkeypatch, tmp_path):
    client = serve_app(monkeypatch, Wrapper(tmp_path), OVOS_TTS_PRIVATE="1")
    answer = client.get("/status")
    assert answer.status_code == 200
    assert answer.json()["private"] is True
    assert answer.json()["plugin"] == "ovos-tts-plugin-phoonnx"


def test_only_status_and_synthesize_are_served(monkeypatch, tmp_path):
    wrapper = Wrapper(tmp_path)
    client = serve_app(monkeypatch, wrapper, OVOS_TTS_PRIVATE="1")
    for path in ("/v2/synthesize/json?utterance=hi", "/v2/synthesize/stream?utterance=hi",
                 "/synthesize/hi", "/docs", "/openapi.json", "/redoc", "/mcp", "/utcp"):
        assert client.get(path).status_code == 404, path
    assert wrapper.texts == []  # none of them reached the engine
    assert {r.path for r in client.app.router.routes} == {"/status", "/v2/synthesize"}


def test_no_cors_headers(monkeypatch, tmp_path):
    client = serve_app(monkeypatch, Wrapper(tmp_path), OVOS_TTS_PRIVATE="1")
    answer = client.get("/status", headers={"Origin": "https://example.test"})
    assert "access-control-allow-origin" not in answer.headers
    answer = client.options("/v2/synthesize", headers={"Origin": "https://example.test",
                                                      "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in answer.headers


def test_each_answer_is_deleted_once_sent(monkeypatch, tmp_path):
    client = serve_app(monkeypatch, Wrapper(tmp_path), OVOS_TTS_PRIVATE="1")
    for words in ("one", "two", "one", "one"):  # the same words twice: the shared name is taken
        answer = client.get("/v2/synthesize", params={"utterance": words})
        assert answer.status_code == 200
        assert answer.content[:4] == b"RIFF"
    assert wavs(tmp_path) == []


def test_without_private_the_stock_server_leaves_the_file(monkeypatch, tmp_path):
    client = serve_app(monkeypatch, Wrapper(tmp_path))
    assert client.get("/v2/synthesize", params={"utterance": "kept"}).status_code == 200
    assert len(wavs(tmp_path)) == 1


def test_a_failed_synthesis_leaves_nothing(monkeypatch, tmp_path):
    wrapper = Wrapper(tmp_path)
    plain = wrapper.synthesize

    def broken_after_writing(utterance, **params):
        plain(utterance, **params)
        raise RuntimeError("synthesis failed")

    wrapper.synthesize = broken_after_writing
    client = serve_app(monkeypatch, wrapper, OVOS_TTS_PRIVATE="1")
    with pytest.raises(RuntimeError):
        client.get("/v2/synthesize", params={"utterance": "words"})
    # The engine's own file is the plugin's business (the sweeper); this layer made none of its own.
    assert len(wavs(tmp_path)) == 1


def test_the_log_is_configured_for_privacy(monkeypatch, tmp_path):
    """What the real log output holds is tested in test_private_process.py; this is the wiring."""
    import uvicorn

    from ovos_utils.log import LOG

    given = {}
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: given.update(k))
    for name in PRIVATE_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OVOS_TTS_PRIVATE", "1")
    monkeypatch.setenv("OVOS_DEFAULT_LOG_LEVEL", "DEBUG")  # asked for, and not obeyed
    entry = type(sys)("ovos_tts_server.__main__")
    entry.main = lambda: uvicorn.run(object(), host="0.0.0.0", port=1)  # as the server's main() does
    monkeypatch.setitem(sys.modules, "ovos_tts_server.__main__", entry)
    monkeypatch.setattr(ovos_tts_server, "create_app", ovos_tts_server.create_app)
    monkeypatch.setattr(ovos_tts_server, "FileResponse", ovos_tts_server.FileResponse)
    monkeypatch.setattr(wave.Wave_write, "writeframesraw", wave.Wave_write.writeframesraw)
    levels = {n: logging.getLogger(n).level for n in (*s.PRIVATE_LOGGERS, "")}
    try:
        s.main()
        assert given["access_log"] is False
        assert given["host"] == "0.0.0.0" and given["port"] == 1  # the server's own arguments stand
        for name in s.PRIVATE_LOGGERS:
            assert logging.getLogger(name).level == logging.CRITICAL
        assert os.environ["OVOS_DEFAULT_LOG_LEVEL"] == "CRITICAL"
        assert LOG.level == "CRITICAL"
        assert logging.getLogger().level == logging.CRITICAL
        # Every handler of uvicorn's log keeps an exception's type and drops its message.
        config = given["log_config"]
        assert config["filters"]["no_words"]["()"] == "ovos_tts_stream.NoWords"
        assert all("no_words" in h["filters"] for h in config["handlers"].values())
    finally:
        for name, level in levels.items():
            logging.getLogger(name).setLevel(level)


def test_no_words_keeps_the_type_and_drops_the_message_and_the_traceback():
    try:
        raise ValueError("cannot say SECRETWORDQQ")
    except ValueError:
        record = logging.LogRecord("uvicorn.error", logging.ERROR, __file__, 1,
                                   "Exception in ASGI application\n", None, sys.exc_info())
    assert s.NoWords().filter(record)
    assert record.exc_info is None and record.exc_text is None
    assert "SECRETWORDQQ" not in record.getMessage() and "ValueError" in record.getMessage()
    plain = logging.LogRecord("uvicorn.error", logging.INFO, __file__, 1, "Uvicorn running on %s", ("x",), None)
    s.NoWords().filter(plain)
    assert plain.getMessage() == "Uvicorn running on x"  # what carries no exception is untouched


def test_an_engine_that_raises_is_a_500_that_says_nothing(monkeypatch, tmp_path):
    wrapper = Wrapper(tmp_path)

    def broken(utterance, **params):
        raise ValueError(f"cannot say {utterance}")

    wrapper.synthesize = broken
    client = serve_app(monkeypatch, wrapper, OVOS_TTS_PRIVATE="1")
    client = TestClient(client.app, raise_server_exceptions=False)
    answer = client.get("/v2/synthesize", params={"utterance": "SECRETWORDQQ"})
    assert answer.status_code == 500
    assert answer.json() == {"error": "internal"} and "SECRET" not in answer.text


def test_the_arena_is_off_in_private_mode_and_on_when_asked(monkeypatch, tmp_path):
    ort = pytest.importorskip("onnxruntime")
    original = ort.SessionOptions
    try:
        serve_app(monkeypatch, Wrapper(tmp_path), OVOS_TTS_PRIVATE="1")
        options = ort.SessionOptions()
        assert options.enable_cpu_mem_arena is False and options.enable_mem_pattern is False
        ort.SessionOptions = original
        serve_app(monkeypatch, Wrapper(tmp_path), OVOS_TTS_PRIVATE="1", OVOS_TTS_NO_ARENA="0")
        assert ort.SessionOptions is original
    finally:
        ort.SessionOptions = original


def test_concurrency_is_bounded_and_status_never_counts(monkeypatch, tmp_path):
    gate, running = threading.Event(), threading.Semaphore(0)
    wrapper = Wrapper(tmp_path, gate=gate, running=running)
    client = serve_app(monkeypatch, wrapper, OVOS_TTS_PRIVATE="1", OVOS_TTS_CONCURRENCY="2",
                       OVOS_TTS_RECYCLE_MB="0")
    answers = []

    def ask(words):
        answers.append(client.get("/v2/synthesize", params={"utterance": words}).status_code)

    threads = [threading.Thread(target=ask, args=(f"line {i}",)) for i in range(2)]
    for thread in threads:
        thread.start()
    assert running.acquire(timeout=10) and running.acquire(timeout=10)  # both are synthesising
    full = client.get("/v2/synthesize", params={"utterance": "third"})
    assert full.status_code == 503 and full.headers["Retry-After"] == "2"
    assert client.get("/status").status_code == 200  # a probe is not a synthesis
    gate.set()
    for thread in threads:
        thread.join(10)
    assert sorted(answers) == [200, 200]
    assert client.get("/v2/synthesize", params={"utterance": "later"}).status_code == 200
    assert wavs(tmp_path) == []


def test_unset_concurrency_is_four_and_a_bad_value_is_too(monkeypatch):
    monkeypatch.delenv("OVOS_TTS_CONCURRENCY", raising=False)
    assert s._concurrency() == 4
    monkeypatch.setenv("OVOS_TTS_CONCURRENCY", "many")
    assert s._concurrency() == 4
    monkeypatch.setenv("OVOS_TTS_CONCURRENCY", "0")
    assert s._concurrency() == 1  # never "no limit"
    monkeypatch.setenv("OVOS_TTS_CONCURRENCY", "6")
    assert s._concurrency() == 6


def test_the_worker_recycles_past_the_threshold(monkeypatch, tmp_path):
    killed = []
    monkeypatch.setattr(os, "kill", lambda pid, sig: killed.append((pid, sig)))
    monkeypatch.setattr(s, "_rss_mb", lambda: 5000)
    client = serve_app(monkeypatch, Wrapper(tmp_path), OVOS_TTS_PRIVATE="1", OVOS_TTS_RECYCLE_MB="4096")
    assert client.get("/status").status_code == 200  # nothing has grown yet: it is still checked after a synthesis
    assert client.get("/v2/synthesize", params={"utterance": "heavy"}).status_code == 200
    assert killed == [(os.getpid(), signal.SIGTERM)]  # the last synthesis ended: it asks to be restarted
    status = client.get("/status")
    assert status.status_code == 503 and status.json()["recycling"] is True and status.json()["private"] is True
    refused = client.get("/v2/synthesize", params={"utterance": "more"})
    assert refused.status_code == 503 and refused.headers["Retry-After"] == "5"
    assert len(killed) == 1  # asked once


def test_the_worker_waits_for_the_syntheses_running(monkeypatch, tmp_path):
    killed = []
    monkeypatch.setattr(os, "kill", lambda pid, sig: killed.append(sig))
    monkeypatch.setattr(s, "_rss_mb", lambda: 5000)
    held, running = threading.Event(), threading.Semaphore(0)
    wrapper = Wrapper(tmp_path, running=running)
    plain = wrapper.synthesize

    def synthesize(utterance, **params):
        if utterance == "slow":
            running.release()
            assert held.wait(10), "the test never let the slow line end"
        return plain(utterance, **params)

    wrapper.synthesize = synthesize
    client = serve_app(monkeypatch, wrapper, OVOS_TTS_PRIVATE="1", OVOS_TTS_CONCURRENCY="2",
                       OVOS_TTS_RECYCLE_MB="4096")
    slow = []
    thread = threading.Thread(target=lambda: slow.append(
        client.get("/v2/synthesize", params={"utterance": "slow"}).status_code))
    thread.start()
    assert running.acquire(timeout=10)
    # A quick line ends over the threshold while the slow one runs: draining starts, nobody is killed.
    assert client.get("/v2/synthesize", params={"utterance": "quick"}).status_code == 200
    assert killed == []
    assert client.get("/status").status_code == 503
    held.set()
    thread.join(10)
    assert slow == [200]  # the slow line was answered, then the process asked to be restarted
    assert killed == [signal.SIGTERM]


def test_no_recycling_when_the_threshold_is_zero(monkeypatch, tmp_path):
    killed = []
    monkeypatch.setattr(os, "kill", lambda pid, sig: killed.append(sig))
    monkeypatch.setattr(s, "_rss_mb", lambda: 10 ** 6)
    client = serve_app(monkeypatch, Wrapper(tmp_path), OVOS_TTS_PRIVATE="1", OVOS_TTS_RECYCLE_MB="0")
    assert client.get("/v2/synthesize", params={"utterance": "x"}).status_code == 200
    assert client.get("/status").status_code == 200 and killed == []


def test_rss_is_read_from_the_process():
    if not os.path.exists("/proc/self/statm"):
        pytest.skip("no /proc")
    assert 10 < s._rss_mb() < 100_000


def test_a_file_that_went_missing_is_made_again_once(tmp_path):
    calls = []
    real = tmp_path / "answer.wav"

    def synthesize(words):
        calls.append(words)
        if len(calls) > 1:
            real.write_bytes(b"RIFF")
        return str(real), None  # the first time the shared name is gone: another request took it away

    own = s._synthesize_with_own_file(synthesize, "x")
    assert len(calls) == 2
    assert own[0] != str(real) and os.path.exists(own[0])
    assert not real.exists()
    with pytest.raises(FileNotFoundError):  # a second time: it is an error, not a loop
        s._synthesize_with_own_file(lambda words: (str(tmp_path / "never.wav"), None), "x")
