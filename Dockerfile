FROM python:3.12-slim
WORKDIR /app
ENV TZ=Asia/Shanghai PYTHONUNBUFFERED=1 HEADLESS=1 BUAA_CONFIG_FILE=/data/config.json BUAA_VAULT_DIR=/data BUAA_TD_DEVICE_FILE=/data/.td-device-id
RUN useradd --create-home --uid 10001 buaa
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY core/ core/
COPY server/ server/
COPY run.py .
RUN mkdir /data && chown buaa:buaa /data
USER buaa
VOLUME ["/data"]
EXPOSE 18346
CMD ["python", "run.py", "--headless", "--host", "0.0.0.0", "--port", "18346"]
