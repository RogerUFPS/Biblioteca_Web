FROM alpine:3.22

RUN apk add --no-cache curl python3 su-exec

WORKDIR /app

COPY script.sh /app/script.sh
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/script.sh /app/entrypoint.sh \
    && adduser -D -H appuser

ENTRYPOINT ["/app/entrypoint.sh"]
