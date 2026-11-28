// Reescritas sugeridas a partir do plano (PlanRewrite em my-gui/index.html).
// O app confere cada uma com EXPLAIN; aqui garantimos que o texto gerado é o esperado e que
// padrões ambíguos não geram reescrita nenhuma.
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const {test} = require('node:test');

const html = readFileSync(join(__dirname, '../my-gui/index.html'), 'utf8');
const src = html.slice(html.indexOf('/* ---------- formatar SQL'), html.indexOf('/* ---------- plano de execução: visual'));
const {PlanCore: C, PlanRewrite: R} = new Function(src + '\nreturn {PlanCore, PlanRewrite};')();
const fixture = name => JSON.parse(readFileSync(join(__dirname, 'plans', name + '.json'), 'utf8'));
const plan = name => C.analyze({root: C.parse(fixture(name).plan), alias: {}});
const one = (sql, P = plan('mysql84-join'), notes = []) => R.rewrites(sql, P, notes).filter(x => x.kind !== 'hint');

test('subquery correlacionada com agregação vira LEFT JOIN agrupado', () => {
  const f = fixture('mysql84-derived'), [x] = one(f.sql, plan('mysql84-derived'));
  assert.equal(x.id, 'corr');
  assert.equal(x.sql,
    'SELECT t.curso, t.total FROM (SELECT curso_id AS curso, COUNT(*) AS total FROM inscricoes GROUP BY curso_id) t ' +
    'LEFT JOIN (SELECT c.id AS k, AVG(vagas) AS v FROM cursos c GROUP BY c.id) sq1 ON sq1.k = t.curso ' +
    'WHERE t.total > sq1.v');
});

test('COUNT correlacionado usa COALESCE e condições extras vão para o WHERE da derivada', () => {
  const P = plan('mysql84-derived');
  const [x] = one("SELECT u.nome, (SELECT COUNT(*) FROM pedidos p WHERE p.user_id = u.id AND p.status = 'pago') AS n FROM users u ORDER BY n DESC", P);
  assert.equal(x.sql,
    "SELECT u.nome, COALESCE(sq1.v, 0) AS n FROM users u " +
    "LEFT JOIN (SELECT p.user_id AS k, COUNT(*) AS v FROM pedidos p WHERE p.status = 'pago' GROUP BY p.user_id) sq1 ON sq1.k = u.id " +
    'ORDER BY n DESC');
});

test('subquery correlacionada ambígua não é reescrita', () => {
  const P = plan('mysql84-derived');
  for (const sql of [
    'SELECT * FROM t WHERE t.a > (SELECT AVG(x.v) FROM x WHERE x.k = t.k OR x.j = 1)',        // OR
    'SELECT * FROM t WHERE t.a > (SELECT AVG(x.v) FROM x WHERE x.k = t.k AND x.m = t.m)',     // duas correlações
    'SELECT * FROM t WHERE t.a > (SELECT AVG(x.v) FROM x WHERE x.k = t.k LIMIT 1)',           // LIMIT
    'SELECT * FROM t WHERE t.a > (SELECT x.v FROM x WHERE x.k = t.k)',                         // sem agregação
    'SELECT * FROM t WHERE t.a > (SELECT AVG(x.v) FROM x JOIN y ON y.id = x.y WHERE x.k = t.k)',
    'SELECT a FROM t WHERE t.a > (SELECT AVG(x.v) FROM x WHERE x.k = t.k) UNION SELECT 1',
  ]) assert.equal(one(sql, P).filter(x => x.id === 'corr').length, 0, sql);
  // sem subquery dependente no plano, a regra nem roda
  assert.equal(one('SELECT * FROM t WHERE t.a > (SELECT AVG(x.v) FROM x WHERE x.k = t.k)').length, 0);
});

test('DATE() e YEAR() sobre a coluna viram faixa, entre parênteses', () => {
  const [x] = one("SELECT * FROM i WHERE NOT DATE(i.criado_em) = '2024-02-29' AND YEAR(d) = 2023 OR DATE(`e`) BETWEEN '2024-01-01' AND '2024-12-31'");
  assert.equal(x.id, 'sarg');
  assert.equal(x.sql, "SELECT * FROM i WHERE NOT (i.criado_em >= '2024-02-29' AND i.criado_em < '2024-03-01') AND " +
    "(d >= '2023-01-01' AND d < '2024-01-01') OR (`e` >= '2024-01-01' AND `e` < '2025-01-01')");
  assert.equal(one("SELECT * FROM i WHERE DATE(c) = '2023-02-30' OR DATE(c) > '2024-01-01' OR t.date(c) = '2024-01-01'").length, 0,
    'data inválida, operador diferente de = e função qualificada ficam como estão');
});

