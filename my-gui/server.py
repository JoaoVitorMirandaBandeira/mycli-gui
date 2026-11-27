#!/usr/bin/env python3
"""my-gui — cliente MySQL local e leve, numa janela do navegador.

Usa os aliases de ~/.myclirc ([alias_dsn]). Só escuta em 127.0.0.1, com token.
Senhas nunca vão para a página. Encerra sozinho quando a janela é fechada.
"""
import datetime, decimal, hashlib, hmac, io, json, os, re, secrets, shutil, subprocess, sys
import signal, ssl, tarfile, threading, time, urllib.error, urllib.parse, urllib.request, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pymysql
import pymysql.cursors
from pymysql.constants import SERVER_STATUS

HOME = os.path.expanduser('~')
CFG = os.path.join(HOME, '.myclirc')
STATE_DIR = os.path.join(HOME, '.cache', 'my-gui')
STATE_FILE = os.path.join(STATE_DIR, 'instance.json')
HTML_PATH = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'index.html')


class ApiError(Exception):
    def __init__(self, msg, need_password=False):
        super().__init__(msg)
        self.need_password = need_password


def emsg(e):
    a = getattr(e, 'args', ())
    return f'{a[0]}: {a[1]}' if len(a) >= 2 else str(e)


# ---------------------------------------------------------------- aliases ---
def load_aliases():
    out = {}
    try:
        lines = open(CFG, encoding='utf-8').read().splitlines()
    except OSError:
        return out
    sec = False
    for line in lines:
        s = line.strip()
        if s.startswith('['):
            sec = (s == '[alias_dsn]')
            continue
        if sec and s and not s.startswith('#') and '=' in s:
            name, val = s.split('=', 1)
            u = urllib.parse.urlparse(val.strip().strip('\'"'))
            out[name.strip()] = dict(
                host=u.hostname or 'localhost', port=u.port or 3306,
                user=urllib.parse.unquote(u.username or ''),
                password=urllib.parse.unquote(u.password) if u.password is not None else None,
                # sem "?ssl=true" no DSN o SSL fica desligado (comportamento de sempre)
                ssl=urllib.parse.parse_qs(u.query).get('ssl', [''])[0].lower() == 'true',
                db=(u.path or '').lstrip('/') or None)
    return out


# ----------------------------------------------------------------- estado ---
CONF_DIR = os.path.join(HOME, '.config', 'my-gui')
STATE_JSON = os.path.join(CONF_DIR, 'state.json')
_state_lock = threading.Lock()


def state_get():
    for p in (STATE_JSON, STATE_JSON + '.bak'):
        try:
            with open(p, encoding='utf-8') as f:
                d = json.load(f)
            if isinstance(d, dict):
                return d
        except (OSError, ValueError):
            continue
    return {}


def state_set(doc):
    """Grava abas, SQL, conexão e histórico: arquivo temporário + fsync + rename (atômico)."""
    if not isinstance(doc, dict):
        raise ApiError('estado inválido')
    with _state_lock:
        merged = state_get()
        merged.update(doc)  # chaves ausentes (ex.: hist) são preservadas
        raw = json.dumps(merged, ensure_ascii=False)
        if len(raw) > 8_000_000:
            raise ApiError('estado grande demais')
        os.makedirs(CONF_DIR, mode=0o700, exist_ok=True)
        tmp = STATE_JSON + '.tmp'
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())
        if os.path.exists(STATE_JSON):
            try:
                os.replace(STATE_JSON, STATE_JSON + '.bak')  # última versão boa
            except OSError:
                pass
        os.replace(tmp, STATE_JSON)
        try:
            dfd = os.open(CONF_DIR, os.O_RDONLY)
            os.fsync(dfd)
            os.close(dfd)
        except OSError:
            pass


def write_cfg(lines):
    tmp = CFG + '.tmp'
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    os.replace(tmp, CFG)


def edit_alias(name, line):
    """Grava (ou remove, se line=None) o alias dentro de [alias_dsn] do ~/.myclirc."""
    try:
        lines = open(CFG, encoding='utf-8').read().splitlines()
    except OSError:
        lines = []
    out, inside, done = [], False, False
    for l in lines:
        s = l.strip()
        if s.startswith('['):
            if inside and not done and line is not None:
                out.append(line); done = True
            inside = (s == '[alias_dsn]')
        if inside and re.match(rf'\s*{re.escape(name)}\s*=', l):
            if line is not None and not done:
                out.append(line); done = True
            continue
        out.append(l)
    if line is not None and not done:
        if not any(l.strip() == '[alias_dsn]' for l in lines):
            out += ['', '[alias_dsn]']
        out.append(line)
    write_cfg(out)


def alias_args(d):
    """Valida o formulário de conexão; senha None = manter a atual."""
    name = (d.get('name') or '').strip()
    host = (d.get('host') or '').strip()
    if not re.fullmatch(r'[A-Za-z0-9_.-]+', name):
        raise ApiError('Nome inválido: use só letras, números, _ . -')
    if not host or re.search(r'[\s/@]', host):
        raise ApiError('Host inválido')
    try:
        port = int(d.get('port') or 3306)
        assert 0 < port < 65536
    except Exception:
        raise ApiError('Porta inválida')
    pw = d.get('password')
    if pw is None:
        pw = (load_aliases().get(name) or {}).get('password')
    return name, host, port, d.get('user') or '', pw


def ssl_kwargs(on):
    """SSL ligado: como o --ssl-mode auto do mycli (criptografa, sem validar o certificado)."""
    if not on:
        return {}
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return dict(ssl=ctx)


