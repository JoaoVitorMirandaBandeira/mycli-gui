#!/usr/bin/env bash
# Instala o comando `my`, a interface gráfica (my-gui), o ícone e o atalho do menu de apps.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
bin="$HOME/.local/bin"
share="$HOME/.local/share/my-gui"

command -v mycli >/dev/null || echo "aviso: mycli não encontrado (sudo apt install mycli) — o modo terminal precisa dele."
python3 -c 'import pymysql' 2>/dev/null || echo "aviso: falta o PyMySQL (sudo apt install python3-pymysql) — a interface gráfica precisa dele."

mkdir -p "$bin" "$share" "$HOME/.local/share/icons/hicolor/scalable/apps" "$HOME/.local/share/applications"
install -m 755 "$here/bin/my" "$bin/my"
install -m 644 "$here/my-gui/server.py" "$here/my-gui/index.html" "$here/my-gui/my-gui.svg" "$share/"
install -m 644 "$here/my-gui/my-gui.svg" "$HOME/.local/share/icons/hicolor/scalable/apps/my-gui.svg"

cat > "$HOME/.local/share/applications/my-gui.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=my — MySQL
Comment=Cliente MySQL leve (mycli em janela)
Exec=$bin/my -g
Icon=my-gui
Terminal=false
Categories=Development;Database;
StartupWMClass=my-gui
EOF
command -v update-desktop-database >/dev/null && update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true

case ":$PATH:" in *":$bin:"*) ;; *) echo "aviso: $bin não está no PATH." ;; esac
echo "Instalado. Rode:  my -a  (adicionar conexão)  ou  python3 tools/import_dbeaver.py  (importar do DBeaver), depois:  my"
