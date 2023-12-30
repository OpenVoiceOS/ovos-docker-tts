ARG TAG=alpha
FROM smartgic/ovos-tts-server-base:${TAG}

ARG BUILD_DATE=unknown
ARG VERSION=unknown

LABEL org.opencontainers.image.title="Open Voice OS OCI TTS Google Translate image"
LABEL org.opencontainers.image.description="A TTS plugin for Open Voice OS using Google Translate"
LABEL org.opencontainers.image.version=${VERSION}
LABEL org.opencontainers.image.created=${BUILD_DATE}
LABEL org.opencontainers.image.documentation="https://openvoiceos.github.io/community-docs"
LABEL org.opencontainers.image.source="https://github.com/OpenVoiceOS/ovos-docker-tts"
LABEL org.opencontainers.image.vendor="Open Voice OS"

ARG ALPHA=false
ARG USER=ovos

SHELL ["/bin/bash", "-c"]

RUN if [ "${ALPHA}" == "true" ]; then \
    pip3 install ovos-tts-server git+https://github.com/OpenVoiceOS/ovos-tts-plugin-google-tx.git ovos-classifiers --pre; \
    else \
    pip3 install ovos-tts-server ovos-tts-plugin-google-tx ovos-classifiers; \
    fi \
    && mkdir -p /home/${USER}/.cache/mycroft/GoogleTranslateTTS \
    && rm -rf /home/${USER}/.cache/pip

USER $USER

ENTRYPOINT ovos-tts-server --engine ovos-tts-plugin-google-tx

EXPOSE 9666