# ------------------------------------------------------------------- pool ---
class Pool:
    """Conexões por alias: 'main' (consultas do usuário), 'meta' (árvore e autocomplete)
    e 'browse' (leitura de tabelas sem o estado da sessão do editor).
    Não há ping a cada comando (custa uma ida e volta): só se a conexão ficou parada
    mais de IDLE_PING segundos; o resto é tratado reconectando quando der erro."""
    IDLE_PING = 120

    def __init__(self):
        self.conns, self.pw, self.locks, self.used = {}, {}, {}, {}
        self.glock = threading.Lock()

    def lock(self, alias, kind='main'):
        with self.glock:
            return self.locks.setdefault((alias, kind), threading.RLock())

    def drop(self, alias, kind=None):
        for k in ((kind,) if kind else ('main', 'meta', 'browse')):
            c = self.conns.pop((alias, k), None)
            if c is not None:
                try:
                    c._force_close()
                except Exception:
                    pass

    def creds(self, alias):
        al = load_aliases().get(alias)
        if not al:
            raise ApiError(f"Alias '{alias}' não existe no ~/.myclirc")
        pw = al['password'] if al['password'] is not None else self.pw.get(alias)
        if pw is None:
            raise ApiError('Senha necessária', need_password=True)
        return al, pw

    def connect(self, alias, read_timeout=900):
        al, pw = self.creds(alias)
        try:
            return pymysql.connect(
                host=al['host'], port=al['port'], user=al['user'], password=pw,
                database=al['db'], connect_timeout=8, read_timeout=read_timeout,
                autocommit=True, charset='utf8mb4',
                cursorclass=pymysql.cursors.SSCursor, **ssl_kwargs(al['ssl']))
        except pymysql.MySQLError as e:
            if e.args and e.args[0] == 1045 and alias in self.pw:
                del self.pw[alias]
                raise ApiError(emsg(e), need_password=True)
            raise ApiError(emsg(e))

    def get(self, alias, kind='main'):
        key = (alias, kind)
        c = self.conns.get(key)
        if c is not None and time.time() - self.used.get(key, 0) > self.IDLE_PING:
            try:
                c.ping(reconnect=True)
            except Exception:
                self.drop(alias, kind)
                c = None
        if c is None:
            c = self.conns[key] = self.connect(alias)
        self.used[key] = time.time()
        return c


pool = Pool()


# -------------------------------------------------------------------- sql ---
def split_sql(sql):
    out, buf, i, n, q = [], [], 0, len(sql), None
    while i < n:
        ch = sql[i]
        nx = sql[i + 1] if i + 1 < n else ''
        if q:
            buf.append(ch)
            if ch == '\\' and q != '`' and i + 1 < n:
                buf.append(nx); i += 2; continue
            if ch == q:
                if nx == q:
                    buf.append(nx); i += 2; continue
                q = None
        elif ch in '\'"`':
            q = ch; buf.append(ch)
        elif ch == '#' or (ch == '-' and nx == '-' and (i + 2 >= n or sql[i + 2] in ' \t\r\n')):
            j = sql.find('\n', i); j = n if j < 0 else j
            buf.append(sql[i:j]); i = j; continue
        elif ch == '/' and nx == '*':
            j = sql.find('*/', i + 2); j = n if j < 0 else j + 2
            buf.append(sql[i:j]); i = j; continue
        elif ch == ';':
            out.append(''.join(buf)); buf = []
        else:
            buf.append(ch)
        i += 1
    out.append(''.join(buf))
    res = []
    for s in out:
        s = s.strip()
        rest = re.sub(r'/\*.*?\*/|--[^\n]*|#[^\n]*', '', s, flags=re.S).strip()
        if rest:
            res.append(s)
    return res


def jv(v):
    if v is None or isinstance(v, str):
        return v
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, int):
        return v if abs(v) < 2 ** 53 else str(v)
    if isinstance(v, float):
        return v if v == v and abs(v) != float('inf') else str(v)
    if isinstance(v, (bytes, bytearray)):
        try:
            s = bytes(v).decode('utf-8')
            if s.isprintable() or '\n' in s:
                return s
        except UnicodeDecodeError:
            pass
        return '0x' + bytes(v).hex()
    return str(v)  # datetime, date, time, timedelta, Decimal, ...


READ_RE = re.compile(r'\s*\(*\s*(select|show|describe|desc|explain|use)\b', re.I)
running, cancelled = {}, {}   # alias -> (qid, thread_id) ; qid -> instante do pedido de cancelamento


def _gone(e):
    return (bool(e.args) and e.args[0] in (2006, 2013, 2055)) or isinstance(e, pymysql.InterfaceError)


def run_query(alias, db, sql, limit, qid=None, browse=None):
    limit = max(1, min(int(limit or 1000), 20000))
    results, err = [], None
    kind = 'browse' if browse else 'main'
    with pool.lock(alias):
        cur_db = db or None
        try:
            for st in split_sql(sql):
                if qid and qid in cancelled:
                    err = 'Consulta cancelada.'
                    break
                t0 = time.time()
                for attempt in (0, 1):
                    try:
                        c = pool.get(alias, kind)
                        if cur_db is None:
                            cur_db = jv(c.db)
                        elif c.db != cur_db:
                            c.select_db(cur_db)
                        running[alias] = (qid, c.thread_id())
                        cur = c.cursor()
                        cur.execute(st)
                        break
                    except pymysql.MySQLError as e:
                        if _gone(e):
                            pool.drop(alias, kind)
                            if attempt == 0 and READ_RE.match(st):
                                continue  # leitura: seguro repetir numa conexão nova
                        raise
                if cur.description:
                    cols = [d[0] for d in cur.description]
                    rows = cur.fetchmany(limit + 1)
                    trunc = len(rows) > limit
                    res = dict(sql=st, columns=cols, truncated=trunc,
                               rows=[[jv(v) for v in r] for r in rows[:limit]])
                    manual = None if browse else select_source(st, cur._result.fields)
                    source = (db, browse) if browse else manual and manual[:2]
                    if trunc:
                        # Descarta o resto sem tentar drenar o socket no destrutor.
                        cur._result.unbuffered_active = False
                        pool.drop(alias, kind)
                        cur.connection = None
                    else:
                        cur.close()
                    if source:
                        if not rows:
                            res['edit_reason'] = 'A consulta não retornou linhas para editar.'
                        elif trunc and not browse:
                            res['edit_reason'] = 'Use LIMIT para carregar o resultado completo antes de editar.'
                        elif browse or check_editor_table(c, manual[2], res):
                            add_table_edit(alias, *source, res, rows[:limit])
                    elif re.match(r'\s*SELECT\b', st, re.I):
                        res['edit_reason'] = 'A edição direta está disponível em SELECT * de uma única tabela.'
                else:
                    res = dict(sql=st, columns=[], rows=[], affected=cur.rowcount)
                    cur.close()
                m = re.match(r'use\s+`?([^`\s]+)`?\s*$', st, re.I)
                if m and (alias, 'main') in pool.conns:
                    cur_db = pool.conns[(alias, 'main')].db = m.group(1)
                res['ms'] = int((time.time() - t0) * 1000)
                if qid and qid in cancelled:  # ex.: SLEEP interrompido devolve 1 sem erro
                    err = 'Consulta cancelada.'
                    break
                results.append(res)
        except ApiError as e:
            return dict(results=results, error=str(e), db=cur_db, need_password=e.need_password)
        except pymysql.MySQLError as e:
            if e.args and e.args[0] == 1317:
                err = 'Consulta cancelada.'
            elif _gone(e):
                pool.drop(alias, kind)
                err = ('Conexão com o servidor perdida. O comando não foi repetido automaticamente; '
                       'confira o resultado antes de executar de novo.')
            else:
                err = emsg(e)
        finally:
            running.pop(alias, None)
            cancelled.pop(qid, None)
    return dict(results=results, error=err, db=cur_db)


