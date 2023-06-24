ARG TAG=alpha
FROM smartgic/ovos-tts-server-base:${TAG}

ARG BUILD_DATE=unknown
ARG VERSION=unknown

LABEL org.opencontainers.image.title="Open Voice OS OCI TTS Piper image"
LABEL org.opencontainers.image.description="A TTS plugin for OVOS using Piper"
LABEL org.opencontainers.image.version=${VERSION}
LABEL org.opencontainers.image.created=${BUILD_DATE}
LABEL org.opencontainers.image.documentation="https://openvoiceos.github.io/community-docs"
LABEL org.opencontainers.image.source="https://github.com/OpenVoiceOS/ovos-docker-tts"
LABEL org.opencontainers.image.vendor="Open Voice OS"

ARG ALPHA=false
ARG USER=ovos

SHELL ["/bin/bash", "-c"]

RUN if [ "${ALPHA}" == "true" ]; then \
    pip3 install ovos-tts-server git+https://github.com/goldyfruit/ovos-tts-plugin-piper.git --pre; \
    else \
    pip3 install ovos-tts-server ovos-tts-plugin-piper; \
    fi \
    && mkdir -p ${HOME}/.cache/mycroft \
    && rm -rf ${HOME}/.cache/pip

USER $USER

ENV PATH /home/${USER}/.venv/bin:$PATH
ENV VIRTUAL_ENV /home/${USER}/.venv

ENTRYPOINT ovos-tts-server --engine ovos-tts-plugin-piper
