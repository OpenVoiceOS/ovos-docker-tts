"""Streaming synthesis for ovos-tts-server.

`GET /v2/synthesize/stream?utterance=...&lang=...&voice=...` answers a WAV whose body is sent as
it is made. phoonnx synthesises one sentence at a time; the stock server waits for every sentence
before it answers, so a four-sentence reply is silent for four sentences. Here each sentence is
sent when it is done, so first audio costs one sentence, however long the text.

How: the request runs the server's own synthesis, the one `/v2/synthesize` runs, in a worker
thread, and the audio is copied to the client as the engine writes it to its WAV file. Nothing of
the engine is done again here, so the voice, the parameters, SSML, the voice cache and the
sentence cache are those of `/v2/synthesize`, whatever the version of the plugin.

The WAV header says the length is unknown (both size fields 0xFFFFFFFF), as streaming WAV does;
readers that need a length read to the end. Three cases are sent in one piece, from the finished
file, because only that is the audio `/v2/synthesize` gives: an utterance answered from the
sentence cache, an engine not known to write its file piece by piece, and a server with
`tts_transformers` configured, which reworks the file after the engine has written it.

`ovos-tts-server-stream` is `ovos-tts-server` with this route added; same arguments.
"""
from __future__ import annotations

import hashlib
import logging
import queue
import struct
import sys
import threading
import wave
from collections.abc import Iterator
from typing import Any

from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.responses import StreamingResponse

LOG = logging.getLogger("ovos_tts_stream")

UNKNOWN = 0xFFFFFFFF

# Plugins, by top-level module, known to write the finished audio to the WAV file as they make
# it. Any other plugin is answered in one piece from the file it returns: it may write a file
# and then rework it, and what was copied on the way would not be what it answers.
PROGRESSIVE = frozenset({"phoonnx"})

Piece = tuple[int, int, int, bytes]  # sample rate, channels, bytes a sample, PCM

_request = threading.local()
_writeframesraw = wave.Wave_write.writeframesraw


def _tee(self: wave.Wave_write, data: Any) -> None:
    """`Wave_write.writeframesraw`, which first hands the frames to the request being served by
    this thread, when there is one."""
    sink = getattr(_request, "sink", None)
    if sink is not None:
        try:
            sink(self, data)
        except Exception:  # the file still has to be written: /v2/synthesize depends on it
            _request.sink = None
            LOG.exception("stream: the audio could not be copied; this answer will stop short")
    _writeframesraw(self, data)


def install_tee() -> None:
    """Let a request see the frames its engine writes. Once a process; other threads, and
    requests that did not ask, write as before."""
    if wave.Wave_write.writeframesraw is not _tee:
        wave.Wave_write.writeframesraw = _tee  # type: ignore[method-assign]


def wav_header(rate: int, channels: int = 1, width: int = 2) -> bytes:
    """A RIFF/WAVE header for PCM of unknown length."""
    return (
        b"RIFF" + struct.pack("<I", UNKNOWN) + b"WAVE"
        + b"fmt " + struct.pack("<IHHIIHH", 16, 1, channels, rate, rate * channels * width,
                                channels * width, width * 8)
        + b"data" + struct.pack("<I", UNKNOWN)
    )


def _file(path: Any) -> Iterator[Piece]:
    with wave.open(str(path), "rb") as clip:
        rate, channels, width = clip.getframerate(), clip.getnchannels(), clip.getsampwidth()
        while data := clip.readframes(rate):  # a second at a time
            yield rate, channels, width, data


def _progressive(engine: Any) -> bool:
    """Whether what the plugin writes is what `/v2/synthesize` answers with."""
    if sys.byteorder != "little":
        return False  # the wave module swaps the bytes after this copy is taken
    if getattr(getattr(engine, "tts_transformers", None), "plugins", None):
        return False  # ovos-tts-server 1.15 reworks the file once the plugin has written it
    return type(engine.engine).__module__.partition(".")[0] in PROGRESSIVE


class _End:
    """The synthesis is over: the file it answered with, or why it failed."""

    def __init__(self, path: Any = None, error: BaseException | None = None) -> None:
        self.path, self.error = path, error


def iter_audio(engine: Any, text: str, **params: Any) -> Iterator[Piece]:
    """The audio of `text`, a piece at a time, each handed on when the engine has written it.

    `params` go to the engine untouched, as `/v2/synthesize` passes them."""
    if not _progressive(engine):
        path, _ = engine.synthesize(text, **params)
        yield from _file(path)
        return

    pieces: queue.SimpleQueue[Piece | _End] = queue.SimpleQueue()
    writers: list[wave.Wave_write] = []
    gone = threading.Event()  # the reader left: nothing more is worth copying

    def sink(writer: wave.Wave_write, data: Any) -> None:
        if gone.is_set():
            return
        if not writers:
            writers.append(writer)
        if writer is not writers[0]:
            return  # an utterance is one file; a second one is not the answer
        pcm = bytes(data) if isinstance(data, (bytes, bytearray)) else bytes(
            memoryview(data).cast("B"))
        if pcm:
            pieces.put((writer.getframerate(), writer.getnchannels(), writer.getsampwidth(), pcm))

    def synthesise() -> None:
        _request.sink = sink
        # Whatever ends this thread, the request is told: it is waiting on the queue.
        end = _End(error=RuntimeError("the synthesis stopped without an answer"))
        try:
            path, _ = engine.synthesize(text, **params)
            end = _End(path=path)
        except Exception as error:  # noqa: BLE001 - raised again, by the request it belongs to
            end = _End(error=error)
        finally:
            _request.sink = None
            pieces.put(end)

    threading.Thread(target=synthesise, name="tts-stream", daemon=True).start()
    sent, digest = 0, hashlib.blake2b()
    try:
        while True:
            piece = pieces.get()
            if isinstance(piece, _End):
                if piece.error is not None:
                    raise piece.error
                if not sent:  # from the sentence cache: nothing was written this time
                    yield from _file(piece.path)
                else:
                    _compare(piece.path, sent, digest.digest())
                return
            sent += len(piece[3])
            digest.update(piece[3])
            yield piece
    finally:
        # The synthesis runs on to its end, for the caches' sake, but no longer into the queue.
        gone.set()


def _compare(path: Any, sent: int, digest: bytes) -> None:
    """Say so when the file the engine answered with is not what was sent on the way."""
    try:
        with wave.open(str(path), "rb") as clip:
            held = clip.readframes(clip.getnframes())
    except (OSError, EOFError, wave.Error) as error:
        LOG.warning("stream: sent %d bytes of audio, but the file cannot be read: %s", sent, error)
        return
    if len(held) != sent or hashlib.blake2b(held).digest() != digest:
        LOG.warning("stream: the %d bytes of audio sent are not the %d the file holds; "
                    "/v2/synthesize would have answered differently", sent, len(held))


def make_stream_router(engine: Any) -> Any:
    install_tee()
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
        rate, channels, width, _ = first

        def body() -> Iterator[bytes]:
            try:
                yield wav_header(rate, channels, width)
                yield first[3]
                for r, c, w, pcm in pieces:
                    if (r, c, w) != (rate, channels, width):
                        return  # the header is already sent; a different format cannot follow
                    yield pcm
            finally:
                pieces.close()

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

    def create_streaming_app(tts_engine: Any, *args: Any, **kwargs: Any) -> FastAPI:
        # Whatever else the server passes (newer versions add enable_mcp) is its own business.
        return add_streaming(create_app(tts_engine, *args, **kwargs), tts_engine)

    ovos_tts_server.create_app = create_streaming_app
    serve()


if __name__ == "__main__":
    main()