def cancel_query(alias, qid):
    """Cancela a consulta (KILL QUERY por outra conexão). Se ainda está na fila, ela aborta ao vez dela."""
    cancelled[qid] = time.time()
    if len(cancelled) > 200:
        for k in sorted(cancelled, key=cancelled.get)[:100]:
            cancelled.pop(k, None)
    r = running.get(alias)
    if r and r[0] == qid:
        c = pool.connect(alias, read_timeout=10)
        try:
            c.cursor().execute(f'KILL QUERY {int(r[1])}')
        finally:
            c.close()


def simple(alias, db, sql, params=None):
    with pool.lock(alias, 'meta'):
        for attempt in (0, 1):
            try:
                c = pool.get(alias, 'meta')
                if db and c.db != db:
                    c.select_db(db)
                cur = c.cursor()
                try:
                    cur.execute(sql, params)
                    return cur.fetchall()
                finally:
                    cur.close()
            except pymysql.MySQLError as e:
                if _gone(e):
                    pool.drop(alias, 'meta')
                    if attempt == 0:
                        continue
                raise


def bq(name):
    return '`' + name.replace('`', '``') + '`'


# ----------------------------------------------------------- editar tabela ---
INTEGER_TYPES = {'tinyint', 'smallint', 'mediumint', 'int', 'bigint', 'year'}
KEY_TYPES = INTEGER_TYPES | {'decimal', 'char', 'varchar', 'date', 'datetime', 'timestamp'}
EDIT_TYPES = KEY_TYPES | {'float', 'double', 'time', 'enum', 'set', 'json',
                          'tinytext', 'text', 'mediumtext', 'longtext'}


def table_scope(alias, db, table):
    return alias, db, table, load_aliases().get(alias)


def row_version(scope, columns, row):
    return hmac.digest(TOKEN.encode(), repr((scope, columns, row)).encode(), 'sha256').hex()


SQL_NAME = r'(?:`(?:``|[^`])+`|[^\W\d][\w$]*)'
SELECT_TABLE = re.compile(
    rf'\s*SELECT\s+\*\s+FROM\s+({SQL_NAME})(?:\s*\.\s*({SQL_NAME}))?(?=\s|$)', re.I)
SQL_QUOTED = re.compile(r"""'(?:''|[^'\\])*'|"(?:""|[^"\\])*"|`(?:``|[^`])*`""")
UNSAFE_SELECT = re.compile(r"""['"`\\#]|--|/\*|;|\b(union|intersect|except|into|procedure|for|lock)\b""", re.I)


def select_source(sql, fields):
    """Identifica SELECT * de uma tabela, inclusive com WHERE, ORDER BY e LIMIT."""
    match = SELECT_TABLE.match(sql)
    if not match or not fields:
        return None
    tail = sql[match.end():].strip()
    if tail and (not re.match(r'(where|order\s+by|limit)\b', tail, re.I)
                 or UNSAFE_SELECT.search(SQL_QUOTED.sub('?', tail))):
        return None
    first = fields[0]
    if not first.db or not first.org_table or any(
            f.db != first.db or f.org_table != first.org_table or f.name != f.org_name
            for f in fields):
        return None
    target = '.'.join(part for part in match.groups() if part)
    return jv(first.db), first.org_table, target


def check_editor_table(connection, target, result):
    if connection.server_status & SERVER_STATUS.SERVER_STATUS_IN_TRANS:
        result['edit_reason'] = 'Finalize a transação do editor antes de editar pela tabela.'
        return False
    try:
        with connection.cursor(pymysql.cursors.Cursor) as cur:
            # Usa o nome da consulta, pois views podem informar a tabela base
            # nos metadados das colunas.
            cur.execute(f'SHOW CREATE TABLE {target}')
            definition = cur.fetchone()[1]
    except pymysql.MySQLError:
        result['edit_reason'] = 'A definição da tabela está indisponível.'
        return False
    if not definition.startswith('CREATE TABLE '):
        result['edit_reason'] = 'A edição está disponível para tabelas permanentes.'
        return False
    return True


def edit_columns(read, db, table, columns):
    rows = read(
        'SELECT c.column_name, c.data_type, k.column_name, c.extra '
        'FROM information_schema.columns c JOIN information_schema.tables t '
        'ON BINARY c.table_schema=BINARY t.table_schema AND BINARY c.table_name=BINARY t.table_name '
        'LEFT JOIN information_schema.key_column_usage k '
        'ON BINARY c.table_schema=BINARY k.table_schema AND BINARY c.table_name=BINARY k.table_name '
        "AND c.column_name=k.column_name AND k.constraint_name='PRIMARY' "
        'WHERE BINARY c.table_schema=%s AND BINARY c.table_name=%s '
        "AND t.table_type='BASE TABLE' AND t.engine='InnoDB'", (db, table))
    keys = {name: ty for name, ty, key, _ in rows if key is not None}
    if not keys or any(name not in columns or ty not in KEY_TYPES for name, ty in keys.items()):
        return {}, []
    editable = {name for name, ty, _, extra in rows
                if name not in keys and ty in EDIT_TYPES
                and not any(flag in extra.upper() for flag in ('VIRTUAL GENERATED', 'STORED GENERATED'))}
    return keys, [i for i, name in enumerate(columns) if name in editable]


