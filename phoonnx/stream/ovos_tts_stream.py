"""Streaming synthesis for ovos-tts-server.

`GET /v2/synthesize/stream?utterance=...&lang=...&voice=...` answers a WAV whose body is sent as
it is made. phoonnx already synthesises one sentence at a time (`TTSVoice.synthesize` is a
generator); the stock server collects every sentence into one file before answering, so a
four-sentence reply is silent for four sentences. Here each sentence is sent when it is done, so
first audio costs one sentence, however long the text.

The WAV header says the length is unknown (both size fields 0xFFFFFFFF), as streaming WAV does;
readers that need a length read to the end. Engines that cannot stream (piper, kokoro, ...)
still answer this route, as one piece: the same bytes a client would have got from /v2/synthesize.

`ovos-tts-server-stream` is `ovos-tts-server` with this route added; same arguments.
"""
from __future__ import annotations

import struct
import wave
from collections.abc import Iterator
from typing import Any

from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.responses import StreamingResponse

UNKNOWN = 0xFFFFFFFF


def wav_header(rate: int, channels: int = 1, width: int = 2) -> bytes:
    """A RIFF/WAVE header for PCM of unknown length."""
    return (
        b"RIFF" + struct.pack("<I", UNKNOWN) + b"WAVE"
        + b"fmt " + struct.pack("<IHHIIHH", 16, 1, channels, rate, rate * channels * width,
                                channels * width, width * 8)
        + b"data" + struct.pack("<I", UNKNOWN)
    )


def _synth_config(plugin: Any, voice_info: Any) -> Any:
    """The SynthesisConfig `PhoonnxTTSPlugin.get_tts` builds, from the plugin's own settings."""
    from phoonnx.voice import SynthesisConfig

    cfg = plugin._cfg_opt
    return SynthesisConfig(
        speaker_id=plugin._resolve_speaker(voice_info),
        enable_phonetic_spellings=cfg(
            voice_info.config.enable_phonetic_spellings
            if hasattr(voice_info.config, "enable_phonetic_spellings") else True,
            "enable_phonetic_spellings", "enable_phonetic_spelling"),
        add_diacritics=cfg(voice_info.config.add_diacritics, "add_diacritics"),
        noise_scale=cfg(voice_info.config.noise_scale, "noise_scale", "noise-scale"),
        length_scale=cfg(voice_info.config.length_scale, "length_scale", "length-scale"),
        noise_w_scale=cfg(voice_info.config.noise_w_scale, "noise_w_scale", "noise_w", "noise-w"),
        speaker_reference=cfg(None, "speaker_reference", "ref_wav", "clone_voice"),
        speaker_reference_text=cfg(None, "speaker_reference_text", "ref_text"),
        speaker_reference_lang=cfg(None, "speaker_reference_lang", "ref_lang"),
        super_resolution=bool(cfg(False, "super_resolution")),
        super_resolution_model=cfg(None, "super_resolution_model"),
    )


def _phoonnx(plugin: Any, text: str, lang: str | None, voice: str | None
             ) -> Iterator[tuple[int, int, bytes]]:
    if voice and voice != "default":
        model = plugin.get_model(voice)
        voice_info = plugin.model_manager.voices[voice]
    else:
        voice_info = plugin.get_default_voice(lang or plugin.lang)
        model = plugin.get_model(voice_info.voice_id)
    for chunk in model.synthesize(text, _synth_config(plugin, voice_info)):
        yield chunk.sample_rate, chunk.sample_channels, chunk.audio_int16_bytes


def _whole(engine: Any, text: str, params: dict[str, Any]) -> Iterator[tuple[int, int, bytes]]:
    path, _ = engine.synthesize(text, **params)
    with wave.open(path, "rb") as clip:
        rate, channels = clip.getframerate(), clip.getnchannels()
        while data := clip.readframes(rate):  # a second at a time
            yield rate, channels, data


def iter_audio(engine: Any, text: str, **params: Any) -> Iterator[tuple[int, int, bytes]]:
    """(rate, channels, PCM) pieces of `text`, each made as it is asked for."""
    plugin = engine.engine
    text = plugin.validate_ssml(text)
    if all(hasattr(plugin, name) for name in ("get_model", "get_default_voice", "model_manager")):
        # The request resolved as /v2/synthesize resolves it: the configured voice when none is
        # asked for, and only the arguments get_tts takes.
        kwargs = plugin._get_ctxt(dict(params)).synth_kwargs
        return _phoonnx(plugin, text, kwargs.get("lang"), kwargs.get("voice"))
    return _whole(engine, text, params)


def make_stream_router(engine: Any) -> Any:

    router = APIRouter()

    @router.get("/v2/synthesize/stream")
    def synth_stream(request: Request) -> Response:
        params = dict(request.query_params)
        utterance = params.pop("utterance", None)
        if not utterance:
            return Response('{"error": "Missing utterance"}', status_code=400,
                            media_type="application/json")
        pieces = iter_audio(engine, utterance, **params)
        # The first piece is made before the answer starts, so an engine that fails says so
        # with a status, not with a body that stops.
        first = next(pieces, None)
        if first is None:
            return Response('{"error": "No audio"}', status_code=422,
                            media_type="application/json")
        rate, channels, _ = first

        def body() -> Iterator[bytes]:
            yield wav_header(rate, channels)
            yield first[2]
            for r, c, pcm in pieces:
                if (r, c) != (rate, channels):
                    return  # the header is already sent; a different format cannot follow
                yield pcm

        return StreamingResponse(body(), media_type="audio/wav", headers={
            "Cache-Control": "no-store", "X-Accel-Buffering": "no"})

    return router


def add_streaming(app: FastAPI, engine: Any) -> FastAPI:
    app.include_router(make_stream_router(engine))
    return app


def main() -> None:
    """`ovos-tts-server` with the streaming route."""
    import ovos_tts_server
    from ovos_tts_server.__main__ import main as serve

    create_app = ovos_tts_server.create_app

    def create_streaming_app(tts_engine: Any) -> FastAPI:
        return add_streaming(create_app(tts_engine), tts_engine)

    ovos_tts_server.create_app = create_streaming_app
    serve()


if __name__ == "__main__":
    main()
