FROM python:3.12-slim AS base
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY src ./src
COPY database/migrations ./database/migrations
COPY frontend ./frontend
RUN useradd --create-home --uid 10001 stackplan && mkdir -p /data/documents && chown stackplan:stackplan /data/documents
USER stackplan
FROM base AS runtime
CMD ["uvicorn", "src.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
FROM base AS test
USER root
COPY requirements-dev.txt ./requirements-dev.txt
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY tests ./tests
COPY pytest.ini ./pytest.ini
USER stackplan
ENTRYPOINT ["python", "-m", "pytest"]
