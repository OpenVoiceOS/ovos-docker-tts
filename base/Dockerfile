FROM debian:bookworm-slim

ARG BUILD_DATE=unknown
ARG VERSION=unknown

LABEL org.opencontainers.image.title="Open Voice OS OCI Text-to-Text base image"
LABEL org.opencontainers.image.description="Used as base layer for other OCI STT images"
LABEL org.opencontainers.image.version=${VERSION}
LABEL org.opencontainers.image.created=${BUILD_DATE}
LABEL org.opencontainers.image.documentation="https://openvoiceos.github.io/community-docs"
LABEL org.opencontainers.image.source="https://github.com/OpenVoiceOS/ovos-docker-tts"
LABEL org.opencontainers.image.vendor="Open Voice OS"

ARG ALPHA=false
ARG USER=ovos

ENV DEBIAN_FRONTEND noninteractive

SHELL ["/bin/bash", "-c"]

RUN apt-get update \
    && apt-get install -y vim git gpg python3 python3-venv python3-pip curl ffmpeg libespeak-ng1 \
    && c_rehash \
    && useradd --no-log-init $USER -m -c "Open Voice OS user" \
    && python3 -m venv /home/${USER}/.venv \
    && . /home/${USER}/.venv/bin/activate \
    && mkdir -p /home/${USER}/.config/mycroft /home/${USER}/.cache /home/${USER}/gradio_cached_examples \
    && pip3 install aiohttp \
    && chown ${USER}:${USER} -R /home/${USER} \
    && apt-get --purge autoremove -y \
    && apt-get clean \
    && rm -rf ${HOME}/.cache/* /var/lib/apt /var/log/{apt,dpkg.log}

USER $USER

ENV PATH /home/${USER}/.venv/bin:$PATH
ENV VIRTUAL_ENV /home/${USER}/.venv

WORKDIR /home/${USER}
