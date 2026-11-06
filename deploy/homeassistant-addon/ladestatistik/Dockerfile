ARG BUILD_FROM
FROM $BUILD_FROM
RUN apk add --no-cache python3 tzdata
WORKDIR /app
# wird von prepare.sh in den Build-Kontext kopiert
COPY ladestatistik /app/ladestatistik
COPY config.example.toml /app/config.example.toml
COPY run.sh /run.sh
RUN chmod a+x /run.sh
CMD ["/run.sh"]
