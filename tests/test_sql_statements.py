import importlib.util
import json
from pathlib import Path
import unittest

TEST_DIR = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('my_gui_server', TEST_DIR.parent / 'my-gui' / 'server.py')
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


class SplitSqlTest(unittest.TestCase):
    def test_shared_sql_cases(self):
        examples = json.loads((TEST_DIR / 'sql-statements.json').read_text())
        for example in examples:
            with self.subTest(example['name']):
                if 'error' in example:
                    with self.assertRaisesRegex(server.ApiError, example['error']):
                        server.split_sql(example['sql'])
                else:
                    self.assertEqual(server.split_sql(example['sql']), example['statements'])


class ExplainTargetTest(unittest.TestCase):
    def test_accepts_one_explainable_statement(self):
        for sql, expected in [
            ('SELECT 1;', 'SELECT 1'),
            ('  -- antes\nWITH x AS (SELECT 1) SELECT * FROM x', 'WITH x AS (SELECT 1) SELECT * FROM x'),
            ("UPDATE t SET a = ';' WHERE id = 1;", "UPDATE t SET a = ';' WHERE id = 1"),
            ('(SELECT 1) UNION (SELECT 2)', '(SELECT 1) UNION (SELECT 2)'),
            ('EXPLAIN FORMAT=TREE SELECT * FROM t', 'SELECT * FROM t'),
            ('desc select * from t', 'select * from t'),
        ]:
            with self.subTest(sql):
                self.assertEqual(server.explain_target(sql), expected)

    def test_rejects_other_statements(self):
        for sql, error in [
            ('SELECT 1; SELECT 2;', 'única consulta'),
            ('-- nada', 'Nenhuma consulta'),
            ('DROP TABLE t', 'disponível para'),
            ('DESCRIBE t', 'disponível para'),
            ('EXPLAIN ANALYZE SELECT 1', 'disponível para'),
            ('SET @a = 1', 'disponível para'),
        ]:
            with self.subTest(sql), self.assertRaisesRegex(server.ApiError, error):
                server.explain_target(sql)

    def test_server_flavor(self):
        self.assertEqual(server.server_flavor('8.4.11'), ('MySQL', (8, 4, 11)))
        self.assertEqual(server.server_flavor('10.11.6-MariaDB-0+deb12u1'), ('MariaDB', (10, 11, 6)))
        self.assertEqual(server.server_flavor('5.7.44-log'), ('MySQL', (5, 7, 44)))


class MeasureTest(unittest.TestCase):
    def test_only_read_statements_are_measured(self):
        for sql in ('SELECT 1', 'WITH x AS (SELECT 1) SELECT * FROM x', '(SELECT 1) UNION (SELECT 2)', 'TABLE t'):
            with self.subTest(sql):
                self.assertTrue(server.MEASURABLE.match(server.sql_command(server.explain_target(sql))))
        for sql in ('UPDATE t SET a = 1', 'DELETE FROM t', 'INSERT INTO t SELECT * FROM u'):
            with self.subTest(sql):
                self.assertFalse(server.MEASURABLE.match(server.sql_command(server.explain_target(sql))))

    def test_analyze_root_line(self):
        line = '-> Limit: 50 row(s)  (cost=10 rows=50) (actual time=0.5..412.3 rows=50 loops=1)\n    -> Sort ...'
        m = server.ANALYZE_ROOT.search(line)
        self.assertEqual((float(m[1]), float(m[2]), int(m[3])), (412.3, 50.0, 1))
