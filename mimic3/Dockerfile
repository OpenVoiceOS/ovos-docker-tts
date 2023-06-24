ARG TAG=alpha
FROM smartgic/ovos-tts-server-base:${TAG}

ARG BUILD_DATE=unknown
ARG VERSION=unknown

LABEL org.opencontainers.image.title="Open Voice OS OCI TTS MImic3 image"
LABEL org.opencontainers.image.description="A TTS plugin for Open Voice OS using Mimic 3"
LABEL org.opencontainers.image.version=${VERSION}
LABEL org.opencontainers.image.created=${BUILD_DATE}
LABEL org.opencontainers.image.documentation="https://openvoiceos.github.io/community-docs"
LABEL org.opencontainers.image.source="https://github.com/OpenVoiceOS/ovos-docker-tts"
LABEL org.opencontainers.image.vendor="Open Voice OS"

ARG ALPHA=false
ARG USER=ovos
ARG LANG=all

SHELL ["/bin/bash", "-c"]

RUN if [ "${ALPHA}" == "true" ]; then \
    pip3 install ovos-tts-server ovos-tts-plugin-mimic3[${LANG}] --pre; \
    else \
    pip3 install ovos-tts-server ovos-tts-plugin-mimic3[${LANG}]; \
    fi \
    && mkdir -p ${HOME}/.cache/mycroft \
    && rm -rf ${HOME}/.cache/pip

USER $USER

ENV PATH /home/${USER}/.venv/bin:$PATH
ENV VIRTUAL_ENV /home/${USER}/.venv

ENTRYPOINT ovos-tts-server --engine ovos-tts-plugin-mimic3
