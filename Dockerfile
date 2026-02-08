FROM python:3.11-slim

# Instalar Chromium e ChromeDriver
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    chromium-driver \
    fonts-liberation \
    libnss3 \
    libxss1 \
    libasound2 \
    libatk-bridge2.0-0 \
    libgtk-3-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Instalar dependências Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar código fonte
COPY ai/ ai/
COPY database/ database/
COPY messaging/ messaging/
COPY models/ models/
COPY scraper/ scraper/
COPY config.py main.py ./

# Criar diretórios para volumes
RUN mkdir -p /app/data /app/logs

CMD ["python", "main.py"]
