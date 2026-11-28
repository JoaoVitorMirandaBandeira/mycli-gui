#!/usr/bin/env bash
# Banco de demonstração do plano de execução: um MySQL 8.4 num container Docker.
#   tools/demo-db/demo-db.sh up      cria (ou religa) o banco e carrega os dados
#   tools/demo-db/demo-db.sh down    apaga o container (e os dados)
#   tools/demo-db/demo-db.sh reset   apaga e cria de novo
# Escuta só em 127.0.0.1:3398 (usuário root, senha demo, banco demo).
set -euo pipefail
NAME=my-gui-demo PORT=3398 PASS=demo IMAGE=mysql:8.4
DIR=$(cd "$(dirname "$0")" && pwd)
command -v docker >/dev/null || { echo "Precisa do Docker instalado."; exit 1; }

sql() { docker exec "$NAME" mysql -uroot -p"$PASS" "$@" </dev/null 2>&1 | grep -v 'Using a password' || true; }

wait_ready() {
  printf 'Esperando o MySQL subir'
  for _ in $(seq 1 90); do
    if docker exec "$NAME" mysql -uroot -p"$PASS" -e 'SELECT 1' >/dev/null 2>&1; then echo ' ok'; return; fi
    printf '.'; sleep 2
  done
  echo; echo 'O MySQL não respondeu. Veja: docker logs '"$NAME"; exit 1
}

add_alias() {
  local cfg="$HOME/.myclirc"
  if [ -f "$cfg" ] && grep -qE '^\s*demo\s*=' "$cfg"; then return; fi
  read -r -p "Adicionar a conexão \"demo\" ao ~/.myclirc? [S/n] " ok || ok=n
  case "${ok:-s}" in [nN]*) echo "Para conectar: host 127.0.0.1, porta $PORT, usuário root, senha $PASS, banco demo."; return ;; esac
  MY_CFG="$cfg" MY_LINE="demo = mysql://root:$PASS@127.0.0.1:$PORT/demo?ssl=false" python3 -I - <<'PY'
import os
cfg, line = os.environ['MY_CFG'], os.environ['MY_LINE']
lines = open(cfg).read().splitlines() if os.path.exists(cfg) else []
if '[alias_dsn]' not in [l.strip() for l in lines]:
    lines += ['', '[alias_dsn]']
i = [l.strip() for l in lines].index('[alias_dsn]')
lines.insert(i + 1, line)
open(cfg, 'w').write('\n'.join(lines) + '\n')
os.chmod(cfg, 0o600)
PY
  echo 'Conexão "demo" adicionada. No my-gui, clique em ⟳ ou reabra a janela para vê-la.'
}

up() {
  if docker ps -a --format '{{.Names}}' | grep -qx "$NAME"; then
    docker start "$NAME" >/dev/null; wait_ready
  else
    docker run -d --name "$NAME" -e MYSQL_ROOT_PASSWORD="$PASS" -e MYSQL_DATABASE=demo \
      -p 127.0.0.1:$PORT:3306 "$IMAGE" >/dev/null
    wait_ready
    echo 'Carregando os dados (uns 30 segundos)…'
    docker exec -i "$NAME" mysql -uroot -p"$PASS" demo < "$DIR/seed.sql" 2>&1 | grep -v 'Using a password' || true
  fi
  sql demo -N -e "SELECT CONCAT(table_name, ': ', table_rows, ' linhas (aprox.)') FROM information_schema.tables WHERE table_schema = 'demo'"
  add_alias
  echo "Pronto. Abra tools/demo-db/consultas.sql no my-gui (conexão demo) e use Ctrl+E."
}

case "${1:-up}" in
  up) up ;;
  down) docker rm -f "$NAME" >/dev/null 2>&1 && echo 'Banco de demonstração apagado.' || echo 'Não havia banco de demonstração.' ;;
  reset) docker rm -f "$NAME" >/dev/null 2>&1 || true; up ;;
  *) echo "uso: $0 [up|down|reset]"; exit 1 ;;
esac
