ARG TAG=alpha
FROM smartgic/ovos-tts-server-base:${TAG}

ARG BUILD_DATE=unknown
ARG VERSION=unknown

LABEL org.opencontainers.image.title="Open Voice OS OCI TTS original MImic image"
LABEL org.opencontainers.image.description="A TTS plugin for Open Voice OS using Mimic"
LABEL org.opencontainers.image.version=${VERSION}
LABEL org.opencontainers.image.created=${BUILD_DATE}
LABEL org.opencontainers.image.documentation="https://openvoiceos.github.io/community-docs"
LABEL org.opencontainers.image.source="https://github.com/OpenVoiceOS/ovos-docker-tts"
LABEL org.opencontainers.image.vendor="Open Voice OS"

ARG ALPHA=false
ARG USER=ovos

ENV DEBIAN_FRONTEND noninteractive

USER root

SHELL ["/bin/bash", "-c"]

RUN curl -sS https://forslund.github.io/mycroft-desktop-repo/mycroft-desktop.gpg.key | gpg --dearmor -o /etc/apt/trusted.gpg.d/mimic.gpg \
    && echo "deb http://forslund.github.io/mycroft-desktop-repo bionic main" | tee -a /etc/apt/sources.list.d/mimic.list \
    && apt-get update \
    && apt-get install -y mimic \
    && if [ "${ALPHA}" == "true" ]; then \
    pip3 install ovos-tts-server ovos-tts-plugin-mimic ovos-classifiers --pre; \
    else \
    pip3 install ovos-tts-server ovos-tts-plugin-mimic ovos-classifiers; \
    fi \
    && mkdir -p /home/${USER}/.cache/mycroft/MimicTTSPlugin \
    && chown ${USER}:${USER} -R /home/${USER} \
    && apt-get --purge autoremove -y \
    && apt-get clean \
    && rm -rf /home/${USER}/.cache/pip /var/lib/apt /var/log/{apt,dpkg.log}

USER $USER

ENTRYPOINT ovos-tts-server --engine ovos-tts-plugin-mimic

EXPOSE 9666
