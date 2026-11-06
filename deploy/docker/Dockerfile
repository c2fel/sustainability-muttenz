# Build aus dem Repo-Root:  docker build -f deploy/docker/Dockerfile -t ladestatistik .
FROM python:3.12-slim
# Zeitzonendaten für Europe/Zurich (Wochentag/Stunde in der Auswertung)
RUN pip install --no-cache-dir tzdata
WORKDIR /app
COPY ladestatistik ./ladestatistik
ENV PYTHONUNBUFFERED=1
VOLUME ["/app/data", "/app/site"]
ENTRYPOINT ["python", "-m", "ladestatistik", "-c", "/app/config.toml"]
CMD ["collect"]
