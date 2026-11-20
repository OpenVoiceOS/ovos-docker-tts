import logging
import queue
import struct
import sys
import threading
import time
import types
import wave

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import ovos_tts_stream as s


def pcm(samples, value):
    return struct.pack("<h", value) * samples


def sentence(i):
    """What the engine below writes for the i-th sentence of a text."""
    return pcm(100 + i, i + 1)


class Plugin:
    """Stands for the phoonnx plugin; only where it lives is read."""


Plugin.__module__ = "phoonnx.opm"


class OtherPlugin:
    """A plugin nobody has checked to write its file as it goes."""


class Engine:
    """ovos-tts-server's engine wrapper, over a plugin that writes its WAV a sentence at a
    time, as phoonnx does."""

    def __init__(self, folder, plugin=None, rate=22050, gate=None):
        self.engine = plugin or Plugin()
        self.folder, self.rate, self.gate = folder, rate, gate
        self.calls = []
        self.written = []

    def synthesize(self, text, **params):
        self.calls.append((text, params))
        path = self.folder / f"{len(self.calls)}.wav"
        with wave.open(str(path), "wb") as out:
            out.setnchannels(1), out.setsampwidth(2), out.setframerate(self.rate)
            for i, _ in enumerate(text.split(". ")):
                if i and self.gate is not None:
                    assert self.gate.wait(5), "the reader never came back for more"
                out.writeframes(sentence(i))
                self.written.append(i)
        return str(path), None


def frames(path):
    with wave.open(str(path), "rb") as clip:
        return clip.readframes(clip.getnframes())


def a_file(path, data, rate=16000):
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1), out.setsampwidth(2), out.setframerate(rate)
        out.writeframes(data)
    return str(path)


@pytest.fixture(autouse=True)
def tee(monkeypatch):
    # What add_streaming() does to the wave module, undone after each test.
    monkeypatch.setattr(wave.Wave_write, "writeframesraw", s._tee)


def client(engine):
    app = FastAPI()
    s.add_streaming(app, engine)
    return TestClient(app)


def test_header_says_length_is_unknown_and_carries_the_format():
    head = s.wav_header(22050)
    assert head[:4] == b"RIFF" and struct.unpack("<I", head[4:8])[0] == 0xFFFFFFFF
    assert struct.unpack("<IHHII", head[16:32])[1:] == (1, 1, 22050, 44100)
    assert struct.unpack("<HH", s.wav_header(48000, 2, 3)[32:36]) == (6, 24)


def test_each_sentence_arrives_in_order_after_one_header(tmp_path):
    engine = Engine(tmp_path, rate=44100)
    r = client(engine).get("/v2/synthesize/stream", params={"utterance": "One. Two. Three"})
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav"
    assert r.content[:4] == b"RIFF" and struct.unpack("<I", r.content[24:28])[0] == 44100
    assert r.content[44:] == sentence(0) + sentence(1) + sentence(2)


def test_the_answer_is_the_file_the_engine_wrote(tmp_path):
    r = client(Engine(tmp_path)).get("/v2/synthesize/stream", params={"utterance": "One. Two"})
    assert r.content[44:] == frames(tmp_path / "1.wav")


def test_the_first_sentence_is_sent_before_the_second_is_written(tmp_path):
    gate = threading.Event()
    engine = Engine(tmp_path, gate=gate)
    pieces = s.iter_audio(engine, "One. Two")
    assert next(pieces)[3] == sentence(0)
    assert 1 not in engine.written  # the engine is waiting for the gate; the reader has audio
    gate.set()
    assert b"".join(piece[3] for piece in pieces) == sentence(1)


def test_request_parameters_reach_the_engine_untouched(tmp_path):
    engine = Engine(tmp_path)
    client(engine).get("/v2/synthesize/stream", params={
        "utterance": "x", "voice": "asked/voice", "lang": "fr-FR", "length_scale": "1.2"})
    assert engine.calls == [("x", {"voice": "asked/voice", "lang": "fr-FR", "length_scale": "1.2"})]


def test_missing_utterance_is_a_400(tmp_path):
    assert client(Engine(tmp_path)).get("/v2/synthesize/stream").status_code == 400


@pytest.mark.parametrize("plugin", [Plugin, OtherPlugin])
def test_an_engine_that_fails_says_so_with_a_status(tmp_path, plugin):
    engine = Engine(tmp_path, plugin())

    def fail(text, **params):
        raise RuntimeError("no such voice")

    engine.synthesize = fail
    with pytest.raises(RuntimeError, match="no such voice"):
        client(engine).get("/v2/synthesize/stream", params={"utterance": "x"})
    assert TestClient(client(engine).app, raise_server_exceptions=False).get(
        "/v2/synthesize/stream", params={"utterance": "x"}).status_code == 500


