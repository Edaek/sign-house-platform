FROM python:3.11-slim

ARG GIT_COMMIT=unknown
ENV GIT_COMMIT=${GIT_COMMIT}

WORKDIR /app

# opencv-python imports libGL.so.1 and libglib even for CPU-only use.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# gthread: MCP Streamable HTTP holds connections; sync workers (2) can block all /api traffic.
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "--worker-class", "gthread", "--threads", "8", "--timeout", "300", "--access-logfile", "-", "--error-logfile", "-", "run:app"]
