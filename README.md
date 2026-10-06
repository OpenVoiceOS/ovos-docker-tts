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
