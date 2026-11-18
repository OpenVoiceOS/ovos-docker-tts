import io
import struct
import sys
import types
import wave

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import ovos_tts_stream as s


class Chunk:
    def __init__(self, n, rate=22050):
        self.sample_rate, self.sample_channels = rate, 1
        self.audio_int16_bytes = (np.arange(n, dtype=np.int16)).tobytes()


class Voice:
    def __init__(self, log):
        self.log = log

    def synthesize(self, text, config):
        for i, sentence in enumerate(text.split(". ")):
            self.log.append(("made", i))  # a sentence is made only when the reader asks for it
            yield Chunk(100 + i)


class Plugin:
    lang = "en-US"
    log: list = []

    def __init__(self):
        self.model_manager = types.SimpleNamespace(voices={"configured/voice": self.get_default_voice("x"),
                                                           "asked/voice": self.get_default_voice("x")})

    voice = "configured/voice"

    def _get_ctxt(self, kwargs):
        kwargs = dict(kwargs)
        kwargs.setdefault("voice", self.voice)
        return types.SimpleNamespace(synth_kwargs=kwargs)

    def validate_ssml(self, text):
        return text

    def get_default_voice(self, lang):
        return types.SimpleNamespace(voice_id="v", config=types.SimpleNamespace(
            add_diacritics=False, noise_scale=0.6, length_scale=1.0, noise_w_scale=0.8))

    def get_model(self, voice):
        self.log.append(("voice", voice))
        return Voice(self.log)

    def _cfg_opt(self, default, *keys):
        return default

    def _resolve_speaker(self, info):
        return None


@pytest.fixture(autouse=True)
def fake_phoonnx(monkeypatch):
    mod = types.ModuleType("phoonnx.voice")
    mod.SynthesisConfig = lambda **kw: kw
    monkeypatch.setitem(sys.modules, "phoonnx", types.ModuleType("phoonnx"))
    monkeypatch.setitem(sys.modules, "phoonnx.voice", mod)
    Plugin.log = []


def client(plugin):
    app = FastAPI()
    s.add_streaming(app, types.SimpleNamespace(engine=plugin, synthesize=None))
    return TestClient(app)


def test_header_says_length_is_unknown_and_reads_as_wav_to_the_end():
    head = s.wav_header(22050)
    assert head[:4] == b"RIFF" and struct.unpack("<I", head[4:8])[0] == 0xFFFFFFFF
    assert struct.unpack("<IHHII", head[16:32])[1:] == (1, 1, 22050, 44100)


def test_each_sentence_arrives_in_order_after_one_header():
    r = client(Plugin()).get("/v2/synthesize/stream", params={"utterance": "One. Two. Three"})
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav"
    body = r.content
    assert body[:4] == b"RIFF"
    assert len(body) - 44 == 2 * (100 + 101 + 102)
    assert Plugin.log == [("voice", "configured/voice"), ("made", 0), ("made", 1), ("made", 2)]


def test_a_voice_in_the_request_wins_over_the_configured_one():
    client(Plugin()).get("/v2/synthesize/stream", params={"utterance": "x", "voice": "asked/voice"})
    assert ("voice", "asked/voice") in Plugin.log


def test_the_second_sentence_is_not_made_before_the_first_was_sent():
    pieces = s.iter_audio(types.SimpleNamespace(engine=Plugin()), "One. Two")
    next(pieces)
    assert ("made", 0) in Plugin.log and ("made", 1) not in Plugin.log


def test_missing_utterance_is_a_400():
    assert client(Plugin()).get("/v2/synthesize/stream").status_code == 400


def test_an_engine_that_fails_says_so_with_a_status():
    plugin = Plugin()
    plugin.get_model = lambda v: (_ for _ in ()).throw(RuntimeError("no voice"))
    with pytest.raises(RuntimeError):
        client(plugin).get("/v2/synthesize/stream", params={"utterance": "x"})


def test_engines_that_cannot_stream_answer_in_one_piece(tmp_path):
    path = tmp_path / "a.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(16000)
        w.writeframes(b"\1\0" * 40000)
    plain = types.SimpleNamespace(validate_ssml=lambda t: t)  # no get_model: not phoonnx
    engine = types.SimpleNamespace(engine=plain, synthesize=lambda t, **kw: (str(path), None))
    app = FastAPI()
    s.add_streaming(app, engine)
    r = TestClient(app).get("/v2/synthesize/stream", params={"utterance": "hi"})
    assert r.status_code == 200 and len(r.content) - 44 == 80000
    assert struct.unpack("<IHHI", r.content[16:28])[3] == 16000


def test_phoonnx_1_3_plugin_without_cfg_opt_still_streams():
    class Legacy(Plugin):
        _cfg_opt = None

    plugin = Legacy()
    plugin.config = {"noise-scale": 0.3}
    cfg = s._synth_config(plugin, plugin.get_default_voice("x"))
    assert cfg["noise_scale"] == 0.3 and cfg["length_scale"] == 1.0
    assert "speaker_id" not in cfg
