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
`tts_transformers` configured, which reworks the file after the engine has written it. A finished
file that is not a WAV of plain samples (an engine that writes MP3) is answered as it is, with its
own media type, as `/v2/synthesize` answers it.

`ovos-tts-server-stream` is `ovos-tts-server` with this route added; same arguments.
"""
from __future__ import annotations

import hashlib
import logging
import os
import queue
import shutil
import struct
import sys
import tempfile
import threading
import wave
from collections.abc import Iterator
from typing import Any

from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.responses import FileResponse, StreamingResponse

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


class _Whole(Exception):
    """The engine's file cannot be read as a WAV of plain samples: it is answered as it is."""

    def __init__(self, path: Any) -> None:
        super().__init__(str(path))
        self.path = path


def _plain(clip: Any) -> bool:
    """Whether the samples are plain integers, the only kind the header sent here describes.

    From Python 3.15 the wave module also reads and writes float samples, and has `getformat()`
    to say so. Before that it refuses them, so whatever it opened is plain."""
    return not hasattr(clip, "getformat") or clip.getformat() == wave.WAVE_FORMAT_PCM


def _file(path: Any) -> Iterator[Piece]:
    if not os.path.getsize(str(path)):
        return  # a file with nothing in it is no audio: the route says so, as for no file at all
    try:
        clip = wave.open(str(path), "rb")
    except (wave.Error, EOFError) as error:  # MP3, or a WAV the wave module does not read
        raise _Whole(path) from error
    with clip:
        if not _plain(clip):
            raise _Whole(path)
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

    # No size limit, on purpose: the synthesis must not wait for a slow reader, because it also
    # fills the sentence cache. A slow reader therefore costs, at most, the samples of its own
    # utterance in memory (about 5.8 MB a minute at 48 kHz, 16 bits, mono).
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
        if not _plain(writer):
            return  # nothing is copied, so the finished file is answered, whole
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
        try:
            first = next(pieces, None)
        except _Whole as whole:
            return FileResponse(str(whole.path))
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


# -- the words are the author's ---------------------------------------------------------------
#
# Skill Studio's "Hear it" sends a skill author's words to this server. By default the stock
# server keeps and logs them: uvicorn's access log holds the whole request line (the utterance is
# in its query), phoonnx's text frontend logs the written forms it cannot read at WARNING, and the
# plugin writes every answer to a WAV under the temporary directory, named by a hash of the words,
# and never deletes it. With OVOS_TTS_PRIVATE=1 (off by default, so the public images behave as
# before):
#
# * no access log. **Nothing from the OVOS loggers or the libraries' loggers is written**, because
#   they quote the text at every level: phoonnx logs what it says at DEBUG (phoonnx.voice) and the
#   numbers it cannot read at ERROR ("failed to pronounce number: <word>", phoonnx.normalization),
#   text2spoken logs unread written forms at WARNING, and an exception that was never retrieved is
#   logged by asyncio with its message. The OVOS LOG has no CRITICAL method and no library calls
#   `.critical`, so its level (OVOS_DEFAULT_LOG_LEVEL, which is what it reads: "log_level" in
#   mycroft.conf is NOT read by this server) is forced to CRITICAL; the standard-library loggers of
#   those libraries and the root logger are at CRITICAL too (the root's level is what a logger
#   without a level of its own, such as asyncio's, inherits). What is left is uvicorn's own log,
#   which has levels of its own, with a filter that writes an exception by its type only, because
#   its message and traceback may quote the text; the request is answered 500 {"error": "internal"};
# * each request gets a file of its own (the shared hash name is deleted at once), deleted as soon as
#   its response has been sent or its synthesis failed; a sweeper in the pod's spec catches the answer
#   of a request that went away;
# * only /status and /v2/synthesize answer: the other routes (the JSON one reads a file and never
#   deletes it, the legacy one takes the words in the path, the documentation lists the rest) and the
#   CORS headers are gone;
# * GET /status says "private": true, which is what the API tells authors it may promise;
# * OVOS_TTS_CONCURRENCY=N (4 when unset, so that unset never means no limit) runs at most N syntheses
#   at once and answers 503 to the next: the server's worst case is N lines, whatever is asked and
#   however many clients gave up (it counts the threads still synthesising, not the connections).
#   Set it to the API's synthesis slots in all (3 per API replica). /status is not a synthesis and
#   never counts, so probes and the API's question still answer while the server is full. The server
#   runs one worker, one process;
# * the process recycles itself: the runtime keeps what the heaviest and most varied lines took (its
#   memory arenas grow to the largest shape each voice has seen and are never returned: replaying 106
#   heavy lines, 6 at a time, took the resident memory from 5.3 to 9.2 GB with no plateau, and a
#   handful of such lines from one address inside its limits would do it), so once the resident memory
#   passes OVOS_TTS_RECYCLE_MB (4096 when unset) the server stops taking syntheses (503 with
#   Retry-After, and /status answers 503 {"recycling": true}, so readiness fails and no traffic is
#   sent), waits for the syntheses running to end, and exits; the container's restart policy brings
#   it back with its memory returned;
# * the runtime's CPU memory arena is off (OVOS_TTS_NO_ARENA=0 turns it back on; the recycle exits
#   through SIGTERM, which is a restart each time: leave the arena off, where 600 fresh heavy lines
#   never reached the threshold): replaying the same 106
#   heavy lines, 6 at a time, the resident memory stayed near 2 GB (high-water 3.0 GB) instead of
#   growing to 7.8 GB, for 16 % more time a line (0.34 s against 0.30 s on 191 mixed lines).
# Standard-library loggers of the libraries that quote text. With the root logger at CRITICAL they
# need no line of their own unless they have a level of their own: belt and braces. asyncio's
# "Task exception was never retrieved" carries the exception's message.
PRIVATE_LOGGERS = ("text2spoken", "scriptconv", "phoonnx", "ovos_plugin_manager", "asyncio")
PRIVATE_ROUTES = frozenset({"/status", "/v2/synthesize"})


