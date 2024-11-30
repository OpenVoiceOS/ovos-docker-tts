ARG TAG=alpha
FROM smartgic/ovos-tts-server-base:${TAG}

ARG BUILD_DATE=unknown
ARG VERSION=unknown

LABEL org.opencontainers.image.title="Open Voice OS OCI TTS NOS image"
LABEL org.opencontainers.image.description="A TTS plugin for Open Voice OS using NOS"
LABEL org.opencontainers.image.version=${VERSION}
LABEL org.opencontainers.image.created=${BUILD_DATE}
LABEL org.opencontainers.image.documentation="https://openvoiceos.github.io/community-docs"
LABEL org.opencontainers.image.source="https://github.com/OpenVoiceOS/ovos-docker-tts"
LABEL org.opencontainers.image.vendor="Open Voice OS"

ARG ALPHA=false
ARG USER=ovos

SHELL ["/bin/bash", "-c"]

RUN if [ "${ALPHA}" == "true" ]; then \
    pip3 install --no-cache-dir ovos-tts-server ovos-tts-plugin-nos ovos-tts-plugin-cotovia ovos-classifiers --pre; \
    else \
    pip3 install --no-cache-dir ovos-tts-server ovos-tts-plugin-nos ovos-tts-plugin-cotovia ovos-classifiers; \
    fi \
    && mkdir -p /home/${USER}/.local/share/nos_tts_models \
    && chown ${USER}:${USER} -R /home/${USER}

USER $USER

ENTRYPOINT ovos-tts-server --engine ovos-tts-plugin-nos

EXPOSE 9666
