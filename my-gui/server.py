#!/usr/bin/env python3
"""my-gui — cliente MySQL local e leve, numa janela do navegador.

Usa os aliases de ~/.myclirc ([alias_dsn]). Só escuta em 127.0.0.1, com token.
Senhas nunca vão para a página. Encerra sozinho quando a janela é fechada.
"""
import datetime, decimal, hmac, json, os, re, secrets, shutil, subprocess, sys
import threading, time, urllib.parse, urllib.request, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pymysql
import pymysql.cursors

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
                db=(u.path or '').lstrip('/') or None)
    return out


# ------------------------------------------------------------------- pool ---
class Pool:
    def __init__(self):
        self.conns, self.pw, self.locks = {}, {}, {}
        self.glock = threading.Lock()

    def lock(self, alias):
        with self.glock:
            return self.locks.setdefault(alias, threading.RLock())

    def drop(self, alias):
        c = self.conns.pop(alias, None)
        if c is not None:
            try:
                c._force_close()
            except Exception:
                pass

    def get(self, alias):
        al = load_aliases().get(alias)
        if not al:
            raise ApiError(f"Alias '{alias}' não existe no ~/.myclirc")
        pw = al['password'] if al['password'] is not None else self.pw.get(alias)
        if pw is None:
            raise ApiError('Senha necessária', need_password=True)
        c = self.conns.get(alias)
        if c is not None:
            try:
                c.ping(reconnect=True)
                return c
            except Exception:
                self.drop(alias)
        try:
            c = pymysql.connect(
                host=al['host'], port=al['port'], user=al['user'], password=pw,
                database=al['db'], connect_timeout=8, read_timeout=900,
                autocommit=True, charset='utf8mb4',
                cursorclass=pymysql.cursors.SSCursor)
        except pymysql.MySQLError as e:
            if e.args and e.args[0] == 1045 and alias in self.pw:
                del self.pw[alias]
                raise ApiError(emsg(e), need_password=True)
            raise ApiError(emsg(e))
        self.conns[alias] = c
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


def run_query(alias, db, sql, limit):
    limit = max(1, min(int(limit or 1000), 20000))
    results, err = [], None
    with pool.lock(alias):
        cur_db = db or None
        for st in split_sql(sql):
            t0 = time.time()
            try:
                c = pool.get(alias)
                if cur_db is None:
                    cur_db = c.db
                elif c.db != cur_db:
                    c.select_db(cur_db)
                cur = c.cursor()
                cur.execute(st)
                if cur.description:
                    cols = [d[0] for d in cur.description]
                    rows = cur.fetchmany(limit + 1)
                    trunc = len(rows) > limit
                    res = dict(sql=st, columns=cols, truncated=trunc,
                               rows=[[jv(v) for v in r] for r in rows[:limit]])
                    if trunc:
                        pool.drop(alias)  # descarta o resto sem ler tudo
                    else:
                        cur.close()
                else:
                    res = dict(sql=st, columns=[], rows=[], affected=cur.rowcount)
                    cur.close()
                m = re.match(r'use\s+`?([^`\s]+)`?\s*$', st, re.I)
                if m and alias in pool.conns:
                    cur_db = pool.conns[alias].db = m.group(1)
                res['ms'] = int((time.time() - t0) * 1000)
                results.append(res)
            except ApiError as e:
                err = str(e)
                return dict(results=results, error=err, db=cur_db, need_password=e.need_password)
            except pymysql.MySQLError as e:
                err = emsg(e)
                if not e.args or e.args[0] in (2006, 2013, 2055) or isinstance(e, pymysql.InterfaceError):
                    pool.drop(alias)
                break
    return dict(results=results, error=err, db=cur_db)


def simple(alias, db, sql, params=None):
    with pool.lock(alias):
        c = pool.get(alias)
        if db and c.db != db:
            c.select_db(db)
        cur = c.cursor()
        try:
            cur.execute(sql, params)
            return cur.fetchall()
        finally:
            cur.close()


def bq(name):
    return '`' + name.replace('`', '``') + '`'


