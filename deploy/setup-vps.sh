#!/bin/bash
set -e

# =============================================================
# KOP - Setup inicial da VPS (Ubuntu / Oracle Linux)
# Rodar como root: sudo bash setup-vps.sh <REPO_URL>
# =============================================================

echo "========================================="
echo "  KOP - Setup VPS"
echo "========================================="

# Detectar package manager
if command -v apt-get &> /dev/null; then
    PKG_MANAGER="apt"
elif command -v dnf &> /dev/null; then
    PKG_MANAGER="dnf"
else
    echo "ERRO: Package manager não suportado (precisa de apt ou dnf)"
    exit 1
fi
echo "Package manager: $PKG_MANAGER"

# 1. Instalar dependências do sistema
echo "[1/8] Instalando dependências do sistema..."
if [ "$PKG_MANAGER" = "apt" ]; then
    apt-get update
    apt-get install -y software-properties-common
    add-apt-repository -y ppa:deadsnakes/ppa
    apt-get update
    apt-get install -y \
        python3.11 \
        python3.11-venv \
        python3.11-dev \
        git \
        wget \
        unzip \
        fonts-liberation \
        libnss3 \
        libxss1 \
        libasound2 \
        libatk-bridge2.0-0 \
        libgtk-3-0 \
        libdrm2 \
        libgbm1
else
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
        mesa-libgbm \
        alsa-lib \
        pango \
        gtk3
fi

# 2. Instalar Node.js 18
echo "[2/8] Instalando Node.js 18..."
if ! command -v node &> /dev/null; then
    if [ "$PKG_MANAGER" = "apt" ]; then
        curl -fsSL https://deb.nodesource.com/setup_18.x | bash -
        apt-get install -y nodejs
    else
        dnf module enable -y nodejs:18
        dnf install -y nodejs
    fi
fi
echo "Node.js: $(node --version)"

# 3. Instalar Chromium
echo "[3/8] Instalando Chromium..."
if [ "$PKG_MANAGER" = "apt" ]; then
    apt-get install -y chromium-browser || apt-get install -y chromium
else
    dnf install -y chromium
fi
CHROMIUM_PATH=$(which chromium-browser 2>/dev/null || which chromium 2>/dev/null || echo "não encontrado")
echo "Chromium: $CHROMIUM_PATH"

# 4. Instalar ChromeDriver
echo "[4/8] Instalando ChromeDriver..."
if [ "$PKG_MANAGER" = "apt" ]; then
    apt-get install -y chromium-chromedriver 2>/dev/null || echo "ChromeDriver será gerenciado pelo Selenium"
else
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
    echo "Uso: sudo bash setup-vps.sh https://github.com/SEU_USER/kop.git"
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

# Detectar comando python (priorizar 3.11)
PYTHON_CMD=$(which python3.11 2>/dev/null || which python3 2>/dev/null)
echo "Python: $PYTHON_CMD ($($PYTHON_CMD --version))"

# Python venv + deps
su - kop -c "
    cd $APP_DIR
    $PYTHON_CMD -m venv venv
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