def add_table_edit(alias, db, table, result, rows):
    cols = result['columns']
    try:
        keys, editable = edit_columns(lambda q, p: simple(alias, None, q, p), db, table, cols)
    except (ApiError, pymysql.MySQLError):
        result['edit_reason'] = 'Os metadados da tabela estão indisponíveis.'
        return
    if not keys:
        result['edit_reason'] = 'A edição exige uma tabela InnoDB com chave primária visível e compatível.'
        return
    if not editable:
        result['edit_reason'] = 'A tabela não tem colunas compatíveis para edição.'
        return
    scope = table_scope(alias, db, table)
    result['edit'] = dict(alias=alias, db=db, table=table, columns=editable,
                          versions=[row_version(scope, cols, row) for row in rows],
                          keys=[i for i, name in enumerate(cols) if name in keys])


def table_updates(alias, db, table, changes, preview=False, expected_columns=None):
    if not all(isinstance(s, str) and s for s in (alias, db, table)):
        raise ApiError('Tabela inválida')
    if not isinstance(changes, list) or not 1 <= len(changes) <= 20000:
        raise ApiError('Alterações inválidas')
    target = bq(db) + '.' + bq(table)
    # PyMySQL usa formatação com %, inclusive em identificadores quando há parâmetros.
    target_params = target.replace('%', '%%')
    with pool.connect(alias) as c:
        c.begin()
        try:
            with c.cursor(pymysql.cursors.Cursor) as cur:
                def read(sql, params=None):
                    cur.execute(sql, params)
                    return cur.fetchall()

                # Mantém o schema estável até o fim da transação.
                read(f'SELECT * FROM {target} LIMIT 0')
                columns = [d[0] for d in cur.description]
                if preview and columns != expected_columns:
                    raise ApiError('As colunas da tabela mudaram. Recarregue o resultado antes de copiar o SQL.')
                keys, editable = edit_columns(read, db, table, columns)
                if not editable:
                    raise ApiError('Esta tabela não permite edição direta')
                editable = {str(i) for i in editable}
                key_names = [name for name in columns if name in keys]
                where = ' AND '.join(bq(name).replace('%', '%%') + '=%s' for name in key_names)
                updates = []
                for change in changes:
                    if not isinstance(change, dict):
                        raise ApiError('Alteração inválida')
                    key = change.get('key')
                    values = change.get('values')
                    version = change.get('version')
                    if (not isinstance(key, list) or len(key) != len(keys)
                            or not all(type(v) in (str, int) for v in key)
                            or not isinstance(values, dict) or not values
                            or not all(i in editable
                                       and (v is None or isinstance(v, str)) for i, v in values.items())
                            or not isinstance(version, str) or not re.fullmatch('[0-9a-f]{64}', version)):
                        raise ApiError('Alteração inválida')
                    try:
                        params = tuple(int(v) if keys[name] in INTEGER_TYPES
                                       else decimal.Decimal(v) if keys[name] == 'decimal' else v
                                       for name, v in zip(key_names, key))
                    except (ValueError, decimal.InvalidOperation):
                        raise ApiError('Chave primária inválida') from None
                    assignments = ', '.join(bq(columns[int(i)]).replace('%', '%%') + '=%s' for i in values)
                    sql = f'UPDATE {target_params} SET {assignments} WHERE {where}'
                    updates.append((sql, (*values.values(), *params), params, version))

                if preview:
                    return dict(sql='\n'.join(cur.mogrify(sql, args) + ';' for sql, args, _, _ in updates))

                scope = table_scope(alias, db, table)
                select = f'SELECT * FROM {target_params} WHERE {where} FOR UPDATE'
                saved = []
                for sql, args, params, version in updates:
                    rows = read(select, params)
                    if len(rows) != 1 or not hmac.compare_digest(version, row_version(scope, columns, rows[0])):
                        raise ApiError('Um registro mudou ou foi excluído. Recarregue a tabela antes de editar novamente.')
                    cur.execute(sql, args)
                    warnings = read('SHOW WARNINGS')
                    if warnings:
                        raise ApiError(f'{warnings[0][1]}: {warnings[0][2]}')
                    rows = read(select, params)
                    if len(rows) != 1:
                        raise ApiError('A chave primária mudou durante a atualização')
                    saved.append(dict(row=[jv(v) for v in rows[0]],
                                      version=row_version(scope, columns, rows[0])))
            c.commit()
        except Exception:
            if c.open:
                c.rollback()
            raise
    return dict(saved=saved)


def foreign_keys(alias, db, tables):
    """FKs (saindo) das tabelas pedidas, numa só consulta. O filtro é por constantes
    (sem BINARY nas colunas) para o MySQL poder usar os índices do information_schema."""
    tables = [t for t in (tables or []) if isinstance(t, str)][:60]
    if not isinstance(db, str) or not db or not tables:
        return {}
    ph = ','.join(['%s'] * len(tables))
    rows = simple(alias, None,
                  'SELECT k.table_name, k.constraint_name, k.column_name, k.referenced_table_schema, '
                  'k.referenced_table_name, k.referenced_column_name, r.delete_rule, r.update_rule '
                  'FROM information_schema.key_column_usage k '
                  'JOIN information_schema.referential_constraints r '
                  'ON r.constraint_schema=k.constraint_schema AND r.constraint_name=k.constraint_name '
                  'AND r.table_name=k.table_name '
                  f'WHERE k.table_schema=%s AND k.table_name IN ({ph}) '
                  'AND k.referenced_table_name IS NOT NULL '
                  'ORDER BY k.table_name, k.constraint_name, k.ordinal_position',
                  (db, *tables))
    out = {t: [] for t in tables}
    by_name = {}
    for t, name, col, rdb, rtable, rcol, dele, upd in rows:
        t, name = jv(t), jv(name)
        fk = by_name.get((t, name))
        if fk is None:
            fk = by_name[(t, name)] = dict(name=name, cols=[], rdb=jv(rdb), rtable=jv(rtable), rcols=[],
                                            on_delete=jv(dele), on_update=jv(upd))
            out.setdefault(t, []).append(fk)
        fk['cols'].append(jv(col))
        fk['rcols'].append(jv(rcol))
    return out


