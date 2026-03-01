# Use Python 3.12 slim image
FROM python:3.12-slim

# Install system dependencies and tzdata
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    libffi-dev \
    tzdata \
    && ln -fs /usr/share/zoneinfo/Europe/Moscow /etc/localtime \
    && dpkg-reconfigure -f noninteractive tzdata \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

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

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
  CMD python -c "import requests; requests.get('https://api.telegram.org/bot${TELEGRAM_TOKEN}/getMe', timeout=5)" || exit 1

# Run bot
CMD ["python", "-u", "src/bot.py"]