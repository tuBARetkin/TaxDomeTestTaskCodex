FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ ./src/
ARG INSTALL_TEST_DEPS=false
RUN if [ "$INSTALL_TEST_DEPS" = "true" ]; then \
        pip install --no-cache-dir '.[test]'; \
    else \
        pip install --no-cache-dir .; \
    fi && useradd --create-home app

COPY alembic.ini ./
COPY migrations/ ./migrations/
COPY test/ ./test/

USER app
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn api.main:app --host 0.0.0.0 --port 8000"]
