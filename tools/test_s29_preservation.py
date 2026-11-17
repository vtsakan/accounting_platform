"""Operator-run stdlib source-integrity contracts; no application execution."""
import hashlib,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import verify_s29


class SourceContracts(unittest.TestCase):
    def fixture(self,directory):
        root=Path(directory);docs=root/'docs/implementation';(docs/'evidence').mkdir(parents=True)
        (root/'retained.py').write_text('assert True\n')
        manifest={'sha256':{'retained.py':'sha256:'+hashlib.sha256((root/'retained.py').read_bytes()).hexdigest()}}
        file=docs/'evidence/S29-preserved-source.json';file.write_text(json.dumps(manifest))
        return root,docs,file,manifest

    def test_real_source_manifest_matches_published_files(self):
        self.assertGreater(verify_s29.preserved(),327)

    def test_matching_source_is_checked_without_writes(self):
        with tempfile.TemporaryDirectory() as d:
            root,docs,file,_=self.fixture(d);before=file.read_bytes()
            with patch.object(verify_s29,'ROOT',root),patch.object(verify_s29,'DOCS',docs):self.assertEqual(verify_s29.preserved(),1)
            self.assertEqual(file.read_bytes(),before)

    def test_changed_source_is_rejected_and_not_rebound(self):
        with tempfile.TemporaryDirectory() as d:
            root,docs,file,_=self.fixture(d);before=file.read_bytes();(root/'retained.py').write_text('assert False\n')
            with patch.object(verify_s29,'ROOT',root),patch.object(verify_s29,'DOCS',docs),self.assertRaises(RuntimeError):verify_s29.preserved()
            self.assertEqual(file.read_bytes(),before)

    def test_empty_malformed_and_escaping_bindings_are_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root,docs,file,_=self.fixture(d)
            for entries in ({},None,{'retained.py':'0'*64},{'../retained.py':'sha256:'+'0'*64}):
                file.write_text(json.dumps({'sha256':entries}))
                with self.subTest(entries=entries),patch.object(verify_s29,'ROOT',root),patch.object(verify_s29,'DOCS',docs),self.assertRaises(RuntimeError):verify_s29.preserved()


if __name__=='__main__':unittest.main()
