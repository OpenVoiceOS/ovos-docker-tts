FROM python:3.12-slim

ARG BUILD_DATE=unknown
ARG VERSION=unknown

LABEL org.opencontainers.image.title="Open Voice OS OCI TTS Kokoro image"
LABEL org.opencontainers.image.description="A TTS plugin for Open Voice OS using Kokoro"
LABEL org.opencontainers.image.version=${VERSION}
LABEL org.opencontainers.image.created=${BUILD_DATE}
LABEL org.opencontainers.image.documentation="https://openvoiceos.github.io/community-docs"
LABEL org.opencontainers.image.source="https://github.com/OpenVoiceOS/ovos-docker-tts"
LABEL org.opencontainers.image.vendor="Open Voice OS"

ARG ALPHA=false
ARG USER=ovos
ARG MISAKI_REF=main
ARG KOKORO_REF=main
ARG KOKORO_PLUGIN_REF=ovos-tts-plugin-kokoro-v0.2.0
ARG MISAKI_EXTRAS=en,ja,zh
ARG KOKORO_PLUGIN_EXTRAS=server,ja,zh

ENV DEBIAN_FRONTEND noninteractive
ENV PATH=/home/${USER}/.venv/bin:$PATH
ENV VIRTUAL_ENV=/home/${USER}/.venv
ENV HF_HOME=/home/${USER}/.cache/huggingface
ENV XDG_CACHE_HOME=/home/${USER}/.cache
ENV TORCH_CPP_LOG_LEVEL=ERROR

SHELL ["/bin/bash", "-c"]

RUN apt-get update \
    && apt-get install -y --no-install-recommends vim git gpg curl ffmpeg espeak-ng libsndfile1 patch build-essential cmake \
    && useradd --no-log-init $USER -m -c "Open Voice OS user" \
    && python3 -m venv /home/${USER}/.venv \
    && . /home/${USER}/.venv/bin/activate \
    && mkdir -p /home/${USER}/.config/mycroft /home/${USER}/.cache/mycroft /home/${USER}/gradio_cached_examples \
    && pip3 install --no-cache-dir aiohttp \
    && chown ${USER}:${USER} -R /home/${USER} \
    && apt-get clean \
    && rm -rf /var/lib/apt /var/log/{apt,dpkg.log}

USER $USER
WORKDIR /home/${USER}

COPY kokoro/patches/ovos-tts-plugin-kokoro-invalid-voice.patch /tmp/ovos-tts-plugin-kokoro-invalid-voice.patch

RUN pip3 install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
    && pip3 install --no-cache-dir \
        "misaki[${MISAKI_EXTRAS}] @ git+https://github.com/hexgrad/misaki.git@${MISAKI_REF}" \
        "kokoro @ git+https://github.com/hexgrad/kokoro.git@${KOKORO_REF}" \
    && if [ "${ALPHA}" == "true" ]; then \
        pip3 install --no-cache-dir --pre "gradio-client<1.0" "setuptools<81" ovos-tts-server ovos-classifiers \
            "ovos-tts-plugin-kokoro[${KOKORO_PLUGIN_EXTRAS}] @ git+https://github.com/OscillateLabsLLC/ovos-tts-plugin-kokoro.git@main"; \
    else \
        pip3 install --no-cache-dir "gradio-client<1.0" "setuptools<81" ovos-tts-server ovos-classifiers \
            "ovos-tts-plugin-kokoro[${KOKORO_PLUGIN_EXTRAS}] @ git+https://github.com/OscillateLabsLLC/ovos-tts-plugin-kokoro.git@${KOKORO_PLUGIN_REF}"; \
    fi \
    && python3 -m spacy download en_core_web_sm \
    && patch -d "${VIRTUAL_ENV}/lib/python3.12/site-packages/ovos_tts_plugin_kokoro" -p0 < /tmp/ovos-tts-plugin-kokoro-invalid-voice.patch \
    && rm -rf /home/${USER}/.cache/pip

COPY kokoro/patches/ovos-tts-server-callable-metadata.patch /tmp/ovos-tts-server-callable-metadata.patch

RUN patch -d "${VIRTUAL_ENV}/lib/python3.12/site-packages/ovos_tts_server" -p0 < /tmp/ovos-tts-server-callable-metadata.patch

RUN pip3 install --no-cache-dir unidic-lite \
    && pip3 uninstall -y unidic

ENTRYPOINT ovos-tts-server --engine ovos-tts-plugin-kokoro --cache

EXPOSE 9666
