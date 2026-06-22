FROM python:3.11-slim

# Install system dependencies (tesseract removed – now using PaddleOCR)
RUN apt-get update && apt-get install -y \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements first for caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install PaddlePaddle from official source (not available on standard PyPI)
RUN pip install --no-cache-dir paddlepaddle==3.3.0 -i https://www.paddlepaddle.org.cn/packages/stable/cpu/
RUN pip install --no-cache-dir paddleocr==3.7.0

# Pre-download PaddleOCR models so first request isn't slow
ENV PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True
RUN python -c "from paddleocr import PaddleOCR; PaddleOCR(lang='en', use_doc_orientation_classify=False, use_doc_unwarping=False, use_textline_orientation=False)"

# Copy application code
COPY . .

# Create upload directories
RUN mkdir -p uploads/pdfs uploads/templates uploads/images uploads/exports

EXPOSE 8000

# Use Gunicorn for production with multiple workers
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "4", "--timeout", "300", "--access-logfile", "-", "--error-logfile", "-", "run:app"]
