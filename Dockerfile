FROM python:3.12-slim AS base

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir --requirement requirements.txt

COPY src ./src
COPY helpers ./helpers

RUN useradd --create-home --uid 10001 stackplan
USER stackplan


FROM base AS runtime

ENTRYPOINT ["python", "-m", "src.main"]