def api(path, d):
    if path == '/api/ping':
        return {}
    if path == '/api/update/status':
        return update_status()
    if path == '/api/update/check':
        update_check_safe()
        return update_status()
    if path == '/api/update/apply':
        return update_apply()
    if path == '/api/aliases':
        return dict(aliases=[
            dict(name=k, host=v['host'], port=v['port'], user=v['user'],
                 ssl=v['ssl'], db=v['db'] or '')
            for k, v in load_aliases().items()])
    if path == '/api/state/get':
        return dict(state=state_get())
    if path == '/api/state/set':
        state_set(d.get('state'))
        return {}
    if path == '/api/alias/save':
        name, host, port, user, pw = alias_args(d)
        q = lambda s: urllib.parse.quote(s, safe='')
        auth = q(user) + (':' + q(pw) if pw else '')
        edit_alias(name, f'{name} = mysql://{auth}@{host}:{port}/?ssl={"true" if bool(d.get("ssl")) else "false"}')
        pool.drop(name); pool.pw.pop(name, None)
        return dict(name=name)
    if path == '/api/alias/delete':
        name = (d.get('name') or '').strip()
        if name not in load_aliases():
            raise ApiError('Conexão não encontrada')
        edit_alias(name, None)
        pool.drop(name); pool.pw.pop(name, None)
        return {}
    if path == '/api/alias/test':
        name, host, port, user, pw = alias_args(d)
        if pw is None:
            pw = pool.pw.get(name, '')
        t0 = time.time()
        try:
            c = pymysql.connect(host=host, port=port, user=user, password=pw,
                                connect_timeout=6, read_timeout=8,
                                **ssl_kwargs(bool(d.get('ssl'))))
            ver = c.get_server_info()
            c.close()
        except pymysql.MySQLError as e:
            raise ApiError(emsg(e))
        return dict(message=f'Conectou: MySQL {ver} ({int((time.time() - t0) * 1000)} ms)')
    alias = d.get('alias')
    if path == '/api/password':
        pool.pw[alias] = d.get('password', '')
        pool.drop(alias)
        return {}
    if path == '/api/databases':
        rows = simple(alias, None, 'SHOW DATABASES')
        return dict(databases=sorted((r[0] for r in rows), key=str.lower),
                    db=jv(pool.conns[(alias, 'meta')].db) or '')
    if path == '/api/tables':
        rows = simple(alias, d.get('db'), 'SHOW FULL TABLES FROM ' + bq(d['db']))
        return dict(tables=[[r[0], r[1]] for r in rows])
    if path == '/api/columns':
        tables = [t for t in (d.get('tables') or []) if isinstance(t, str)][:60]
        if not tables:
            return dict(columns={})
        ph = ','.join(['%s'] * len(tables))
        rows = simple(alias, None,
                      'SELECT table_name, column_name, column_type, column_key '
                      'FROM information_schema.columns WHERE table_schema=%s '
                      f'AND table_name IN ({ph}) ORDER BY table_name, ordinal_position',
                      (d['db'], *tables))
        cols = {t: [] for t in tables}
        for t, c, ty, k in rows:
            cols.setdefault(jv(t), []).append([jv(c), jv(ty), jv(k)])
        return dict(columns=cols)
    if path == '/api/fks':
        return dict(fks=foreign_keys(alias, d.get('db'), d.get('tables')))
    if path == '/api/cancel':
        cancel_query(alias, d.get('qid'))
        return {}
    if path == '/api/query':
        db, sql, limit, qid = d.get('db'), d.get('sql', ''), d.get('limit'), d.get('qid')
        table = d.get('table')
        if db and isinstance(table, str) and sql == f'SELECT * FROM {bq(table)} LIMIT 200;':
            # A leitura usa outra sessão para ignorar tabelas temporárias do editor.
            return run_query(alias, db, sql, limit, qid, browse=table)
        return run_query(alias, db, sql, limit, qid)
    if path in ('/api/table/save', '/api/table/preview'):
        return table_updates(alias, d.get('db'), d.get('table'), d.get('changes'),
                             preview=path == '/api/table/preview', expected_columns=d.get('columns'))
    raise ApiError('rota desconhecida')


# ------------------------------------------------------------ atualização ---
# Versão nova = release do GitHub (tag vX.Y.Z) do repositório oficial. Só se baixa por HTTPS
# de github.com, confere o SHA-256 publicado na release e só se copiam os arquivos da lista
# fixa abaixo — nada do pacote é executado, nem o install.sh.
REPO = 'JoaoVitorMirandaBandeira/mycli-gui'
API_LATEST = f'https://api.github.com/repos/{REPO}/releases/latest'
CHECK_EVERY = 6 * 3600
VER_RE = re.compile(r'\d{1,4}\.\d{1,4}\.\d{1,4}')
UPDATE_FILES = ('bin/my', 'my-gui/server.py', 'my-gui/index.html', 'my-gui/my-gui.svg',
                'my-gui/VERSION')
MAX_PACKAGE = 8_000_000
SHARE_DIR = os.path.dirname(HTML_PATH)
BIN_PATH = os.path.normpath(os.path.join(SHARE_DIR, '..', '..', 'bin', 'my'))
ICON_PATH = os.path.normpath(os.path.join(SHARE_DIR, '..', 'icons', 'hicolor', 'scalable',
                                          'apps', 'my-gui.svg'))
