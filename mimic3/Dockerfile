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
ARG LANG=all
ARG USER=ovos

SHELL ["/bin/bash", "-c"]

RUN if [ "${ALPHA}" == "true" ]; then \
    pip3 install ovos-tts-server ovos-tts-plugin-mimic3[${LANG}] onnxruntime!=1.16 ovos-classifiers --pre; \
    else \
    pip3 install ovos-tts-server ovos-tts-plugin-mimic3[${LANG}] onnxruntime!=1.16 ovos-classifiers; \
    fi \
    && mkdir -p /home/${USER}/.cache/mycroft /home/${USER}/.local/share/mycroft/mimic3 \
    && rm -rf /home/${USER}/.cache/pip

USER $USER

ENTRYPOINT ovos-tts-server --engine ovos-tts-plugin-mimic3

EXPOSE 9666
