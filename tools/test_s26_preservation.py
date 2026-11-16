"""Operator-only regressions for the real S26 retained-source guard."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import verify_s26


@contextmanager
def fixture(expected=None):
    with tempfile.TemporaryDirectory(prefix='s26-preserved-source-') as directory:
        root = Path(directory)
        docs = root/'docs/implementation'
        (docs/'evidence').mkdir(parents=True)
        source = root/'accounting/retained.py'
        source.parent.mkdir()
        source.write_bytes(b'# retained source\n')
        digest = 'sha256:' + hashlib.sha256(source.read_bytes()).hexdigest()
        document = {'sha256': {'accounting/retained.py': digest if expected is None else expected}}
        (docs/'evidence/S26-preserved-source.json').write_text(json.dumps(document))
        with patch.object(verify_s26, 'ROOT', root), patch.object(verify_s26, 'DOCS', docs):
            yield source, digest


class PreservationContracts(unittest.TestCase):
    def test_published_s26_manifest_matches_the_unchanged_retained_files(self):
        manifest = json.loads((verify_s26.DOCS/'evidence/S26-preserved-source.json').read_text())
        self.assertEqual(verify_s26.ensure_preserved(), len(manifest['sha256']))
        self.assertGreater(verify_s26.ensure_preserved(), 0)

    def test_matching_prefixed_digest_is_accepted(self):
        with fixture():
            self.assertEqual(verify_s26.ensure_preserved(), 1)

    def test_changed_source_is_rejected_without_rewriting_the_manifest(self):
        with fixture() as (source, expected):
            source.write_bytes(b'# changed source\n')
            with self.assertRaisesRegex(RuntimeError, 'Retained source changed: accounting/retained.py') as raised:
                verify_s26.ensure_preserved()
            self.assertIn('expected='+expected, str(raised.exception))
            document = json.loads((verify_s26.DOCS/'evidence/S26-preserved-source.json').read_text())
            self.assertEqual(document['sha256']['accounting/retained.py'], expected)

    def test_malformed_digest_and_empty_manifest_are_rejected(self):
        for invalid in ('0'*64, 'SHA256:'+'0'*64, 'sha256:'+'g'*64, 'sha256:'+'0'*63, 7, False):
            with self.subTest(value=invalid), fixture(expected=invalid):
                with self.assertRaisesRegex(RuntimeError, 'Invalid retained-source SHA-256'):
                    verify_s26.ensure_preserved()
        with fixture():
            path = verify_s26.DOCS/'evidence/S26-preserved-source.json'
            path.write_text(json.dumps({'sha256': {}}))
            with self.assertRaisesRegex(RuntimeError, 'Invalid retained-source manifest'):
                verify_s26.ensure_preserved()


if __name__ == '__main__':
    unittest.main()