UPDATE_CACHE = os.path.join(CONF_DIR, 'update.json')
PORT = 0
UPD = dict(latest=None, checked=0, error=None, etag=None)
_upd_lock = threading.Lock()


def vtuple(v):
    return tuple(int(x) for x in v.split('.'))


def current_version():
    try:
        v = open(os.path.join(SHARE_DIR, 'VERSION'), encoding='utf-8').read().strip()
    except OSError:
        v = ''
    return v if VER_RE.fullmatch(v) else '0.0.0'


def can_update():
    """Só atualiza a instalação em ~/.local (não um checkout de desenvolvimento)."""
    return not os.path.exists(os.path.join(SHARE_DIR, '..', '.git'))


def _host_ok(h):
    return h in ('github.com', 'api.github.com') or (h or '').endswith('.githubusercontent.com')


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        u = urllib.parse.urlparse(newurl)
        if u.scheme != 'https' or not _host_ok(u.hostname):
            raise urllib.error.URLError('redirecionamento para origem não confiável')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url, limit, etag=None):
    """GET por HTTPS só em github.com (e seus CDNs); devolve (bytes, etag)."""
    u = urllib.parse.urlparse(url)
    if u.scheme != 'https' or not _host_ok(u.hostname):
        raise ApiError('origem de atualização não permitida')
    headers = {'User-Agent': 'my-gui-updater', 'Accept': 'application/vnd.github+json'}
    if etag:
        headers['If-None-Match'] = etag
    op = urllib.request.build_opener(_SafeRedirect)
    with op.open(urllib.request.Request(url, headers=headers), timeout=15) as r:
        data = r.read(limit + 1)
        if len(data) > limit:
            raise ApiError('arquivo de atualização grande demais')
        return data, r.headers.get('ETag')


def _upd_load():
    try:
        c = json.load(open(UPDATE_CACHE, encoding='utf-8'))
        if isinstance(c.get('latest'), dict) and VER_RE.fullmatch(str(c['latest'].get('version'))):
            UPD['latest'], UPD['etag'] = c['latest'], c.get('etag')
    except (OSError, ValueError, AttributeError):
        pass


def _upd_save():
    try:
        os.makedirs(CONF_DIR, exist_ok=True)
        tmp = UPDATE_CACHE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(dict(latest=UPD['latest'], etag=UPD['etag']), f)
        os.replace(tmp, UPDATE_CACHE)
    except OSError:
        pass


def update_check():
    """Consulta a última release (1 requisição leve; com ETag, 304 não gasta cota da API)."""
    try:
        raw, etag = fetch(API_LATEST, 1_000_000, UPD['etag'] if UPD['latest'] else None)
    except urllib.error.HTTPError as e:
        if e.code == 304:
            UPD.update(checked=time.time(), error=None)
            return
        if e.code == 404:  # ainda não há release publicada
            UPD.update(latest=None, etag=None, checked=time.time(), error=None)
            return
        raise
    rel = json.loads(raw)
    m = re.fullmatch(r'v(\d{1,4}\.\d{1,4}\.\d{1,4})', str(rel.get('tag_name', '')))
    if not m or rel.get('draft') or rel.get('prerelease'):
        raise ApiError('release inválida')
    ver = m.group(1)
    names = {a.get('name') for a in rel.get('assets') or [] if isinstance(a, dict)}
    pkg = f'my-gui-{ver}.tar.gz'
    if pkg not in names or pkg + '.sha256' not in names:
        raise ApiError(f'a release v{ver} não tem os arquivos de instalação')
    UPD.update(latest=dict(version=ver, notes=str(rel.get('body') or '')[:2000]),
               etag=etag, checked=time.time(), error=None)
    _upd_save()


def update_check_safe():
    try:
        update_check()
    except Exception as e:  # sem rede/VPN fora do ar: segue sem avisar
        UPD.update(checked=time.time(), error=f'{type(e).__name__}: {e}'[:200])


def update_loop():
    time.sleep(5)
    while True:
        update_check_safe()
        time.sleep(CHECK_EVERY)


def update_status():
    cur, latest = current_version(), UPD['latest']
    return dict(current=cur, latest=latest and latest['version'],
                notes=latest['notes'] if latest else '', checked=UPD['checked'],
                error=UPD['error'], can_update=can_update(),
                available=bool(latest and vtuple(latest['version']) > vtuple(cur)))


def _targets():
    t = {'bin/my': (BIN_PATH, 0o755)}
    for n in UPDATE_FILES[1:]:
        t[n] = (os.path.join(SHARE_DIR, n.split('/', 1)[1]), 0o644)
    return t


def _unpack(blob, ver):
    """Lê só os arquivos esperados do .tar.gz (nunca extrai nada em disco)."""
    out = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(blob), mode='r:gz') as tf:
            for m in tf:
                name = m.name[2:] if m.name.startswith('./') else m.name
                if name not in UPDATE_FILES:
                    continue
                if not m.isreg() or m.size > 4_000_000 or name in out:
                    raise ApiError(f'pacote inválido ({name})')
                out[name] = tf.extractfile(m).read()
    except (tarfile.TarError, OSError, EOFError) as e:
        raise ApiError(f'pacote ilegível: {e}')
    missing = [n for n in UPDATE_FILES if n not in out]
    if missing:
        raise ApiError('pacote incompleto: faltam ' + ', '.join(missing))
    if out['my-gui/VERSION'].decode('utf-8', 'replace').strip() != ver:
        raise ApiError('a versão dentro do pacote não confere com a release')
    try:
        compile(out['my-gui/server.py'], 'server.py', 'exec')
    except SyntaxError as e:
        raise ApiError(f'server.py do pacote não compila: {e}')
    if not out['bin/my'].startswith(b'#!') or b'__TOKEN__' not in out['my-gui/index.html']:
        raise ApiError('pacote com arquivos inesperados')
    return out


def _backup_dir():
    return os.path.join(SHARE_DIR, 'backup')


