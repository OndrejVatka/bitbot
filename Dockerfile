FROM python:3.12-slim

WORKDIR /app

# Install curl for healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY pyproject.toml .
COPY src/ src/
RUN pip install --no-cache-dir .

# Copy config (settings.yaml — secrets come from .env at runtime)
COPY config/ config/

# Data directory is mounted as a volume
RUN mkdir -p data/logs

EXPOSE 8000

CMD ["bitbot"]
