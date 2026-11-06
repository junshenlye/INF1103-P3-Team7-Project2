FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY src ./src
COPY experiments ./experiments
RUN useradd --create-home --uid 10001 stackplan && mkdir /data && chown stackplan:stackplan /data
USER stackplan
EXPOSE 18766
ENV STACKPLAN_DOCUMENT_DIRECTORY=/data DOCLING_URL=http://docling:5001
ENTRYPOINT ["gunicorn", "--bind", "0.0.0.0:18766", "--workers", "1", "--threads", "4", "--timeout", "30", "experiments.document_pipeline.wsgi:app"]
