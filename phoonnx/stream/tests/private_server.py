"""A private-mode server in its own process, for tests/test_private_process.py.

`python private_server.py PORT FOLDER`: the real `ovos_tts_stream.main()`, the real
`ovos_tts_server.create_app` and the real uvicorn, over an engine that logs the way phoonnx does
(`ovos_utils` LOG at DEBUG and INFO, the standard-library logger text2spoken at WARNING) and that
raises, with the text in the message, when asked for `boom=1`.
"""
import logging
import sys
import types
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import ovos_tts_stream as s  # noqa: E402  (imports no OVOS module)

port, folder = int(sys.argv[1]), Path(sys.argv[2])


class Plugin:
    config = {}


Plugin.__module__ = "phoonnx.opm"


class Wrapper:
    plugin_name = "ovos-tts-plugin-phoonnx"
    langs, lang, voices = ["en-us"], "en-us", []
    dialog_transformers = tts_transformers = None

    def __init__(self):
        self.engine = Plugin()
        self.count = 0

    def synthesize(self, utterance, **params):
        from ovos_utils.log import LOG  # imported late, as the plugins do

        LOG.debug("text=%s", utterance)  # phoonnx.voice.prepare does this
        LOG.info("saying %s", utterance)
        logging.getLogger("text2spoken").warning("unread written form %r", utterance)
        if params.get("boom"):
            raise ValueError(f"cannot say {utterance}")
        self.count += 1
        path = folder / f"{self.count}.wav"
        with wave.open(str(path), "wb") as out:
            out.setnchannels(1), out.setsampwidth(2), out.setframerate(22050)
            out.writeframes(b"\x01\x00" * 500)
        return str(path), None


def serve():
    import ovos_tts_server
    import uvicorn

    uvicorn.run(ovos_tts_server.create_app(Wrapper()), host="127.0.0.1", port=port)


entry = types.ModuleType("ovos_tts_server.__main__")
entry.main = serve
sys.modules["ovos_tts_server.__main__"] = entry
s.main()
