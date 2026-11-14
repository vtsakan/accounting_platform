FROM python:3.12.16-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df

ARG APP_REVISION
LABEL org.opencontainers.image.source="https://github.com/vtsakan/accounting_platform" \
      org.opencontainers.image.revision=$APP_REVISION
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DJANGO_SETTINGS_MODULE=core.settings.production \
    TZ=Europe/Athens

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --create-home app
WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN python -m pip install --timeout 120 --retries 5 --no-cache-dir --require-hashes --only-binary=:all: --index-url https://pypi.org/simple -r requirements.txt \
    && python -m pip check
COPY manage.py gunicorn.conf.py /app/
COPY core /app/core
COPY accounting /app/accounting
COPY locale /app/locale
COPY templates /app/templates
COPY tools/init_local_env.py /app/tools/init_local_env.py
COPY docker/production-entrypoint.sh docker/healthcheck.py /app/docker/
RUN python manage.py collectstatic --noinput --settings=core.settings.build \
    && find /app/staticfiles -type d -exec chmod 0555 {} + \
    && find /app/staticfiles -type f -exec chmod 0444 {} +
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=10s --start-period=15s --retries=3 \
    CMD ["python", "/app/docker/healthcheck.py"]
ENTRYPOINT ["sh", "/app/docker/production-entrypoint.sh"]
CMD ["gunicorn", "--config", "/app/gunicorn.conf.py"]
