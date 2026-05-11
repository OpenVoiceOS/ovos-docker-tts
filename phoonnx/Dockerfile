FROM python:3.12-slim

ARG BUILD_DATE=unknown
ARG VERSION=unknown

LABEL org.opencontainers.image.title="Open Voice OS OCI TTS Phoonnx image"
LABEL org.opencontainers.image.description="A TTS plugin for Open Voice OS using Phoonnx"
LABEL org.opencontainers.image.version=${VERSION}
LABEL org.opencontainers.image.created=${BUILD_DATE}
LABEL org.opencontainers.image.documentation="https://openvoiceos.github.io/community-docs"
LABEL org.opencontainers.image.source="https://github.com/OpenVoiceOS/ovos-docker-tts"
LABEL org.opencontainers.image.vendor="Open Voice OS"

ARG ALPHA=false
ARG USER=ovos
ARG PHOONNX_REF=1.3.3

ENV DEBIAN_FRONTEND noninteractive
ENV PATH=/home/${USER}/.venv/bin:$PATH
ENV VIRTUAL_ENV=/home/${USER}/.venv
ENV HF_HOME=/home/${USER}/.cache/huggingface
ENV XDG_CACHE_HOME=/home/${USER}/.cache

SHELL ["/bin/bash", "-c"]

RUN apt-get update \
    && apt-get install -y --no-install-recommends git espeak-ng libsndfile1 \
    && useradd --no-log-init $USER -m -c "Open Voice OS user" \
    && python3 -m venv /home/${USER}/.venv \
    && . /home/${USER}/.venv/bin/activate \
    && mkdir -p /home/${USER}/.config/mycroft /home/${USER}/.cache/phoonnx /home/${USER}/gradio_cached_examples \
    && pip3 install --no-cache-dir --upgrade pip wheel \
    && pip3 install --no-cache-dir aiohttp \
    && chown ${USER}:${USER} -R /home/${USER} \
    && apt-get --purge autoremove -y \
    && apt-get clean \
    && rm -rf /var/lib/apt /var/log/{apt,dpkg.log}

USER $USER

RUN if [ "${ALPHA}" == "true" ]; then \
        pip3 install --no-cache-dir --pre "gradio-client<1.0" "setuptools<81" ovos-tts-server ovos-classifiers \
            "phoonnx @ git+https://github.com/TigreGotico/phoonnx.git@dev"; \
    else \
        pip3 install --no-cache-dir "gradio-client<1.0" "setuptools<81" ovos-tts-server ovos-classifiers \
            "phoonnx @ git+https://github.com/TigreGotico/phoonnx.git@${PHOONNX_REF}"; \
    fi \
    && mkdir -p /home/${USER}/.cache/phoonnx /home/${USER}/gradio_cached_examples \
    && rm -rf /home/${USER}/.cache/pip

ENTRYPOINT ["/home/ovos/.venv/bin/ovos-tts-server", "--engine", "ovos-tts-plugin-phoonnx", "--cache"]

EXPOSE 9666