test('número comparado com coluna de texto vira texto só com o aviso 1739', () => {
  const sql = 'SELECT * FROM t WHERE codigo = 123 AND tel IN (1, 2) AND outro = 5';
  assert.equal(one(sql).length, 0);
  const notes = [['Warning', 1739, "Cannot use ref access on index 'ix' due to type or collation conversion on field 'codigo'"],
    ['Warning', 1739, "Cannot use range access on index 'ix2' due to type or collation conversion on field 'tel'"]];
  const [x] = one(sql, plan('mysql84-join'), notes);
  assert.equal(x.sql, "SELECT * FROM t WHERE codigo = '123' AND tel IN ('1', '2') AND outro = 5");
});

test('conselhos: OFFSET grande e índice para ORDER BY … LIMIT', () => {
  const join = plan('mysql84-join');
  const [off] = R.advice('SELECT * FROM t ORDER BY criado_em DESC LIMIT 100000, 50', join);
  assert.match(off.t, /OFFSET de 100 mil/);
  assert.match(off.fix.sql, /WHERE criado_em < :ultimo_valor\nORDER BY criado_em DESC\nLIMIT 50/);
  assert.equal(R.advice('SELECT * FROM t LIMIT 50 OFFSET 20', join).length, 0);
  const single = C.analyze({root: C.parse({query_block: {select_id: 1, ordering_operation: {using_filesort: true,
    table: {table_name: 'i', access_type: 'ref', key: 'ix_status', rows_examined_per_scan: 50000, rows_produced_per_join: 50000, filtered: '100',
      cost_info: {read_cost: '10', eval_cost: '10'}, attached_condition: "(`app`.`i`.`status` = 'ativa')"}}}}), alias: {i: {table: 'inscricoes'}}});
  const idx = R.advice("SELECT * FROM inscricoes i WHERE i.status = 'ativa' ORDER BY i.criado_em DESC, i.id DESC LIMIT 20", single);
  assert.equal(idx.length, 1);
  assert.match(idx[0].fix.sql, /ON inscricoes \(status, criado_em, id\)/);
});

test('custo de subquery dependente conta multiplicado pelas execuções', () => {
  const P = plan('mysql84-derived');
  let dep; C.walk(P.root, n => { if (n.kind === 'table' && n.mult > 1) dep = n; });
  assert.ok(dep, 'a tabela da subquery dependente tem multiplicador');
  assert.ok(dep.mult > 1000);
  assert.ok(dep.share > dep.est.cost * 1000);
});

test('ordens de JOIN alternativas: tabela com filtro próprio vai para a frente, via JOIN_ORDER', () => {
  const f = fixture('mysql84-join'), P = plan('mysql84-join');
  const alts = R.rewrites(f.sql, P, [], {flavor: 'MySQL', version: '8.4.11'}).filter(x => x.kind === 'hint');
  assert.ok(alts.length >= 1);
  const current = R.topJoin(P).children.map(c => c.title);
  for (const x of alts) {
    assert.notDeepEqual(x.expect, current);
    assert.deepEqual([...x.expect].sort(), [...current].sort());
    assert.match(x.sql, new RegExp('^SELECT /\\*\\+ JOIN_ORDER\\(' + x.expect.join(', ') + '\\) \\*/ '));
    assert.equal(x.sql.replace(/ \/\*\+ JOIN_ORDER\([^)]*\) \*\//, ''), f.sql, 'só o hint muda');
  }
  assert.equal(R.rewrites(f.sql, P, [], {flavor: 'MariaDB', version: '11.4.2'}).filter(x => x.kind === 'hint').length, 0);
  assert.equal(R.rewrites(f.sql, P, [], {flavor: 'MySQL', version: '5.7.44'}).filter(x => x.kind === 'hint').length, 0);
});

test('diagnósticos do plano: índice na coluna de junção e estimativa chutada', () => {
  const P = C.analyze({root: C.parse({query_block: {select_id: 1, nested_loop: [
    {table: {table_name: 'u', access_type: 'ALL', rows_examined_per_scan: 5000, rows_produced_per_join: 500, filtered: '10.00',
      cost_info: {read_cost: '50', eval_cost: '50'}, attached_condition: "(`db`.`u`.`ativo` = 1)", used_columns: ['id', 'ativo']}},
    {table: {table_name: 'p', access_type: 'ALL', rows_examined_per_scan: 90000, rows_produced_per_join: 9000, filtered: '10.00', using_join_buffer: 'hash join',
      cost_info: {read_cost: '900', eval_cost: '900'}, attached_condition: "(`db`.`p`.`user_id` = `db`.`u`.`id`)", used_columns: ['id', 'user_id']}}]}}),
    alias: {u: {table: 'users'}, p: {table: 'pedidos'}}});
  const join = P.ins.find(x => /JOIN sem índice em pedidos/.test(x.t));
  assert.match(join.fix.sql, /ON pedidos \(user_id\)/);
  const full = P.ins.find(x => /Varredura completa em pedidos/.test(x.t));
  assert.match(full.fix.sql, /ON pedidos \(user_id\)/, 'tabela interna: coluna de junção no índice');
  const chute = P.ins.find(x => /Estimativa chutada em users/.test(x.t));
  assert.match(chute.p, /igualdade/);
  assert.equal(chute.fix.sql, 'ANALYZE TABLE users UPDATE HISTOGRAM ON ativo;');
});
