FROM node:24-bookworm-slim AS web
WORKDIR /build
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/index.html ./
COPY web/public ./public
COPY web/src ./src
RUN npm run build

FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 KEEPER_HOST=0.0.0.0 KEEPER_PORT=8080 KEEPER_DATA=/data
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends fonts-dejavu-core tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 10001 --create-home keeper && mkdir /data && chown keeper:keeper /data
COPY requirements-core.txt ./
RUN pip install --no-cache-dir -r requirements-core.txt
COPY keeper ./keeper
COPY server.py ./
COPY --from=web /build/dist ./web/dist
USER keeper
VOLUME ["/data"]
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz',timeout=3)"
CMD ["python", "server.py"]
