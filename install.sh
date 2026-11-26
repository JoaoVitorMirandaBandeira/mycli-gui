#!/usr/bin/env bash
# Instalação em um passo:  ./install.sh
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
bin="$HOME/.local/bin"
share="$HOME/.local/share/my-gui"

# 1) dependências (só instala o que falta; pede a senha de administrador)
need=()
command -v python3 >/dev/null || need+=(python3)
command -v mycli   >/dev/null || need+=(mycli)
python3 -c 'import pymysql' 2>/dev/null || need+=(python3-pymysql)
if [ ${#need[@]} -gt 0 ]; then
  if command -v apt-get >/dev/null; then
    echo "Instalando: ${need[*]}"
    sudo apt-get install -y "${need[@]}"
  else
    echo "Instale manualmente: ${need[*]}"; exit 1
  fi
fi
command -v google-chrome >/dev/null || command -v chromium >/dev/null \
  || echo "Aviso: Chrome/Chromium não encontrado; a janela vai abrir no navegador padrão."

# 2) arquivos
mkdir -p "$bin" "$share" "$HOME/.local/share/icons/hicolor/scalable/apps" "$HOME/.local/share/applications"
install -m 755 "$here/bin/my" "$bin/my"
install -m 644 "$here/my-gui/server.py" "$here/my-gui/index.html" "$here/my-gui/my-gui.svg" "$share/"
install -m 644 "$here/my-gui/my-gui.svg" "$HOME/.local/share/icons/hicolor/scalable/apps/my-gui.svg"
# o nome do arquivo e o StartupWMClass são a classe que o Chrome dá às janelas --app=http://127.0.0.1:...
rm -f "$HOME/.local/share/applications/my-gui.desktop"
cat > "$HOME/.local/share/applications/chrome-127.0.0.1__-Default.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=my — MySQL
Comment=Cliente MySQL leve (mycli em janela)
Exec=$bin/my -g
Icon=my-gui
Terminal=false
Categories=Development;Database;
StartupWMClass=chrome-127.0.0.1__-Default
DESK
command -v update-desktop-database >/dev/null && update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true

# 3) PATH (só se ~/.local/bin ainda não estiver nele)
case ":$PATH:" in *":$bin:"*) ;; *)
  rc="$HOME/.bashrc"; [ "${SHELL##*/}" = zsh ] && rc="$HOME/.zshrc"
  grep -qs '.local/bin' "$rc" || echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$rc"
  echo "Adicionei ~/.local/bin ao PATH em $rc — abra um terminal novo."
esac

echo
echo "Pronto! Próximos passos:"
echo "  1) my        (abre a janela)"
echo "  2) clique em ＋ para adicionar sua primeira conexão"
