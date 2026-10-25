FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
COPY pyproject.toml ./
COPY stratagy ./stratagy
COPY migrations ./migrations
COPY alembic.ini ./
RUN pip install .
RUN useradd -m app && mkdir -p /app/data && chown -R app /app/data
USER app
EXPOSE 8000
HEALTHCHECK CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8000/api/health')"
CMD ["uvicorn", "stratagy.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
