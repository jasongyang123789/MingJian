FROM python:3.12-slim-bookworm

WORKDIR /app

# System deps for weasyprint (PDF generation)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf2.0-0 \
    libffi-dev \
    libcairo2 \
    fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY pyproject.toml .
COPY src/ src/
RUN pip install --no-cache-dir --index-url https://mirrors.cloud.tencent.com/pypi/simple -e .

# Create exports directory
RUN mkdir -p /app/exports

EXPOSE 8000

CMD ["uvicorn", "planagent.main:app", "--host", "0.0.0.0", "--port", "8000"]
