// Núcleo do Visual Explain (PlanCore em my-gui/index.html): leitura do JSON, diagnósticos e layout.
// As fixtures mysql84-* são saídas reais do MySQL 8.4; a do MariaDB segue o formato documentado.
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const {test} = require('node:test');

const html = readFileSync(join(__dirname, '../my-gui/index.html'), 'utf8');
const core = html.slice(html.indexOf('/* ---------- plano de execução: núcleo'),
  html.indexOf('/* ---------- plano de execução: visual'));
const C = new Function(core + '\nreturn PlanCore;')();
const fixture = name => JSON.parse(readFileSync(join(__dirname, 'plans', name + '.json'), 'utf8'));
const alias = {i: {table: 'inscricoes'}, c: {table: 'candidatos'}, cu: {table: 'cursos'}};
function build(name) {
  const f = fixture(name), P = {root: C.parse(f.plan), alias};
  return C.layout(C.analyze(P));
}
const nodes = (P, kind) => { const r = []; C.walk(P.root, n => { if (!kind || n.kind === kind) r.push(n); }); return r; };

test('JOIN de três tabelas vira uma fileira de nested loops sob ORDER BY e GROUP BY', () => {
  const P = build('mysql84-join');
  assert.deepEqual(P.root.children.map(n => n.title), ['ORDER BY']);
  assert.deepEqual(P.root.children[0].children.map(n => n.title), ['GROUP BY']);
  const nl = nodes(P, 'nl');
  assert.equal(nl.length, 1);
  assert.equal(nl[0].children.length, 3);
  assert.equal(nl[0].joins.length, 2);
  assert.deepEqual(nodes(P, 'table').map(n => n.title).sort(), ['c', 'cu', 'i']);
  const pct = nodes(P, 'table').reduce((s, n) => s + n.pct, 0);
  assert.ok(Math.abs(pct - 1) < 1e-9, 'as partes do custo somam 100%');
});

test('varredura completa gera diagnóstico com sugestão de índice pelas colunas do WHERE', () => {
  const P = build('mysql84-join');
  const full = P.ins.find(x => x.n.access === 'ALL');
  assert.ok(full, 'diagnóstico de varredura completa');
  assert.equal(P.ins[0], full, 'o mais grave vem primeiro');
  assert.match(full.fix.sql, /CREATE INDEX ix_candidatos_cidade\s+ON candidatos \(cidade/);
  assert.ok(P.ins.some(x => /filesort/.test(x.t)));
  assert.ok(P.ins.some(x => /temporária/.test(x.t)));
});

test('tabela derivada e subquery dependente ficam em molduras e a dependente é alertada', () => {
  const P = build('mysql84-derived');
  assert.equal(P.frames.length, 2);
  const dep = nodes(P, 'block').find(n => n.dependent);
  assert.ok(dep && dep.sub);
  assert.ok(P.ins.some(x => x.n === dep && x.sev === 'hi' && /execuções/.test(x.p)));
  assert.ok(nodes(P, 'table').some(n => n.derived));
});

test('UNION e window functions aparecem no diagrama (o Workbench 8 os perde)', () => {
  const U = build('mysql84-union');
  assert.ok(nodes(U, 'op').some(n => n.title === 'UNION'));
  assert.equal(nodes(U, 'block').length, 3);
  const W = build('mysql84-window');
  assert.ok(nodes(W, 'op').some(n => n.title === 'WINDOW'));
  assert.ok(nodes(W, 'table').length >= 1);
});

test('formato do MariaDB: rows/cost sem cost_info, filesort e block-nl-join', () => {
  const P = build('mariadb-bnl');
  const [i, cu] = ['i', 'cu'].map(t => nodes(P, 'table').find(n => n.title === t));
  assert.equal(i.est.scan, 150000);
  assert.equal(i.est.rows, 60000);
  assert.equal(i.est.cost, 24.5);
  assert.ok(cu.flags.some(f => /join buffer/.test(f)));
  assert.equal(nodes(P, 'nl')[0].joins[0], 'block nested loop');
  assert.ok(nodes(P, 'op').some(n => n.title === 'ORDER BY' && n.flags.includes('filesort')));
  assert.ok(P.ins.some(x => /JOIN sem índice/.test(x.t)));
});

test('chaves desconhecidas viram operação genérica em vez de sumir', () => {
  const P = C.layout(C.analyze({root: C.parse({query_block: {select_id: 1, nova_operacao: {table: {table_name: 't', access_type: 'ref', key: 'k'}}}})}));
  assert.equal(P.root.children[0].title, 'NOVA OPERACAO');
  assert.equal(P.root.children[0].children[0].title, 't');
});

test('nós não se sobrepõem no layout', () => {
  for (const name of ['mysql84-join', 'mysql84-derived', 'mysql84-union', 'mysql84-window', 'mariadb-bnl']) {
    const P = build(name), boxes = [];
    for (const n of P.nodes) {
      if (n.kind === 'nl') n._d.forEach(d => boxes.push([d.x - 20, d.y - 20, d.x + 20, d.y + 20]));
      else boxes.push([n.x - n.w / 2, n.y, n.x + n.w / 2, n.y + n.h]);
    }
    for (let a = 0; a < boxes.length; a++) for (let b = a + 1; b < boxes.length; b++) {
      const [p, q] = [boxes[a], boxes[b]];
      assert.ok(p[2] <= q[0] || q[2] <= p[0] || p[3] <= q[1] || q[3] <= p[1], `${name}: caixas ${a} e ${b} se sobrepõem`);
    }
    assert.ok(P.W > 0 && P.H > 0);
  }
});

test('números com sufixo e formatação pt-BR', () => {
  assert.equal(C.num('1.50'), 1.5);
  assert.equal(C.num('3K'), 3000);
  assert.equal(C.num('2M'), 2e6);
  assert.equal(C.num(null), null);
  assert.equal(C.fmtN(152340), '152,3 mil');
  assert.equal(C.fmtN(1692), '1.692');
  assert.equal(C.pctS(0.469), '46,9%');
  assert.equal(C.cleanCond("(`app`.`i`.`status` = 'ativa')"), "(i.status = 'ativa')");
});

test('JSON que não é plano do MySQL dá erro claro', () => {
  assert.throws(() => C.parse({query: 'x'}), /query_block/);
});