def test_text_that_gives_no_audio_is_a_422(tmp_path):
    engine = Engine(tmp_path)
    engine.synthesize = lambda text, **params: (a_file(tmp_path / "empty.wav", b""), None)
    assert client(engine).get("/v2/synthesize/stream", params={"utterance": "..."}).status_code == 422


def test_an_answer_from_the_sentence_cache_is_sent_whole(tmp_path):
    cached = a_file(tmp_path / "cached.wav", pcm(40000, 7))
    engine = Engine(tmp_path)
    engine.synthesize = lambda text, **params: (cached, None)  # nothing is written this time
    r = client(engine).get("/v2/synthesize/stream", params={"utterance": "hi"})
    assert r.status_code == 200 and r.content[44:] == pcm(40000, 7)
    assert struct.unpack("<I", r.content[24:28])[0] == 16000


def test_a_plugin_not_known_to_write_as_it_goes_is_answered_from_its_file(tmp_path):
    engine = Engine(tmp_path, OtherPlugin())
    draft = engine.synthesize

    def rework(text, **params):
        draft(text, **params)  # written a sentence at a time, then replaced
        return a_file(tmp_path / "final.wav", pcm(500, 9)), None

    engine.synthesize = rework
    r = client(engine).get("/v2/synthesize/stream", params={"utterance": "One. Two"})
    assert r.content[44:] == pcm(500, 9)


class Mp3Engine:
    """An engine whose plugin writes MP3, as ovos-tts-plugin-google-tx does."""

    def __init__(self, folder, plugin=None):
        self.engine = plugin or OtherPlugin()
        self.folder = folder

    def synthesize(self, text, **params):
        path = self.folder / "answer.mp3"
        path.write_bytes(b"ID3" + text.encode())
        return str(path), None


@pytest.mark.parametrize("plugin", [OtherPlugin, Plugin])
def test_a_file_that_is_not_a_wav_is_answered_as_it_is(tmp_path, plugin):
    # /v2/synthesize answers with the file itself; a 500 here would be a worse answer than that.
    # With the phoonnx plugin the same holds for an answer from the sentence cache.
    r = client(Mp3Engine(tmp_path, plugin())).get("/v2/synthesize/stream",
                                                  params={"utterance": "One. Two"})
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/mpeg"
    assert r.content == b"ID3One. Two"


