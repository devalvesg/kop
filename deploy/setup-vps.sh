#!/bin/bash
set -e

# =============================================================
# KOP-ML - Setup inicial da VPS Oracle Linux
# Rodar como root: sudo bash setup-vps.sh
# =============================================================

echo "========================================="
echo "  KOP-ML - Setup VPS Oracle Linux"
echo "========================================="

# 1. Instalar dependências do sistema
echo "[1/8] Instalando dependências do sistema..."
dnf install -y epel-release
dnf install -y \
    python3.11 \
    python3.11-pip \
    git \
    wget \
    unzip \
    fontconfig \
    liberation-fonts \
    nss \
    atk \
    at-spi2-atk \
    cups-libs \
    libdrm \
    libXcomposite \
    libXdamage \
    libXrandr \
    mesa-libgbm \
    alsa-lib \
    pango \
    gtk3

# 2. Instalar Node.js 18
echo "[2/8] Instalando Node.js 18..."
if ! command -v node &> /dev/null; then
    dnf module enable -y nodejs:18
    dnf install -y nodejs
fi
echo "Node.js: $(node --version)"

# 3. Instalar Chromium
echo "[3/8] Instalando Chromium..."
dnf install -y chromium
CHROMIUM_PATH=$(which chromium-browser 2>/dev/null || which chromium 2>/dev/null)
echo "Chromium: $CHROMIUM_PATH"

# 4. Instalar ChromeDriver compatível
echo "[4/8] Instalando ChromeDriver..."
if ! command -v chromedriver &> /dev/null; then
    dnf install -y chromedriver 2>/dev/null || echo "ChromeDriver será gerenciado pelo Selenium"
fi

# 5. Criar usuário kop
echo "[5/8] Configurando usuário kop..."
if ! id "kop" &>/dev/null; then
    useradd -r -m -s /bin/bash kop
    echo "Usuário kop criado"
else
    echo "Usuário kop já existe"
fi

# 6. Clonar/atualizar repositório
echo "[6/8] Configurando repositório..."
REPO_URL="${1:-}"
APP_DIR="/opt/kop-ml"

if [ -z "$REPO_URL" ]; then
    echo "AVISO: URL do repositório não informada."
    echo "Uso: sudo bash setup-vps.sh https://github.com/SEU_USER/kop-ml.git"
    echo "Criando diretório vazio..."
    mkdir -p "$APP_DIR"
else
    if [ -d "$APP_DIR/.git" ]; then
        cd "$APP_DIR"
        git pull origin main
    else
        git clone "$REPO_URL" "$APP_DIR"
    fi
fi

chown -R kop:kop "$APP_DIR"

# 7. Instalar dependências do projeto
echo "[7/8] Instalando dependências do projeto..."

# Python venv + deps
su - kop -c "
    cd $APP_DIR
    python3.11 -m venv venv
    venv/bin/pip install --upgrade pip
    venv/bin/pip install -r requirements.txt
"

# Node.js deps
su - kop -c "
    cd $APP_DIR/whatsapp_bridge
    npm ci --omit=dev
"

# Criar diretórios de dados
su - kop -c "
    mkdir -p $APP_DIR/data
    mkdir -p $APP_DIR/logs
"

# 8. Instalar e habilitar serviços systemd
echo "[8/8] Configurando serviços systemd..."
cp "$APP_DIR/deploy/kop-scraper.service" /etc/systemd/system/
cp "$APP_DIR/deploy/kop-whatsapp-bridge.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable kop-whatsapp-bridge
systemctl enable kop-scraper

# Configurar sudoers para deploy sem senha (CI/CD)
if ! grep -q "kop ALL=(ALL) NOPASSWD" /etc/sudoers.d/kop 2>/dev/null; then
    echo "kop ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart kop-scraper, /usr/bin/systemctl restart kop-whatsapp-bridge, /usr/bin/systemctl status kop-scraper, /usr/bin/systemctl status kop-whatsapp-bridge" > /etc/sudoers.d/kop
    chmod 440 /etc/sudoers.d/kop
    echo "Sudoers configurado para usuário kop"
fi

echo ""
echo "========================================="
echo "  Setup concluído!"
echo "========================================="
echo ""
echo "Próximos passos:"
echo "  1. Copiar .env para $APP_DIR/.env e preencher"
echo "     cp $APP_DIR/.env.example $APP_DIR/.env"
echo "     nano $APP_DIR/.env"
echo ""
echo "  2. Copiar cookies.json (gerado localmente) para o servidor:"
echo "     scp cookies.json kop@VPS_IP:$APP_DIR/data/"
echo ""
echo "  3. Iniciar o WhatsApp bridge e escanear QR code:"
echo "     sudo systemctl start kop-whatsapp-bridge"
echo "     journalctl -u kop-whatsapp-bridge -f"
echo ""
echo "  4. Após escanear QR, iniciar o scraper:"
echo "     sudo systemctl start kop-scraper"
echo "     journalctl -u kop-scraper -f"
echo ""
echo "  5. Configurar SSH key no GitHub para CI/CD"
echo "     ssh-keygen -t ed25519 -f ~/.ssh/github_deploy"
echo ""
