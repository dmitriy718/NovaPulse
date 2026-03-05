FROM python:3.12-slim

LABEL maintainer="HA-SentinelAI" \
      description="Autonomous high-availability monitoring agent"

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        iputils-ping \
        procps \
        dnsutils \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN pip install --no-cache-dir aiohttp>=3.9.0 pyyaml>=6.0 dnspython>=2.4.0

COPY ../ha_agent/ ./ha_agent/
COPY ../ha_config.yaml ./ha_config.yaml

RUN mkdir -p /app/data/ha_sentinel

ENV HA_SENTINEL_CONFIG_PATH=/app/ha_config.yaml
ENV HA_SENTINEL_DATA_DIR=/app/data/ha_sentinel
ENV HA_SENTINEL_LOG_LEVEL=INFO

EXPOSE 8089

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8089/health || exit 1

ENTRYPOINT ["python3", "-m", "ha_agent"]
CMD ["--config", "/app/ha_config.yaml"]
