# syntax=docker/dockerfile:1
FROM python:3.11-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    DISPLAY=:1 \
    DISPLAY_NUM=1 \
    WIDTH=1024 \
    HEIGHT=768 \
    HOME=/home/sandbox

RUN sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    apt-get -o Acquire::Retries=5 update \
    && apt-get -o Acquire::Retries=5 install -y --no-install-recommends --fix-missing \
    ca-certificates \
    curl \
    dbus-x11 \
    firefox-esr \
    fonts-dejavu-core \
    netcat-openbsd \
    openbox \
    procps \
    scrot \
    tini \
    x11vnc \
    xdotool \
    xterm \
    xvfb

RUN python -m pip install --no-cache-dir \
    jwcrypto==1.5.6 \
    websockify==0.12.0

RUN curl --fail --location --retry 5 \
    https://github.com/novnc/noVNC/archive/refs/tags/v1.5.0.tar.gz \
    --output /tmp/novnc.tar.gz \
    && mkdir -p /opt/novnc \
    && tar --extract --gzip --file /tmp/novnc.tar.gz --strip-components=1 --directory /opt/novnc \
    && rm /tmp/novnc.tar.gz

RUN useradd --create-home --shell /bin/bash sandbox \
    && mkdir -p /opt/sandbox \
    && chown -R sandbox:sandbox /opt/sandbox /home/sandbox

COPY --chown=sandbox:sandbox sandbox/ /opt/sandbox/
RUN chmod +x /opt/sandbox/entrypoint.sh

USER sandbox
WORKDIR /home/sandbox

EXPOSE 6080

HEALTHCHECK --interval=3s --timeout=2s --start-period=15s --retries=10 \
    CMD ["python3", "/opt/sandbox/healthcheck.py"]

ENTRYPOINT ["/usr/bin/tini", "--", "/opt/sandbox/entrypoint.sh"]