def _make_backup():
    bd = _backup_dir()
    shutil.rmtree(bd, ignore_errors=True)
    existed = []
    for name, (path, _) in _targets().items():
        if os.path.isfile(path):
            os.makedirs(os.path.dirname(os.path.join(bd, name)), exist_ok=True)
            shutil.copy2(path, os.path.join(bd, name))
            existed.append(name)
    with open(os.path.join(bd, 'manifest.json'), 'w') as f:
        json.dump(dict(version=current_version(), existed=existed), f)


def _write(path, data, mode):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.new'
    with open(tmp, 'wb') as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def restore_backup():
    bd = _backup_dir()
    man = json.load(open(os.path.join(bd, 'manifest.json')))
    for name, (path, mode) in _targets().items():
        if name in man['existed']:
            _write(path, open(os.path.join(bd, name), 'rb').read(), mode)
        elif os.path.exists(path):
            os.remove(path)
    if os.path.isdir(os.path.dirname(ICON_PATH)):
        _write(ICON_PATH, open(os.path.join(SHARE_DIR, 'my-gui.svg'), 'rb').read(), 0o644)
    return man['version']


def _install(files):
    _make_backup()
    try:
        for name, (path, mode) in _targets().items():
            _write(path, files[name], mode)
        if os.path.isdir(os.path.dirname(ICON_PATH)):
            _write(ICON_PATH, files['my-gui/my-gui.svg'], 0o644)
    except Exception:
        restore_backup()
        raise


def _spawn_server():
    """Sobe um servidor (sem abrir janela) a partir dos arquivos instalados."""
    os.makedirs(STATE_DIR, exist_ok=True)
    log = open(os.path.join(STATE_DIR, 'log'), 'ab')
    env = dict(os.environ, MY_GUI_NO_OPEN='1')
    p = subprocess.Popen([sys.executable, '-I', os.path.join(SHARE_DIR, 'server.py')], env=env,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=log,
                         start_new_session=True)
    deadline = time.time() + 15
    while time.time() < deadline and p.poll() is None:
        try:
            st = json.load(open(STATE_FILE))
            if st.get('pid') == p.pid:
                req = urllib.request.Request(f"http://127.0.0.1:{st['port']}/api/ping",
                                             headers={'X-Token': st['token']})
                urllib.request.urlopen(req, timeout=1.5).read()
                return st
        except Exception:
            pass
        time.sleep(0.25)
    if p.poll() is None:
        p.terminate()
    return None


