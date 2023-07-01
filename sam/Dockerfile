ARG TAG=alpha
FROM smartgic/ovos-tts-server-base:${TAG}

ARG BUILD_DATE=unknown
ARG VERSION=unknown

LABEL org.opencontainers.image.title="Open Voice OS OCI TTS S.A.M image"
LABEL org.opencontainers.image.description="Sam is a very small Text-To-Speech (TTS) program written in C, that runs on most popular platforms. It is an adaption to C of the speech software SAM (Software Automatic Mouth) for the Commodore C64 published in the year 1982 by Don't Ask Software (now SoftVoice, Inc.)."
LABEL org.opencontainers.image.version=${VERSION}
LABEL org.opencontainers.image.created=${BUILD_DATE}
LABEL org.opencontainers.image.documentation="https://openvoiceos.github.io/community-docs"
LABEL org.opencontainers.image.source="https://github.com/OpenVoiceOS/ovos-docker-tts"
LABEL org.opencontainers.image.vendor="Open Voice OS"

ARG ALPHA=false
ARG USER=ovos

SHELL ["/bin/bash", "-c"]

USER root

RUN apt-get update \
    && apt-get install -y libsdl1.2-dev \
    && rm -rf /var/lib/apt /var/log/{apt,dpkg.log}

USER $USER

RUN if [ "${ALPHA}" == "true" ]; then \
    pip3 install ovos-tts-server git+https://github.com/OpenVoiceOS/ovos-tts-plugin-SAM.git --pre; \
    else \
    pip3 install ovos-tts-server ovos-tts-plugin-SAM; \
    fi \
    && mkdir -p /home/${USER}/.cache/mycroft/SAMTTS \
    && rm -rf /home/${USER}/.cache/pip

USER $USER

ENTRYPOINT ovos-tts-server --engine ovos-tts-plugin-SAM
