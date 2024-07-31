ARG TAG=alpha
FROM smartgic/ovos-tts-server-base:${TAG}

ARG BUILD_DATE=unknown
ARG VERSION=unknown

LABEL org.opencontainers.image.title="Open Voice OS OCI TTS Matxa image"
LABEL org.opencontainers.image.description="A TTS plugin for Open Voice OS using Matxa"
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

RUN apt-get update \
    && apt-get install -y automake libtool \
    && git clone https://github.com/projecte-aina/espeak-ng /tmp/espeak-ng \
    && cd /tmp/espeak-ng \
    && ./autogen.sh \
    && ./configure \
    && make \
    && make install \
    && if [ "${ALPHA}" == "true" ]; then \
    pip3 install ovos-tts-server git+https://github.com/OpenVoiceOS/ovos-tts-plugin-matxa-multispeaker-cat.git ovos-classifiers --pre; \
    else \
    pip3 install ovos-tts-server ovos-tts-plugin-google-tx ovos-classifiers; \
    fi \
    && mkdir -p /home/${USER}/.local/share/OpenVoiceOS \
    && chown ${USER}:${USER} -R /home/${USER} \
    && apt-get --purge autoremove -y \
    && apt-get clean \
    && rm -rf /home/${USER}/.cache/pip /var/lib/apt /var/log/{apt,dpkg.log} /tmp/espeak-ng

USER $USER

ENTRYPOINT ovos-tts-server --engine ovos-tts-plugin-matxa-multispeaker-cat

EXPOSE 9666

