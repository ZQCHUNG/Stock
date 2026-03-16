# Cloud Run Job: Daily Stock Data Update
# Lightweight image — only data pipeline code, no frontend/backend
FROM python:3.11-slim

WORKDIR /app

# System deps for pyarrow and lxml
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc g++ && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY cloud/requirements-cloud.txt .
RUN pip install --no-cache-dir -r requirements-cloud.txt

# Copy only the modules needed for data pipeline
COPY config.py .
COPY data/ data/
COPY analysis/ analysis/

# Copy the job entry point
COPY cloud/daily_job.py cloud/daily_job.py

# Ensure data directories exist for GCS downloads (may be empty after .dockerignore)
RUN mkdir -p data/pattern_data/features data/pattern_data/raw data/cache

# Non-root user for security — must own data/ for GCS downloads
RUN useradd -m worker && chown -R worker:worker /app/data
USER worker

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

CMD ["python", "cloud/daily_job.py"]
