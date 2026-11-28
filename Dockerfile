# TikTok Shop Fashion Intelligence - end-to-end data pipeline demo (MADT8102)
# Build:  docker build -t tiktok-shop-pipeline .
# Run:    docker run --rm tiktok-shop-pipeline
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies first (cached layer): only what the local pipeline needs.
COPY docker/requirements.txt docker/requirements.txt
RUN pip install -r docker/requirements.txt

# Only the code and data contracts the pipeline needs (the web dashboard is not part of this image).
COPY pipeline ./pipeline
COPY schemas ./schemas
COPY sql ./sql
COPY source ./source
# Hash lock of the Source packages; the generator also writes its table contract into dashboard/data.
COPY dashboard/data/source_lock_classroom_v2.json dashboard/data/source_lock_classroom_v2.json
COPY docker/run_demo.py docker/run_demo.py

# Default: run all 10 monthly deliveries (incl. the March data-quality demo) and print the KPIs.
CMD ["python", "docker/run_demo.py"]