def write_state():
    os.makedirs(STATE_DIR, exist_ok=True)
    fd = os.open(STATE_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump(dict(port=PORT, token=TOKEN, pid=os.getpid(), ver=code_version()), f)


def drop_state():
    """Remove o instance.json só se ele ainda for deste processo."""
    try:
        if json.load(open(STATE_FILE)).get('pid') == os.getpid():
            os.remove(STATE_FILE)
    except (OSError, ValueError):
        pass


def _handoff(ok_msg):
    """Troca para o servidor recém-instalado; devolve a URL para a janela recarregar."""
    drop_state()  # senão o servidor novo trataria este como "instância antiga" e o mataria
    st = _spawn_server()
    if not st:
        return None
    threading.Timer(2.0, os._exit, (0,)).start()  # a janela já terá a resposta
    return dict(ok=True, message=ok_msg, version=current_version(),
                url=f"http://127.0.0.1:{st['port']}/?t={st['token']}")


def update_apply():
    if not _upd_lock.acquire(blocking=False):
        raise ApiError('Já existe uma atualização em andamento')
    try:
        if not can_update():
            raise ApiError('Esta cópia não é a instalada em ~/.local; atualize com git pull + ./install.sh')
        update_check_safe()
        latest, cur = UPD['latest'], current_version()
        if not latest or vtuple(latest['version']) <= vtuple(cur):
            raise ApiError('Você já está na versão mais recente')
        ver = latest['version']
        base = f'https://github.com/{REPO}/releases/download/v{ver}/my-gui-{ver}.tar.gz'
        try:
            blob, _ = fetch(base, MAX_PACKAGE)
            want = fetch(base + '.sha256', 4096)[0].decode('ascii', 'replace').split()
        except urllib.error.URLError as e:
            raise ApiError(f'Falha ao baixar a atualização: {e.reason if hasattr(e, "reason") else e}')
        if not want or not re.fullmatch(r'[0-9a-f]{64}', want[0]):
            raise ApiError('arquivo .sha256 inválido')
        if not hmac.compare_digest(hashlib.sha256(blob).hexdigest(), want[0]):
            raise ApiError('SHA-256 do pacote não confere; nada foi instalado')
        _install(_unpack(blob, ver))
        res = _handoff(f'Atualizado para v{ver}')
        if res:
            return res
        # o servidor novo não subiu: volta a versão anterior
        restore_backup()
        res = _handoff(f'A v{ver} não iniciou; voltei para v{cur}')
        if res:
            return dict(res, ok=False, error=res['message'])
        write_state()
        raise ApiError(f'A v{ver} não iniciou e a volta falhou; rode: python3 {os.path.join(SHARE_DIR, "server.py")} --rollback')
    finally:
        _upd_lock.release()


# ------------------------------------------------------------------- http ---
TOKEN = secrets.token_urlsafe(24)
# monotonic: não conta o tempo de suspensão do notebook (com time.time() o relógio pula ao
# acordar e o watchdog derrubava o servidor antes de a página conseguir pingar)
last_ping = time.monotonic()
seen = False
bye_at = None


class H(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype='application/json; charset=utf-8'):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(body)

    def _host_ok(self):
        return self.headers.get('Host', '').rsplit(':', 1)[0] in ('127.0.0.1', 'localhost')

    def _tok_ok(self):
        return hmac.compare_digest(self.headers.get('X-Token', ''), TOKEN)

    def do_GET(self):
        global last_ping
        if not self._host_ok():
            return self._send(403, 'forbidden', 'text/plain')
        u = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(u.query)
        if u.path == '/' and hmac.compare_digest(qs.get('t', [''])[0], TOKEN):
            html = open(HTML_PATH, encoding='utf-8').read().replace('__TOKEN__', TOKEN)
            return self._send(200, html, 'text/html; charset=utf-8')
        if u.path == '/icon.svg':
            try:
                svg = open(os.path.join(os.path.dirname(HTML_PATH), 'my-gui.svg'), 'rb').read()
            except OSError:
                return self._send(404, 'not found', 'text/plain')
            return self._send(200, svg, 'image/svg+xml')
        if u.path == '/api/ping' and self._tok_ok():
            last_ping = time.monotonic()
            return self._send(200, {})
        self._send(404, 'not found', 'text/plain')

    def do_POST(self):
        global last_ping, seen, bye_at
        if not self._host_ok():
            return self._send(403, 'forbidden', 'text/plain')
        u = urllib.parse.urlparse(self.path)
        n = int(self.headers.get('Content-Length') or 0)
        if n > 16_000_000:
            return self._send(413, {'error': 'requisição grande demais'})
        raw = self.rfile.read(n) if n else b''
        if u.path == '/api/bye':  # sendBeacon não envia cabeçalhos
            if hmac.compare_digest(urllib.parse.parse_qs(u.query).get('t', [''])[0], TOKEN):
                bye_at = time.monotonic() + 6
            return self._send(200, {})
        if not self._tok_ok() or 'application/json' not in self.headers.get('Content-Type', ''):
            return self._send(403, {'error': 'não autorizado'})
        if u.path == '/api/ping':
            last_ping, seen, bye_at = time.monotonic(), True, None
        try:
            d = json.loads(raw or b'{}')
            self._send(200, api(u.path, d))
        except ApiError as e:
            self._send(200, dict(error=str(e), need_password=e.need_password))
        except pymysql.MySQLError as e:
            self._send(200, dict(error=emsg(e)))
        except Exception as e:  # noqa
            self._send(200, dict(error=f'{type(e).__name__}: {e}'))


def watchdog():
    while True:
        time.sleep(2)
        now = time.monotonic()
        if (bye_at and now > bye_at) or now - last_ping > (300 if seen else 120):
            drop_state()
            close_window()  # senão a janela fica órfã, pingando um servidor que não existe mais
            os._exit(0)


def _chrome_profile():
    return os.path.join(CONF_DIR, 'chrome')


def close_window():
    """Encerra o Chrome do perfil dedicado do my-gui (o servidor o abriu; não o deixa órfão)."""
    flag = f'--user-data-dir={_chrome_profile()}'.encode()
    me = os.getpid()
    try:
        pids = [int(d) for d in os.listdir('/proc') if d.isdigit()]
    except OSError:
        return
    for pid in pids:
        if pid == me:
            continue
        try:
            args = open(f'/proc/{pid}/cmdline', 'rb').read().split(b'\0')
            if flag in args:
                os.kill(pid, 15)
        except (OSError, ValueError):
            pass


def open_window(url):
    if os.environ.get('MY_GUI_NO_OPEN'):
        print(url, flush=True)
        return
    for b in ('google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser',
              'brave-browser', 'microsoft-edge'):
        exe = shutil.which(b)
        if exe:
            # Perfil próprio: o app_id da janela no Wayland inclui o nome do perfil
            # (chrome-127.0.0.1__-<perfil>); com perfil dedicado ele é sempre "Default" e
            # casa com o atalho do menu (ícone no dock). Também isola das suas extensões.
            prof = _chrome_profile()
            args = [exe, f'--user-data-dir={prof}', f'--app={url}', '--no-first-run',
                    '--no-default-browser-check', '--password-store=basic']
            if not os.path.isdir(os.path.join(prof, 'Default')):
                args.append('--window-size=1400,880')  # 1ª vez; depois o Chrome lembra o tamanho
            subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
            return
    webbrowser.open(url)


def code_version():
    """Hash dos arquivos instalados: detecta servidor antigo ainda rodando após uma atualização."""
    h = hashlib.sha1()
    d = os.path.dirname(HTML_PATH)
    for n in ('server.py', 'index.html', 'my-gui.svg', 'VERSION'):
        try:
            h.update(open(os.path.join(d, n), 'rb').read())
        except OSError:
            pass
    return h.hexdigest()[:12]


def existing_instance():
    try:
        st = json.load(open(STATE_FILE))
        req = urllib.request.Request(f"http://127.0.0.1:{st['port']}/api/ping",
                                     headers={'X-Token': st['token']})
        urllib.request.urlopen(req, timeout=1.5).read()
    except Exception:
        return None
    if st.get('ver') == code_version():
        return st
    # servidor de uma versão antiga: encerra (só se for mesmo o nosso) e sobe o novo
    try:
        pid = int(st['pid'])
        if b'server.py' in open(f'/proc/{pid}/cmdline', 'rb').read():
            os.kill(pid, 15)
            time.sleep(0.4)
    except Exception:
        pass
    try:
        os.remove(STATE_FILE)
    except OSError:
        pass
    return None


def main():
    global PORT
    alias = sys.argv[1] if len(sys.argv) > 1 else ''
    if alias == '--rollback':
        try:
            print('Restaurado para a v' + restore_backup())
        except (OSError, ValueError, KeyError):
            sys.exit('Não há backup para restaurar.')
        return
    extra = '&a=' + urllib.parse.quote(alias) if alias else ''
    st = existing_instance()
    if st:
        open_window(f"http://127.0.0.1:{st['port']}/?t={st['token']}{extra}")
        return
    srv = ThreadingHTTPServer(('127.0.0.1', 0), H)
    srv.daemon_threads = True
    port = PORT = srv.server_address[1]
    write_state()
    threading.Thread(target=watchdog, daemon=True).start()

    def _bye(*_):  # kill/Ctrl+C/logout: a janela não pode sobreviver ao servidor
        drop_state()
        close_window()
        os._exit(0)
    for sg in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sg, _bye)
    if can_update():
        _upd_load()
        threading.Thread(target=update_loop, daemon=True).start()
    open_window(f'http://127.0.0.1:{port}/?t={TOKEN}{extra}')
    srv.serve_forever()


if __name__ == '__main__':
    main()
