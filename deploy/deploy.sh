#!/bin/bash
set -e

# =============================================================
# KOP-ML - Script de deploy (executado pelo CI/CD via SSH)
# Roda como ubuntu (sudo disponível) no Oracle VPS
# =============================================================

APP_DIR="/opt/kop-ml"
cd "$APP_DIR"

echo "[DEPLOY] Iniciando deploy..."

# 1. Pull do código (como user kop, dono do repo)
echo "[DEPLOY] Atualizando código..."
sudo -u kop git config --global --add safe.directory "$APP_DIR"
sudo -u kop git pull origin main

# 2. Atualizar dependências Python
echo "[DEPLOY] Verificando dependências Python..."
sudo -u kop venv/bin/pip install -q -r requirements.txt

# 3. Atualizar dependências Node
echo "[DEPLOY] Verificando dependências Node..."
sudo -u kop bash -c "cd $APP_DIR/whatsapp_bridge && npm ci --omit=dev --silent 2>/dev/null"

# 4. Reiniciar APENAS o scraper (bridge mantém sessão WhatsApp ativa)
echo "[DEPLOY] Reiniciando scraper..."
sudo systemctl restart kop-scraper

# 5. Verificar status
sleep 3
if sudo systemctl is-active --quiet kop-scraper; then
    echo "[DEPLOY] Scraper reiniciado com sucesso!"
else
    echo "[DEPLOY] ERRO: Scraper não iniciou!"
    sudo journalctl -u kop-scraper --no-pager -n 20
    exit 1
fi

echo "[DEPLOY] Deploy concluído!"