def api(path, d):
    if path == '/api/ping':
        return {}
    if path == '/api/aliases':
        return dict(aliases=[
            dict(name=k, host=v['host'], port=v['port'], user=v['user'],
                 db=v['db'] or '')
            for k, v in load_aliases().items()])
    alias = d.get('alias')
    if path == '/api/password':
        pool.pw[alias] = d.get('password', '')
        pool.drop(alias)
        return {}
    if path == '/api/databases':
        rows = simple(alias, None, 'SHOW DATABASES')
        return dict(databases=sorted((r[0] for r in rows), key=str.lower),
                    db=pool.conns[alias].db or '')
    if path == '/api/tables':
        rows = simple(alias, d.get('db'), 'SHOW FULL TABLES FROM ' + bq(d['db']))
        return dict(tables=[[r[0], r[1]] for r in rows])
    if path == '/api/columns':
        rows = simple(alias, None,
                      'SELECT table_name, column_name, column_type, column_key '
                      'FROM information_schema.columns WHERE table_schema=%s '
                      'ORDER BY table_name, ordinal_position LIMIT 80000', (d['db'],))
        cols = {}
        for t, c, ty, k in rows:
            cols.setdefault(jv(t), []).append([jv(c), jv(ty), jv(k)])
        return dict(columns=cols)
    if path == '/api/query':
        return run_query(alias, d.get('db'), d.get('sql', ''), d.get('limit'))
    raise ApiError('rota desconhecida')


# ------------------------------------------------------------------- http ---
TOKEN = secrets.token_urlsafe(24)
last_ping = time.time()
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
            last_ping = time.time()
            return self._send(200, {})
        self._send(404, 'not found', 'text/plain')

    def do_POST(self):
        global last_ping, seen, bye_at
        if not self._host_ok():
            return self._send(403, 'forbidden', 'text/plain')
        u = urllib.parse.urlparse(self.path)
        n = int(self.headers.get('Content-Length') or 0)
        raw = self.rfile.read(n) if n else b''
        if u.path == '/api/bye':  # sendBeacon não envia cabeçalhos
            if hmac.compare_digest(urllib.parse.parse_qs(u.query).get('t', [''])[0], TOKEN):
                bye_at = time.time() + 6
            return self._send(200, {})
        if not self._tok_ok() or 'application/json' not in self.headers.get('Content-Type', ''):
            return self._send(403, {'error': 'não autorizado'})
        if u.path == '/api/ping':
            last_ping, seen, bye_at = time.time(), True, None
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
        now = time.time()
        if (bye_at and now > bye_at) or now - last_ping > (300 if seen else 120):
            try:
                os.remove(STATE_FILE)
            except OSError:
                pass
            os._exit(0)


def open_window(url):
    if os.environ.get('MY_GUI_NO_OPEN'):
        print(url, flush=True)
        return
    for b in ('google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser',
              'brave-browser', 'microsoft-edge'):
        exe = shutil.which(b)
        if exe:
            subprocess.Popen([exe, f'--app={url}', '--class=my-gui', '--window-size=1400,880',
                              '--no-first-run'],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
            return
    webbrowser.open(url)


def existing_instance():
    try:
        st = json.load(open(STATE_FILE))
        req = urllib.request.Request(f"http://127.0.0.1:{st['port']}/api/ping",
                                     headers={'X-Token': st['token']})
        urllib.request.urlopen(req, timeout=1.5).read()
        return st
    except Exception:
        return None


def main():
    alias = sys.argv[1] if len(sys.argv) > 1 else ''
    extra = '&a=' + urllib.parse.quote(alias) if alias else ''
    st = existing_instance()
    if st:
        open_window(f"http://127.0.0.1:{st['port']}/?t={st['token']}{extra}")
        return
    srv = ThreadingHTTPServer(('127.0.0.1', 0), H)
    srv.daemon_threads = True
    port = srv.server_address[1]
    os.makedirs(STATE_DIR, exist_ok=True)
    fd = os.open(STATE_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump(dict(port=port, token=TOKEN, pid=os.getpid()), f)
    threading.Thread(target=watchdog, daemon=True).start()
    open_window(f'http://127.0.0.1:{port}/?t={TOKEN}{extra}')
    srv.serve_forever()


if __name__ == '__main__':
    main()
