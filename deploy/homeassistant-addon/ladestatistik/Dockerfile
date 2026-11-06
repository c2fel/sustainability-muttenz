ARG BUILD_FROM
FROM $BUILD_FROM
# Der Code wird zur Laufzeit von GitHub geholt und automatisch aktualisiert (supervisor.py).
RUN apk add --no-cache python3 tzdata git
COPY supervisor.py /supervisor.py
CMD ["python3", "-u", "/supervisor.py"]
