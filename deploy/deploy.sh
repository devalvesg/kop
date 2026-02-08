#!/bin/bash
set -e

# =============================================================
# KOP-ML - Script de deploy (executado pelo CI/CD via SSH)
# =============================================================

APP_DIR="/opt/kop-ml"
cd "$APP_DIR"

echo "[DEPLOY] Iniciando deploy..."

# 1. Pull do código
echo "[DEPLOY] Atualizando código..."
git pull origin main

# 2. Atualizar dependências Python (só se requirements.txt mudou)
echo "[DEPLOY] Verificando dependências Python..."
venv/bin/pip install -q -r requirements.txt

# 3. Atualizar dependências Node (só se package.json mudou)
echo "[DEPLOY] Verificando dependências Node..."
cd whatsapp_bridge && npm ci --omit=dev --silent 2>/dev/null && cd ..

# 4. Reiniciar APENAS o scraper (bridge mantém sessão WhatsApp ativa)
echo "[DEPLOY] Reiniciando scraper..."
sudo systemctl restart kop-scraper

# 5. Verificar status
sleep 2
if sudo systemctl is-active --quiet kop-scraper; then
    echo "[DEPLOY] Scraper reiniciado com sucesso!"
else
    echo "[DEPLOY] ERRO: Scraper não iniciou!"
    sudo journalctl -u kop-scraper --no-pager -n 20
    exit 1
fi

echo "[DEPLOY] Deploy concluído!"
