# ovos-docker-tts

Dockerfiles and Compose stacks that package each [OpenVoiceOS](https://github.com/OpenVoiceOS) text-to-speech plugin as a self-contained `ovos-tts-server` HTTP container. Each engine builds on a shared base image and exposes port 9666.

## Install

This repository has no Python package and no install step. It only builds OCI images.

Build the base image first, then an engine image:

```sh
docker build -t smartgic/ovos-tts-server-base:alpha base/
docker build --build-arg TAG=alpha -t smartgic/ovos-tts-server-piper:alpha piper/
```

CUDA variants use `Dockerfile.cuda` and build on `smartgic/ovos-tts-server-base-cuda`. CUDA images exist for `base`, `piper`, and `phoonnx`.

The `phoonnx` images are different in two points. They do not build on the base image. Their build context is the repository root, not the `phoonnx/` directory, because they install the package in `phoonnx/stream`:

```sh
docker build -f phoonnx/Dockerfile -t smartgic/ovos-tts-server-phoonnx:alpha .
docker build -f phoonnx/Dockerfile.cuda -t smartgic/ovos-tts-server-phoonnx-cuda:alpha .
```

Their entrypoint is `ovos-tts-server-stream`. It is `ovos-tts-server` with one more route, `GET /v2/synthesize/stream`, which sends the audio while the engine makes it.

### Private mode

Set `OVOS_TTS_PRIVATE=1` on a `phoonnx` image when the server is given text that its author owns (Skill Studio's "Hear it" is the first user). It is off by default, so the public images behave as before. With it on:

- The server writes no access log (the access log holds the request line, and the text is in it).
- Nothing from the OVOS loggers or the libraries' loggers is written, because they quote the text at every level: phoonnx logs what it says at `DEBUG` and the number it cannot read at `ERROR` (`failed to pronounce number: <word>`), `text2spoken` logs unread written forms at `WARNING`, and asyncio logs an exception nobody retrieved with its message. Private mode sets the OVOS log level to `CRITICAL` (the OVOS `LOG` has no critical method and no library calls `.critical`, so nothing is written), and the root logger and those libraries' standard loggers to `CRITICAL`. The level comes from the environment variable `OVOS_DEFAULT_LOG_LEVEL`; **`log_level` in `mycroft.conf` is not read by this server**. A higher setting is ignored in private mode. The cost is that the OVOS stack's own errors are not in the log either; an exception in a request is still logged, by its type (below). Only uvicorn's own lines (start, stop, that exception line) are written.
- An exception in a request is answered `500 {"error": "internal"}` and logged by its type only: its message and traceback can quote the text.
- Each request has its own answer file, deleted as soon as the answer is sent or the synthesis fails. A sweeper in the pod must remove the file of a request that went away.
- Only `GET /status` and `GET /v2/synthesize` are served. The other routes and the CORS headers are removed. `/v2/synthesize/stream` is removed too: it reads plain text, not SSML.
- `GET /status` has `"private": true`. Clients show a promise of privacy only when they read it.
- `OVOS_TTS_CONCURRENCY=N` is the number of syntheses that can run at once (4 when unset). The next request gets `503` with `Retry-After`. `/status` never counts. Run one worker.
- The process recycles itself when its resident memory passes `OVOS_TTS_RECYCLE_MB` (4096 when unset, 0 turns it off). It stops taking syntheses (`503`, and `/status` answers `503 {"recycling": true}`), waits for the running ones, and exits. The container must restart it. The exit status is **0 in a container** (the process is PID 1, and the kernel gives PID 1 no signal that has the default action, so uvicorn's last SIGTERM does nothing) and **143 (SIGTERM) anywhere else**, for example under `docker run --init` or `shareProcessNamespace`. Both are a restart with `restartPolicy: Always`. During a recycle (a few seconds to load the voices again) the server answers `503`; with one replica and the `Recreate` strategy that is a short outage, which clients must treat as "use another voice".
- The CPU memory arena of ONNX Runtime is off (`OVOS_TTS_NO_ARENA=0` turns it on again). With the arena on, the resident memory grows with the heaviest lines and is never returned.

The image entrypoint ends with `--cache`, which stores every answer on disk. For a private server, override `command` and `args` and do not pass `--cache`:

```sh
ovos-tts-server-stream --engine ovos-tts-plugin-phoonnx --host 0.0.0.0 --port 9666
```

Size the memory limit as `1.15 x (OVOS_TTS_RECYCLE_MB + N x 0.53 GiB)`: 6.5Gi for N = 3 and 8.5Gi for N = 6 at the default threshold.

Images publish to the Docker Hub `smartgic/` namespace. The image labels still point back to this repository as the source.

## Usage

Copy `.env` and set `CONFIG_FOLDER`, `OVOS_USER`, `TZ`, and `VERSION` for your setup, then start the engines you need with Compose:

```sh
docker compose up -d
docker compose -f docker-compose.cuda.yml up -d
```

`docker-compose.yml` runs the CPU engines (Piper, Mimic3, Mimic, Google Translate, SAM, Matxa, NOS, Kokoro, Phoonnx, Coqui, Bark) on host ports 8089-8098, each with its own cache and Gradio volumes mounted read-write and a read-only mount of `${CONFIG_FOLDER}` into `/home/${OVOS_USER}/.config/mycroft`. `docker-compose.cuda.yml` runs the GPU-accelerated Piper engine and reserves an NVIDIA device.

## Layout

- `base/`: shared layer: Debian, a Python virtual environment, the `ovos` user, espeak-ng, ffmpeg, and `aiohttp`. Every engine image builds `FROM` this.
- `piper/`, `mimic3/`, `mimic/`, `google-tx/`, `sam/`, `matxa/`, `nos/`, `phoonnx/`, `kokoro/`: one directory per TTS engine. Each installs `ovos-tts-server` plus the matching `ovos-tts-plugin-*` and sets `ENTRYPOINT ovos-tts-server --engine <plugin>`.

## Related projects

- [OpenVoiceOS/ovos-tts-server](https://github.com/OpenVoiceOS/ovos-tts-server): the HTTP server each image runs.
- [OpenVoiceOS/gh-automations](https://github.com/OpenVoiceOS/gh-automations): shared CI workflows used across OpenVoiceOS repositories.
- [OpenVoiceOS community docs](https://openvoiceos.github.io/community-docs): broader OpenVoiceOS documentation referenced by the image labels.

## License

This repository has no LICENSE file.
