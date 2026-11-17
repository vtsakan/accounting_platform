"""Operator-executed stdlib guard contracts; no Django, Docker or app tests."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import verify_s27


def sha(data):
    return 'sha256:'+hashlib.sha256(data).hexdigest()


class PortablePreservationContracts(unittest.TestCase):
    def make_fixture(self, directory):
        root=Path(directory);docs=root/'docs/implementation';(docs/'evidence').mkdir(parents=True)
        bodies={'accounting/tests_old.py':b'def test_original():\n    assert 1 == 1\n',
            'accounting/tests_boundary.py':b'def test_boundary():\n    assert True\n'}
        for name,body in bodies.items():
            path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(body)
        manifest={'sha256':{'accounting/tests_old.py':sha(bodies['accounting/tests_old.py'])},
            'test_methods':{name:{'retained.test_original':'historical-ast-reference'} for name in bodies}}
        bindings={'sha256':{name:sha(body) for name,body in bodies.items()}}
        (docs/'evidence/S27-preserved-source.json').write_text(json.dumps(manifest))
        (docs/'evidence/S27-test-source-bindings.json').write_text(json.dumps(bindings))
        return root,docs,bodies,bindings

    def test_real_published_source_bindings_cover_every_retained_test(self):
        self.assertEqual(verify_s27.preserved(),327)
        bindings=json.loads((verify_s27.DOCS/'evidence/S27-test-source-bindings.json').read_text())['sha256']
        self.assertEqual(len(bindings),23)

    def test_exact_bytes_are_checked_without_ast_serialization(self):
        with tempfile.TemporaryDirectory() as directory:
            root,docs,_,_=self.make_fixture(directory)
            with patch.object(verify_s27,'ROOT',root),patch.object(verify_s27,'DOCS',docs),patch.object(
                    verify_s27.ast,'dump',side_effect=AssertionError('AST formatting must not be consulted')):
                self.assertEqual(verify_s27.preserved(),2)

    def test_changed_original_or_fixture_is_denied_without_manifest_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            root,docs,bodies,_=self.make_fixture(directory)
            reports={p:p.read_bytes() for p in (docs/'evidence').iterdir()}
            with patch.object(verify_s27,'ROOT',root),patch.object(verify_s27,'DOCS',docs):
                for name,body in bodies.items():
                    with self.subTest(name=name):
                        (root/name).write_bytes(body+b'# changed source\n')
                        with self.assertRaisesRegex(RuntimeError,'Retained source changed'):
                            verify_s27.preserved()
                        (root/name).write_bytes(body)
            for path,data in reports.items():self.assertEqual(path.read_bytes(),data)

    def test_missing_malformed_or_conflicting_test_bindings_are_denied(self):
        with tempfile.TemporaryDirectory() as directory:
            root,docs,_,bindings=self.make_fixture(directory)
            changes=[]
            missing=copy.deepcopy(bindings);del missing['sha256']['accounting/tests_boundary.py'];changes.append(missing)
            malformed=copy.deepcopy(bindings);malformed['sha256']['accounting/tests_boundary.py']='0'*64;changes.append(malformed)
            conflict=copy.deepcopy(bindings);conflict['sha256']['accounting/tests_old.py']='sha256:'+'0'*64;changes.append(conflict)
            changes.extend([{'sha256':{}},{'sha256':None}])
            with patch.object(verify_s27,'ROOT',root),patch.object(verify_s27,'DOCS',docs):
                for value in changes:
                    with self.subTest(value=value):
                        (docs/'evidence/S27-test-source-bindings.json').write_text(json.dumps(value))
                        with self.assertRaises(RuntimeError):verify_s27.preserved()


if __name__=='__main__':unittest.main()
