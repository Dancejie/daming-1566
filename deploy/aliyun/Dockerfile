FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8019 \
    DAMING_DATA_DIR=/data DAMING_EXTERNAL_MEDIA=verified-oss-release
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt && \
    groupadd -g 10001 daming && useradd -u 10001 -g 10001 -M daming && \
    mkdir /data && chown 10001:10001 /data && chmod 700 /data
COPY server.py legacy_server.py ./
COPY film/backend ./film/backend
COPY film/content ./film/content
COPY film/media/runtime-manifest.json ./film/media/runtime-manifest.json
COPY original/content ./original/content
COPY original/media/runtime-manifest.json ./original/media/runtime-manifest.json
COPY assets/classic_voice/manifest.json ./assets/classic_voice/manifest.json
USER 10001:10001
EXPOSE 8019
HEALTHCHECK --interval=30s --timeout=4s --start-period=15s --retries=3 CMD python -c "import json,urllib.request; d=json.load(urllib.request.urlopen('http://127.0.0.1:8019/api/health', timeout=3)); assert d['status']=='ok' and d['readyVideoCount']==12"
CMD ["python", "server.py"]
