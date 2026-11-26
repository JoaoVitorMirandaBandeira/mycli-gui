#!/usr/bin/env python3
"""Importa as conexões MySQL do DBeaver para aliases do mycli (~/.myclirc, chmod 600).

Uso:  python3 tools/import_dbeaver.py [pasta/.dbeaver]

Lê SOMENTE os arquivos locais do seu DBeaver (data-sources.json e credentials-config.json)
e grava os aliases (inclusive usuário e senha) no ~/.myclirc. Nada é enviado para a rede
e nenhuma senha é impressa. Requer `openssl` no PATH.
"""
import glob, json, os, subprocess, sys, urllib.parse
from pathlib import Path

# Chave padrão do DBeaver (publicada no código-fonte do projeto) para credentials-config.json.
KEY = 'babb4a9f774ab853c96c2d653dfe544a'


def find_base():
    if len(sys.argv) > 1:
        return Path(sys.argv[1]).expanduser()
    home = os.path.expanduser('~')
    pats = [
        home + '/snap/dbeaver-ce/*/.local/share/DBeaverData/workspace6/General/.dbeaver',
        home + '/.local/share/DBeaverData/workspace6/General/.dbeaver',
        home + '/.var/app/io.dbeaver.DBeaverCommunity/data/DBeaverData/workspace6/General/.dbeaver',
    ]
    found = [p for pat in pats for p in glob.glob(pat) if os.path.exists(p + '/data-sources.json')]
    if not found:
        sys.exit('Não achei o data-sources.json do DBeaver. Passe a pasta .dbeaver como argumento.')
    return Path(max(found, key=lambda p: os.path.getmtime(p + '/data-sources.json')))


base = find_base()
conns = json.loads((base / 'data-sources.json').read_text())['connections']
creds = {}
cred_file = base / 'credentials-config.json'
if cred_file.exists():
    raw = cred_file.read_bytes()
    out = subprocess.run(
        ['openssl', 'enc', '-d', '-aes-128-cbc', '-K', KEY, '-iv', raw[:16].hex()],
        input=raw[16:], capture_output=True, check=True)
    creds = json.loads(out.stdout)

q = lambda s: urllib.parse.quote(s, safe='')
lines = []
for k, c in conns.items():
    cfg, name = c['configuration'], c['name']
    if 'mysql' not in (c.get('provider', '') + c.get('driver', '')).lower() and 'maria' not in c.get('driver', '').lower():
        continue
    cr = creds.get(k, {}).get('#connection', {})
    user, pw = cr.get('user', cfg.get('user', '')), cr.get('password', '')
    alias = ''.join(ch if ch.isalnum() or ch in '_.-' else '_' for ch in name) or k
    auth = q(user) + (':' + q(pw) if pw else '')
    lines.append(f"{alias} = mysql://{auth}@{cfg['host']}:{cfg['port']}/")
    print(f"{alias:20} {cfg['host']}:{cfg['port']}  user={'ok' if user else '-'}  senha={'ok' if pw else '-'}")

path = Path.home() / '.myclirc'
old = path.read_text().splitlines() if path.exists() else []
# preserva o resto do arquivo; troca só a seção [alias_dsn]
kept, skip = [], False
for l in old:
    s = l.strip()
    if s.startswith('['):
        skip = (s == '[alias_dsn]')
    if not skip:
        kept.append(l)
path.write_text('\n'.join(kept + ['', '[alias_dsn]'] + lines).lstrip('\n') + '\n')
path.chmod(0o600)
print('gravado em', path)
