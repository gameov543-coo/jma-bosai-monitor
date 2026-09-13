FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN groupadd --gid 10001 bosai && useradd --uid 10001 --gid 10001 --no-create-home bosai \
    && mkdir /data && chown bosai:bosai /data
COPY --chown=bosai:bosai bosai /app/bosai
COPY LICENSE THIRD_PARTY_NOTICES.md /usr/share/doc/bosai/
COPY docs/data-sources.md /usr/share/doc/bosai/docs/data-sources.md
USER 10001:10001
ENV STATE_DB=/data/state.sqlite3
HEALTHCHECK --interval=60s --timeout=10s --start-period=180s --retries=3 CMD ["python", "-m", "bosai", "healthcheck"]
CMD ["python", "-m", "bosai", "run"]
