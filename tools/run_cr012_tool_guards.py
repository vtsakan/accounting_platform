"""Operator-only retained176 deployment contracts; never touches the live VM."""
import json
from pathlib import Path
import sys
import unittest

from dev import ROOT
from r1_gate import require


def main():
    suite=unittest.TestSuite();loader=unittest.TestLoader()
    for pattern in ('test_preview_cr008*.py','test_preview_cr009_vm.py','test_preview_cr011_vm.py'):
        suite.addTests(loader.discover(str(ROOT/'tools'),pattern=pattern))
    result=unittest.TextTestRunner(verbosity=1).run(suite)
    require(result.testsRun==176 and result.wasSuccessful() and not result.skipped
        and not result.expectedFailures and not result.unexpectedSuccesses,'All176 retained deployment contracts must execute and pass')
    print(json.dumps({'tests_run':result.testsRun,'tests_passed':result.testsRun,'skips':0,'status':'Passed'}))


if __name__=='__main__':main()
