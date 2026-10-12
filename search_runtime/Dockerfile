# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm AS bundle
ARG TARGETARCH

RUN apt-get update && apt-get install -y --no-install-recommends binutils ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*
RUN case "$TARGETARCH" in \
      amd64) archive=x64; checksum=f677f850e64a75f4c202955649df074629306231feb4a2fa9bab0b9bbddafb6a ;; \
      arm64) archive=arm64; checksum=5213d291e6e883ece6d9509fa39be1ae0a7e188592ef87318693e705be994728 ;; \
      *) echo "Unsupported architecture: $TARGETARCH" >&2; exit 1 ;; \
    esac \
    && curl -fL --retry 3 -o /tmp/fortress.tar.gz \
      "https://github.com/tiliondev/fortress/releases/download/v153.0.8010.36/fortress-v153-linux-${archive}.tar.gz" \
    && echo "$checksum  /tmp/fortress.tar.gz" | sha256sum -c - \
    && mkdir /bundle \
    && tar -xzf /tmp/fortress.tar.gz -C /bundle --strip-components=1 \
    && strip --strip-unneeded /bundle/chrome /bundle/chrome_crashpad_handler \
    && find /bundle/locales -type f ! -name 'en-US.pak' -delete \
    && rm -f /bundle/libqt5_shim.so /bundle/libqt6_shim.so /bundle/tilion-activate /bundle/tilion_activate.py

FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl fontconfig libasound2 libatk-bridge2.0-0 libatk1.0-0 \
      libcairo2 libcups2 libdrm2 libgbm1 libglib2.0-0 libnspr4 libnss3 \
      libpango-1.0-0 libvulkan1 libx11-6 libxcomposite1 libxdamage1 \
      libxfixes3 libxkbcommon0 libxrandr2 libxshmfence1 \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir aiohttp==3.13.3 playwright==1.63.0
RUN useradd -m -u 10001 search
COPY --from=bundle --chown=search:search /bundle /opt/fortress
COPY --chown=search:search server.py /app/server.py
COPY --chown=search:search providers.py /app/providers.py
USER search
ENV HOME=/home/search TILION_NO_ACTIVATE=1 PYTHONUNBUFFERED=1
WORKDIR /app
EXPOSE 8080
CMD ["python", "server.py"]
