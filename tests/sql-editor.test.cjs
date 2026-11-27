const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const {test} = require('node:test');

const examples = require('./sql-statements.json');
const html = readFileSync(join(__dirname, '../my-gui/index.html'), 'utf8');
const bundleStart = html.indexOf('<!-- BEGIN SQL EDITOR BUNDLE -->');
const bundle = html.slice(html.indexOf('<script>', bundleStart) + '<script>'.length,
  html.indexOf('</script>', bundleStart));
const {EditorState} = new Function(bundle + '\nreturn SqlEditor;')();
const statements = html.slice(html.indexOf('/* ---------- editor SQL ---------- */'),
  html.indexOf('/* ---------- CodeMirror ---------- */'));
const dangerFn = html.slice(html.indexOf('function danger('), html.indexOf('async function run('));
const {sqlStatements, statementAt, foldAt, danger} = new Function(
  statements + dangerFn + '\nreturn {sqlStatements,statementAt,foldAt,danger};'
)();

for (const {name, sql, statements: expected, error} of examples) {
  test(name, () => {
    if (error) {
      assert.throws(() => sqlStatements(sql), {message: new RegExp(error)});
    } else {
      const parsed = sqlStatements(sql).map(({from, to, bodyEnd, delimiter}) =>
        sql.slice(from, to > bodyEnd ? to - delimiter.length : to).trimEnd()
      );
      assert.deepEqual(parsed, expected);
    }
  });
}

test('cursor uses the previous statement in gaps and the first one before any SQL', () => {
  const sql = '-- before first\nSELECT 1;\n\n-- between\nSELECT 2;\n';
  const {doc} = EditorState.create({doc: sql});
  const cases = [[3, 'SELECT 1;'], [sql.indexOf('\n\n') + 1, 'SELECT 1;'],
    [sql.indexOf('-- between') + 3, 'SELECT 1;'], [sql.length, 'SELECT 2;']];
  for (const [pos, expected] of cases) {
    const {from, to} = statementAt(doc, pos);
    assert.equal(sql.slice(from, to), expected);
  }
});

test('the cursor and fold inside a stored procedure use its entire definition', () => {
  const sql = 'DELIMITER //\nCREATE PROCEDURE p()\nBEGIN\nSELECT 1;\nUPDATE t SET v=2;\nEND//\nDELIMITER ;\nSELECT 3;';
  const {doc} = EditorState.create({doc: sql});
  const range = statementAt(doc, sql.indexOf('UPDATE'));
  assert.equal(range.delimiter, '//');
  assert.equal(sql.slice(range.from, range.to), sql.slice(sql.indexOf('CREATE'), sql.indexOf('END//') + 5));
  assert.deepEqual(foldAt(doc, range.from), {from: sql.indexOf('\nBEGIN'), to: range.to});
  assert.equal(danger(sql), undefined);
});

test('danger ignores quoted commands and comments, and flags executable comments', () => {
  assert.equal(danger("SELECT 'literal; DROP TABLE t'; -- DELETE FROM t"), undefined);
  assert.equal(danger('/*!50000 DROP TABLE t */;'), '/*!50000 DROP TABLE t */');
  assert.equal(danger("UPDATE t SET col='WHERE' /* WHERE id=1 */;"), "UPDATE t SET col='WHERE'");
  assert.equal(danger('DELETE FROM t WHERE col=1;'), undefined);
});

test('large documents only parse on demand for execution', () => {
  const {doc} = EditorState.create({doc: 'SELECT 1;\n'.repeat(40000) + 'SELECT 2;'});
  assert.equal(foldAt(doc, 0), null);
  const {from, to} = statementAt(doc, doc.length);
  assert.equal(doc.sliceString(from, to), 'SELECT 2;');
});
