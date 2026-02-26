# Use Python 3.12 slim image
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies with verbose output
RUN pip install --no-cache-dir -v -r requirements.txt && \
    pip list

# Copy application code
COPY src/ ./src/
COPY .env .env.example ./

# Create directory for lock file
RUN mkdir -p /tmp && \
    chmod 777 /tmp

# Run as non-root user
RUN useradd -m -u 1000 botuser && \
    chown -R botuser:botuser /app

USER botuser

# Run bot
CMD ["python", "-u", "src/bot.py"]