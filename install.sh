#!/bin/bash

# ====================================================================
# INSTALADOR AUTOMATIZADO - TACACS+ NG Premium WebGUI
# ====================================================================

# Colores para salida elegante
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # Sin color

echo -e "${BLUE}======================================================${NC}"
echo -e "${BLUE}  Instalador de TACACS+ NG Premium WebGUI & Servicio  ${NC}"
echo -e "${BLUE}======================================================${NC}"

# 1. Verificar privilegios de root
if [ "$EUID" -ne 0 ]; then
  echo -e "${RED}[ERROR] Este script debe ejecutarse como root (con sudo sh install.sh o sudo ./install.sh)${NC}"
  exit 1
fi

# Obtener el directorio absoluto de la aplicación
APP_DIR=$(cd "$(dirname "$0")" && pwd)

# Obtener el usuario real que ejecutó sudo, o en su defecto el dueño de la carpeta
REAL_USER=${SUDO_USER:-$(stat -c '%U' "$APP_DIR")}

echo -e "${GREEN}[1/5] Detectando sistema e instalando dependencias de OS...${NC}"
if [ -f /etc/debian_version ]; then
    apt-get update -y
    apt-get install -y python3 python3-pip python3-venv sqlite3 sudo
elif [ -f /etc/redhat-release ]; then
    dnf install -y python3 python3-pip sqlite sudo
else
    echo -e "${YELLOW}[ADVERTENCIA] Sistema operativo no detectado como Debian/Ubuntu o RHEL. Continuando de forma genérica...${NC}"
fi

# 2. Configurar el directorio de configuración
echo -e "${GREEN}[2/5] Configurando directorio de datos en /etc/tac_plus-ng/...${NC}"
mkdir -p /etc/tac_plus-ng
chown -R $REAL_USER:$REAL_USER /etc/tac_plus-ng

# 3. Configurar Entorno Virtual de Python y Librerías
echo -e "${GREEN}[3/5] Creando entorno virtual e instalando librerías de Python...${NC}"
cd "$APP_DIR" || exit 1
if [ ! -d ".venv" ]; then
    sudo -u $REAL_USER python3 -m venv .venv
fi

# Instalar dependencias dentro del entorno virtual
sudo -u $REAL_USER "$APP_DIR/.venv/bin/pip" install --upgrade pip
sudo -u $REAL_USER "$APP_DIR/.venv/bin/pip" install fastapi uvicorn sqlalchemy jinja2 python-multipart

# 4. Configurar sudoers para reinicios sin contraseña del daemon TACACS+
echo -e "${GREEN}[4/5] Configurando privilegios de sudoers para $REAL_USER...${NC}"
SUDOERS_FILE="/etc/sudoers.d/$REAL_USER"
if [ ! -f "$SUDOERS_FILE" ]; then
    echo "$REAL_USER ALL=(ALL) NOPASSWD: ALL" > "$SUDOERS_FILE"
    chmod 0440 "$SUDOERS_FILE"
    echo -e "  -> Configurado acceso sin contraseña de sudo para $REAL_USER"
fi

# 5. Crear el servicio de Systemd para que la WebGUI inicie con el sistema
echo -e "${GREEN}[5/5] Instalando servicio de systemd de la WebGUI...${NC}"
SERVICE_FILE="/etc/systemd/system/tacacs-webgui.service"

cat <<EOF > "$SERVICE_FILE"
[Unit]
Description=TACACS+ Next-Gen Premium WebGUI
After=network.target

[Service]
Type=simple
User=$REAL_USER
Group=$REAL_USER
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/.venv/bin/python3 -m uvicorn main:app --host 0.0.0.0 --port 8080
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Recargar systemd y activar servicio
systemctl daemon-reload
systemctl enable tacacs-webgui.service
systemctl restart tacacs-webgui.service

echo -e "\n${BLUE}======================================================${NC}"
echo -e "${GREEN}    ¡INSTALACIÓN COMPLETADA CON ÉXITO!${NC}"
echo -e "${BLUE}======================================================${NC}"
echo -e "La WebGUI se ha instalado como un servicio del sistema."
echo -e "Ahora se iniciará de forma automática si el servidor se reinicia.\n"
echo -e "Puedes administrar el servicio web usando los comandos:"
echo -e "  -> ${YELLOW}sudo systemctl status tacacs-webgui${NC}"
echo -e "  -> ${YELLOW}sudo systemctl restart tacacs-webgui${NC}"
echo -e "  -> ${YELLOW}sudo systemctl stop tacacs-webgui${NC}\n"

# Intentar obtener la IP local
IP_ADDR=$(hostname -I | awk '{print $1}')
echo -e "Accede a la interfaz web en: ${GREEN}http://${IP_ADDR:-localhost}:8080${NC}"
echo -e "${BLUE}======================================================${NC}"
