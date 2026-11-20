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

ARG USER=ovos
ARG PHOONNX_REF=dev

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

# Alpha releases only: --pre for ovos-tts-server and what it depends on, and phoonnx from its dev
# branch. ovos-classifiers is not installed any more; nothing here imports it, and it held NumPy
# at 1.26.
# scriptconv[...] installs the phonemizers that phoonnx leaves out. A voice that needs one of
# them fails without it, or reads Arabic and Hebrew without their vowels:
#   espeak    the eSpeak wrapper
#   he        the Hebrew voices
#   misaki    the English, Japanese and Chinese voices of Kokoro
#   pt        the sense marks of European Portuguese
#   tashkeel  the vowel marks of Arabic text
# The floor is the one the dev branch of phoonnx asks for. It names a pre-release, and pip takes
# scriptconv's alpha line for this requirement only when the requirement itself names one.
# misaki's English extra also asks for a spaCy transformer tagger and, through it, for PyTorch.
# scriptconv does not use the tagger, but spaCy imports both when they are installed (190 MB of
# memory, 0.9 GB of image). PyTorch's CPU wheel goes in first, so that the resolver does not
# take the CUDA wheel with its CUDA libraries, and both are removed again. The spaCy model is
# installed here because misaki would otherwise fetch it with pip on the first request. The G2P
# call fails the build if English does not load without the removed packages.
# tokenizers<1: --pre takes the 1.0 release candidates, which have no Tokenizer.encode; the
# Hebrew vowel marks call it, and the voice reads the bare letters when it fails.
RUN pip3 install --no-cache-dir --no-deps --index-url https://download.pytorch.org/whl/cpu torch \
    && pip3 install --no-cache-dir --pre "gradio-client<1.0" "setuptools<81" "tokenizers<1" \
        ovos-tts-server \
        "phoonnx[espeak] @ git+https://github.com/TigreGotico/phoonnx.git@${PHOONNX_REF}" \
        "scriptconv[espeak,he,misaki,pt,tashkeel]>=0.0.4a123" \
    && pip3 uninstall -y \
        spacy-curated-transformers curated-transformers curated-tokenizers \
        torch sympy mpmath networkx \
    && python -m spacy download en_core_web_sm \
    && python -c "from misaki import en; en.G2P()('The image can speak English.')" \
    && mkdir -p /home/${USER}/.cache/phoonnx /home/${USER}/gradio_cached_examples \
    && rm -rf /home/${USER}/.cache/pip

# The streaming route (phoonnx/stream), in a layer of its own: a change to it does not
# rebuild the layer above.
COPY --chown=${USER}:${USER} phoonnx/stream /tmp/stream

RUN pip3 install --no-cache-dir /tmp/stream \
    && rm -rf /home/${USER}/.cache/pip

# ovos-tts-server plus GET /v2/synthesize/stream (phoonnx/stream)
ENTRYPOINT ["ovos-tts-server-stream", "--engine", "ovos-tts-plugin-phoonnx", "--cache"]

EXPOSE 9666
