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
