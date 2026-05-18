FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies first (layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create data directory for SQLite DB
RUN mkdir -p data

# Expose port
EXPOSE 8000

# Seed DB and start server
CMD ["sh", "-c", "python startup.py && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