def test_a_wav_the_wave_module_cannot_read_is_answered_as_it_is(tmp_path):
    class FloatEngine(Mp3Engine):
        def synthesize(self, text, **params):
            path = self.folder / "answer.wav"
            # format tag 3: IEEE float samples, which the wave module refuses
            path.write_bytes(b"RIFF" + struct.pack("<I", 40) + b"WAVEfmt " + struct.pack(
                "<IHHIIHH", 16, 3, 1, 16000, 64000, 4, 32) + b"data" + struct.pack("<I", 4) + bytes(4))
            return str(path), None

    r = client(FloatEngine(tmp_path)).get("/v2/synthesize/stream", params={"utterance": "One"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("audio/")
    assert r.content[:4] == b"RIFF" and len(r.content) == 48


def test_a_second_file_written_for_the_same_request_is_not_sent(tmp_path):
    engine = Engine(tmp_path)
    answer = engine.synthesize

    def with_a_side_file(text, **params):
        result = answer(text, **params)
        a_file(tmp_path / "side.wav", pcm(300, 5))
        return result

    engine.synthesize = with_a_side_file
    r = client(engine).get("/v2/synthesize/stream", params={"utterance": "One. Two"})
    assert r.content[44:] == sentence(0) + sentence(1)


def test_it_says_so_when_the_file_is_not_what_was_sent(tmp_path, caplog):
    engine = Engine(tmp_path)
    answer = engine.synthesize

    def reworked(text, **params):
        answer(text, **params)
        return a_file(tmp_path / "final.wav", pcm(500, 9)), None

    engine.synthesize = reworked
    with caplog.at_level(logging.WARNING, logger="ovos_tts_stream"):
        list(s.iter_audio(engine, "One. Two"))
    assert "would have answered differently" in caplog.text


def test_two_requests_at_once_each_get_their_own_audio(tmp_path):
    both_writing = threading.Barrier(2, timeout=5)

    class Busy(Engine):
        def synthesize(self, text, **params):
            path = self.folder / f"{text}.wav"
            with wave.open(str(path), "wb") as out:
                out.setnchannels(1), out.setsampwidth(2), out.setframerate(self.rate)
                out.writeframes(pcm(200, len(text)))
                both_writing.wait()  # both requests are now half-way through their file
                out.writeframes(pcm(300, len(text)))
            return str(path), None

    engine, got = Busy(tmp_path), {}

    def ask(text):
        got[text] = b"".join(piece[3] for piece in s.iter_audio(engine, text))

    askers = [threading.Thread(target=ask, args=(text,)) for text in ("ab", "abcdef")]
    for asker in askers:
        asker.start()
    for asker in askers:
        asker.join(10)
    assert got == {"ab": pcm(500, 2), "abcdef": pcm(500, 6)}


def test_a_file_written_outside_a_request_is_left_alone(tmp_path):
    client(Engine(tmp_path))  # the route is installed
    assert frames(a_file(tmp_path / "plain.wav", pcm(10, 3))) == pcm(10, 3)


def test_the_launcher_hands_create_app_whatever_the_server_passes(tmp_path, monkeypatch):
    seen = {}
    server = types.ModuleType("ovos_tts_server")

    def create_app(engine, enable_mcp=False):
        seen["enable_mcp"] = enable_mcp
        return FastAPI()

    def serve():  # as ovos-tts-server 1.15 starts: it looks create_app up, and passes a keyword
        seen["app"] = server.create_app(Engine(tmp_path), enable_mcp=True)

    server.create_app = create_app
    entry = types.ModuleType("ovos_tts_server.__main__")
    entry.main = serve
    monkeypatch.setitem(sys.modules, "ovos_tts_server", server)
    monkeypatch.setitem(sys.modules, "ovos_tts_server.__main__", entry)
    s.main()
    assert seen["enable_mcp"] is True
    # The route is there: without an utterance it answers 400, not 404.
    assert TestClient(seen["app"]).get("/v2/synthesize/stream").status_code == 400


def test_with_tts_transformers_configured_the_finished_file_is_sent(tmp_path):
    engine = Engine(tmp_path)
    engine.tts_transformers = types.SimpleNamespace(plugins=["a-transformer"])
    written = engine.synthesize

    def transformed(text, **params):
        written(text, **params)  # the plugin writes its sentences; the server then reworks a copy
        return a_file(tmp_path / "transformed.wav", pcm(201, 9), rate=22050), None

    engine.synthesize = transformed
    r = client(engine).get("/v2/synthesize/stream", params={"utterance": "One. Two"})
    assert r.content[44:] == pcm(201, 9)  # the same length as what was written, other samples


def test_a_server_with_no_transformer_loaded_still_sends_as_it_goes(tmp_path):
    engine = Engine(tmp_path)
    engine.tts_transformers = types.SimpleNamespace(plugins=[])
    assert s._progressive(engine)
    engine.tts_transformers = types.SimpleNamespace(plugins=["a-transformer"])
    assert not s._progressive(engine)


def test_it_says_so_when_the_file_differs_at_the_same_length(tmp_path, caplog):
    engine = Engine(tmp_path)
    written = engine.synthesize

    def reworked(text, **params):
        written(text, **params)
        return a_file(tmp_path / "same-length.wav", pcm(201, 9), rate=22050), None

    engine.synthesize = reworked
    with caplog.at_level(logging.WARNING, logger="ovos_tts_stream"):
        list(s.iter_audio(engine, "One. Two"))
    assert "would have answered differently" in caplog.text


def test_when_the_reader_leaves_nothing_more_is_copied(tmp_path, monkeypatch):
    puts, real = [], queue.SimpleQueue

    class Recording:
        """The queue between the engine's thread and the reader, with a note of every put."""

        def __init__(self):
            self.inner = real()

        def put(self, item):
            puts.append(item)
            self.inner.put(item)

        def get(self):
            return self.inner.get()

    monkeypatch.setattr(s.queue, "SimpleQueue", Recording)
    gate = threading.Event()
    engine = Engine(tmp_path, gate=gate)
    pieces = s.iter_audio(engine, "One. Two")
    assert next(pieces)[3] == sentence(0)
    pieces.close()  # the reader has gone
    gate.set()  # the engine goes on to its second sentence, for the caches
    deadline = time.time() + 5
    while not any(isinstance(item, s._End) for item in puts) and time.time() < deadline:
        time.sleep(0.01)
    assert engine.written == [0, 1]  # the synthesis ran to its end
    assert [item[3] for item in puts if not isinstance(item, s._End)] == [sentence(0)]
