FROM python:3.12.16-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Europe/Athens

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --create-home app

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN python -m pip install --no-cache-dir --require-hashes --only-binary=:all: --index-url https://pypi.org/simple -r requirements.txt \
    && python -m pip check

COPY --chown=app:app manage.py /app/manage.py
COPY --chown=app:app core /app/core
COPY --chown=app:app accounting /app/accounting
COPY --chown=app:app locale /app/locale
COPY --chown=app:app templates /app/templates
COPY --chown=app:app tools/init_local_env.py /app/tools/init_local_env.py
COPY --chown=app:app docker/development-entrypoint.sh /app/docker/development-entrypoint.sh

USER app
EXPOSE 8000
ENTRYPOINT ["sh", "/app/docker/development-entrypoint.sh"]
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
