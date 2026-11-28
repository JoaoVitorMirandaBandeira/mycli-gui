// Formatador de SQL (SqlFormat em my-gui/index.html), usado no Ctrl+Shift+F e no painel do plano.
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const {test} = require('node:test');

const html = readFileSync(join(__dirname, '../my-gui/index.html'), 'utf8');
const src = html.slice(html.indexOf('/* ---------- formatar SQL'), html.indexOf('/* ---------- plano de execução: núcleo'));
const {format, lex} = new Function(src + '\nreturn SqlFormat;')();

const cases = [
  ['cláusulas em linhas e JOIN no nível do FROM',
    'SELECT * FROM `log_request_crm` lr inner join users u on u.id = lr.user_id inner join clients c on c.id = lr.client_id LIMIT 200;',
    'SELECT *\nFROM `log_request_crm` lr\nINNER JOIN users u ON u.id = lr.user_id\nINNER JOIN clients c ON c.id = lr.client_id\nLIMIT 200;'],
  ['uma coluna por linha, AND do WHERE em linhas, BETWEEN intacto',
    "select c.nome, count(*) as total from t c where c.a=1 and c.d between '2024-01-01' and '2024-12-31' group by c.nome order by total desc",
    "SELECT\n  c.nome,\n  count(*) AS total\nFROM t c\nWHERE c.a = 1\n  AND c.d BETWEEN '2024-01-01' AND '2024-12-31'\nGROUP BY c.nome\nORDER BY total DESC"],
  ['subqueries indentadas',
    'SELECT t.a FROM (SELECT a FROM x GROUP BY a) t WHERE t.a > (SELECT AVG(b) FROM y WHERE y.id = t.a)',
    'SELECT t.a\nFROM (\n  SELECT a\n  FROM x\n  GROUP BY a\n) t\nWHERE t.a > (\n  SELECT AVG(b)\n  FROM y\n  WHERE y.id = t.a\n)'],
  ['UPDATE com várias atribuições e comentário no fim da linha',
    "update t set a='x', b=now() where id in (1,2); -- fim\ndelete from t where a=1",
    "UPDATE t\nSET\n  a = 'x',\n  b = now()\nWHERE id IN (1, 2); -- fim\n\nDELETE FROM t\nWHERE a = 1"],
  ['INSERT com VALUES e ON DUPLICATE KEY',
    "insert into t (a,b) values (1,'x'),(2,'y') on duplicate key update b=values(b)",
    "INSERT INTO t (a, b)\nVALUES\n  (1, 'x'),\n  (2, 'y')\nON DUPLICATE KEY UPDATE b = VALUES(b)"],
  ['CTE e funções com FROM interno não quebram linha',
    'with x as (select 1 a) select distinct a, extract(year from d) from x where (a=1 or b=2)',
    'WITH x AS (\n  SELECT 1 a\n)\nSELECT DISTINCT\n  a,\n  extract(year FROM d)\nFROM x\nWHERE (a = 1 OR b = 2)'],
];
for (const [name, input, expected] of cases) {
  test(name, () => assert.equal(format(input), expected));
}

test('textos, identificadores e comentários não mudam; formatar duas vezes dá o mesmo resultado', () => {
  const sql = "select `from`, 'and  or\nselect', \"x;y\" /* a, b */ from `my table` where k = 'it''s' and j = 0x1F -- c\n order by 1";
  const keep = s => lex(s).filter(t => t.type !== 'word').map(t => t.v);
  const once = format(sql);
  assert.deepEqual(keep(once), keep(sql));
  assert.equal(format(once), once);
});

test('hint do otimizador continua na linha do SELECT', () => {
  assert.equal(format('SELECT /*+ JOIN_ORDER(p, c) */ c.nome, p.id FROM c JOIN p ON p.c = c.id'),
    'SELECT /*+ JOIN_ORDER(p, c) */\n  c.nome,\n  p.id\nFROM c\nJOIN p ON p.c = c.id');
});