def _private() -> bool:
    return os.environ.get("OVOS_TTS_PRIVATE", "").strip().lower() in ("1", "true", "yes", "on")


def _forget(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def _concurrency() -> int:
    try:
        return max(1, int(os.environ.get("OVOS_TTS_CONCURRENCY", "").strip() or DEFAULT_CONCURRENCY))
    except ValueError:
        return DEFAULT_CONCURRENCY


DEFAULT_CONCURRENCY = 4
DEFAULT_RECYCLE_MB = 4096


def _recycle_mb() -> int:
    try:
        return int(os.environ.get("OVOS_TTS_RECYCLE_MB", "").strip() or DEFAULT_RECYCLE_MB)
    except ValueError:
        return DEFAULT_RECYCLE_MB


def _rss_mb() -> int:
    with open("/proc/self/statm") as statm:
        return int(statm.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") // (1024 * 1024)


class _Recycling:
    """Drain, then exit, once the resident memory is over the threshold."""

    def __init__(self, threshold_mb: int) -> None:
        self.threshold_mb = threshold_mb
        self.draining = threading.Event()
        self.running = 0
        self.lock = threading.Lock()
        self._exiting = False

    def enter(self) -> None:
        from fastapi import HTTPException

        with self.lock:
            if self.draining.is_set():
                raise HTTPException(status_code=503, detail="recycling", headers={"Retry-After": "5"})
            self.running += 1

    def leave(self) -> None:
        with self.lock:
            self.running -= 1
            if not self.draining.is_set() and self.threshold_mb > 0 and _rss_mb() > self.threshold_mb:
                self.draining.set()
            if self.draining.is_set() and self.running == 0 and not self._exiting:
                self._exiting = True
                # The last synthesis has ended: uvicorn finishes the responses it is sending, then the
                # container restarts with its memory returned.
                import signal

                os.kill(os.getpid(), signal.SIGTERM)


def _keep_no_words(engine: Any, recycling: "_Recycling | None" = None) -> None:
    """Give each request a file of its own, so that deleting it cannot take another's away; run
    at most OVOS_TTS_CONCURRENCY syntheses at once; and recycle when the memory has grown."""
    synthesize = engine.synthesize
    slots = threading.BoundedSemaphore(_concurrency())

    def synthesize_for_this_request(*args: Any, **kwargs: Any) -> Any:
        from fastapi import HTTPException

        if recycling is not None:
            recycling.enter()
        try:
            if not slots.acquire(blocking=False):
                raise HTTPException(status_code=503, detail="busy", headers={"Retry-After": "2"})
            try:
                return _synthesize_with_own_file(synthesize, *args, **kwargs)
            finally:
                slots.release()
        finally:
            if recycling is not None:
                recycling.leave()

    engine.synthesize = synthesize_for_this_request


def _synthesize_with_own_file(synthesize: Any, *args: Any, **kwargs: Any) -> Any:
    for attempt in (0, 1):
        result = synthesize(*args, **kwargs)
        path = os.fspath(result[0] if isinstance(result, tuple) else result)
        own = None
        try:
            handle, own = tempfile.mkstemp(suffix=".wav", dir=os.path.dirname(path))
            os.close(handle)
            shutil.copyfile(path, own)
        except FileNotFoundError:
            # A request for the same words had already taken the cached name away.
            if own:
                _forget(own)
            if attempt:
                raise
            continue
        except BaseException:
            # Whatever failed, neither the copy nor the shared name is left behind.
            if own:
                _forget(own)
            _forget(path)
            raise
        _forget(path)
        return (own, *result[1:]) if isinstance(result, tuple) else own


def _forgetful_file_response() -> Any:
    """FileResponse that deletes its file once the response has been sent, or could not be."""
    from fastapi.responses import FileResponse
    from starlette.background import BackgroundTask

    class ForgetfulFileResponse(FileResponse):
        def __init__(self, path: Any, *args: Any, **kwargs: Any) -> None:
            try:
                super().__init__(path, *args, background=BackgroundTask(_forget, os.fspath(path)),
                                 **kwargs)
            except BaseException:
                _forget(os.fspath(path))
                raise

    return ForgetfulFileResponse


class NoWords(logging.Filter):
    """Log an exception by its type only: its message and traceback may quote the text."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.exc_info:
            kind = getattr(record.exc_info[0], "__name__", "exception")
            record.msg, record.args = f"unhandled {kind} in a request (details withheld)", None
            record.exc_info = record.exc_text = None
        return True


def _private_log_config() -> dict:
    """uvicorn's own log configuration, with the filter above on every handler."""
    import copy

    from uvicorn.config import LOGGING_CONFIG

    config = copy.deepcopy(LOGGING_CONFIG)
    config.setdefault("filters", {})["no_words"] = {"()": "ovos_tts_stream.NoWords"}
    for handler in config.get("handlers", {}).values():
        handler["filters"] = [*handler.get("filters", []), "no_words"]
    return config


def _quiet_ovos_logs() -> None:
    """Write nothing from the OVOS loggers, whatever the environment or mycroft.conf say.

    The OVOS LOG has debug, info, warning, error and exception, and each is gated on its level, so
    CRITICAL (which no library calls) silences all of it, including the ERROR lines of phoonnx that
    quote the number it could not read."""
    os.environ["OVOS_DEFAULT_LOG_LEVEL"] = "CRITICAL"  # read when ovos_utils is imported
    try:
        from ovos_utils.log import LOG
    except ImportError:  # not installed: nothing of it logs
        return
    LOG.set_level("CRITICAL")  # and for what has been imported already


def _make_private(app: FastAPI, recycling: "_Recycling | None" = None) -> None:
    """Only the routes the API uses, no CORS, and /status says it is private."""
    import json

    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse

    app.router.routes[:] = [r for r in app.router.routes if getattr(r, "path", None) in PRIVATE_ROUTES]
    app.user_middleware = [m for m in app.user_middleware if m.cls is not CORSMiddleware]

    @app.exception_handler(Exception)
    async def say_nothing_of_it(request: Any, error: Exception) -> Any:
        # Starlette sends this, then raises the error again for the server to log: uvicorn's
        # handlers hold NoWords, which keeps the type and drops the message and the traceback.
        return JSONResponse({"error": "internal"}, status_code=500)

    @app.middleware("http")
    async def say_private(request: Any, call_next: Any) -> Any:
        response = await call_next(request)
        if request.url.path == "/status" and response.status_code == 200:
            body = b"".join([chunk async for chunk in response.body_iterator])
            if recycling is not None and recycling.draining.is_set():
                # Not ready: the memory is being returned. Readiness fails, no traffic is sent.
                return JSONResponse({**json.loads(body), "private": True, "recycling": True}, status_code=503)
            return JSONResponse({**json.loads(body), "private": True})
        return response


def main() -> None:
    """`ovos-tts-server` with the streaming route."""
    private = _private()
    if private:
        _quiet_ovos_logs()  # before ovos_utils is imported by the server
    import ovos_tts_server
    from ovos_tts_server.__main__ import main as serve

    create_app = ovos_tts_server.create_app

    def create_streaming_app(tts_engine: Any, *args: Any, **kwargs: Any) -> FastAPI:
        app = add_streaming(create_app(tts_engine, *args, **kwargs), tts_engine)
        if private:
            recycling = _Recycling(_recycle_mb())
            _keep_no_words(tts_engine, recycling)
            _make_private(app, recycling)
        return app

    if private:
        import functools

        import uvicorn

        # A logger without a level of its own (asyncio's, and any library's) follows the root's.
        # uvicorn's loggers have levels of their own, so the exception line below still comes out.
        logging.getLogger().setLevel(logging.CRITICAL)
        for name in PRIVATE_LOGGERS:
            logging.getLogger(name).setLevel(logging.CRITICAL)
        uvicorn.run = functools.partial(uvicorn.run, access_log=False, log_config=_private_log_config())
        if os.environ.get("OVOS_TTS_NO_ARENA", "1").strip().lower() in ("1", "true", "yes", "on"):
            import onnxruntime

            class NoArenaSessionOptions(onnxruntime.SessionOptions):
                def __init__(self) -> None:
                    super().__init__()
                    self.enable_cpu_mem_arena = False
                    self.enable_mem_pattern = False

            onnxruntime.SessionOptions = NoArenaSessionOptions
        ovos_tts_server.FileResponse = _forgetful_file_response()
    ovos_tts_server.create_app = create_streaming_app
    serve()


if __name__ == "__main__":
    main()
