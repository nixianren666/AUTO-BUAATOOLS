ARG BASE_IMAGE=python@sha256:cf6f9d6bea53c64f0eefc8912655ca37fc57d8439126ad0335be12a89952d35f
FROM ${BASE_IMAGE}
LABEL org.opencontainers.image.source="https://github.com/nixianren666/AUTO-BUAATOOLS" org.opencontainers.image.version="1.4.19" org.opencontainers.image.revision="a8f26c8"
ENV TZ=Asia/Shanghai PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 HEADLESS=1 BUAA_CONFIG_FILE=/data/config.json BUAA_VAULT_DIR=/data BUAA_TD_DEVICE_FILE=/data/.td-device-id
WORKDIR /app
RUN useradd --create-home --uid 10001 buaa
COPY requirements.lock ./
RUN pip install --no-cache-dir --prefer-binary --timeout 30 --retries 1 -r requirements.lock && pip check
COPY core/ core/
COPY server/ server/
COPY run.py LICENSE ./
RUN mkdir /data && chown buaa:buaa /data
USER 10001:10001
VOLUME ["/data"]
EXPOSE 18346
CMD ["python", "run.py", "--headless", "--host", "0.0.0.0", "--port", "18346"]
