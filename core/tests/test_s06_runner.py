"""Guard against falsely accepting broken fixtures or unrelated test failures."""

from decimal import Decimal
import io
import unittest
from unittest.mock import patch

from django.test import SimpleTestCase

from accounting.regression_runner import CASES, FinancialRegressionResult, assert_financial_equal, regression_case


class RegressionRunnerGuardTests(SimpleTestCase):
    def scenario(self, action):
        # Isolate harness examples so fixing BAL-001 later does not change the
        # guard tests' expectations or require choosing another live defect.
        guard = {"case_id": "GUARD-001", "expected_outcome": "known_failure", "test": "s06.guard.test_contract"}
        with patch.dict(CASES, {"GUARD-001": guard}):
            class Scenario(unittest.TestCase):
                @regression_case("GUARD-001")
                def test_contract(self):
                    action(self)

                def id(self):
                    return "s06.guard.test_contract"

            return unittest.TextTestRunner(stream=io.StringIO(), resultclass=FinancialRegressionResult,
                                           verbosity=0).run(unittest.TestSuite([Scenario("test_contract")]))

    def test_exact_known_financial_mismatch_is_recorded(self):
        result = self.scenario(lambda test: assert_financial_equal(test, None, Decimal("100.00"), legacy=None))
        self.assertTrue(result.wasSuccessful())
        self.assertEqual(len(result.expectedFailures), 1)
        self.assertEqual(result.report()["cases"][0]["outcome"], "known_failure_reproduced")

    def test_ordinary_assertion_is_an_unexpected_failure(self):
        result = self.scenario(lambda test: test.assertEqual("unrelated", "failure"))
        self.assertFalse(result.wasSuccessful())
        self.assertEqual((len(result.failures), len(result.expectedFailures)), (1, 0))

    def test_new_financial_failure_pattern_is_not_accepted(self):
        result = self.scenario(lambda test: assert_financial_equal(test, Decimal("2.00"), Decimal("100.00"), legacy=None))
        self.assertFalse(result.wasSuccessful())
        self.assertEqual((len(result.failures), len(result.expectedFailures)), (1, 0))

    def test_runtime_exception_is_an_unexpected_error(self):
        def broken_fixture(test):
            raise RuntimeError("Synthetic unrelated setup error")
        result = self.scenario(broken_fixture)
        self.assertFalse(result.wasSuccessful())
        self.assertEqual((len(result.errors), len(result.expectedFailures)), (1, 0))

    def test_unexpected_pass_requires_review(self):
        result = self.scenario(lambda test: test.assertEqual(1, 1))
        self.assertFalse(result.wasSuccessful())
        self.assertEqual(len(result.unexpectedSuccesses), 1)

    def test_tracked_skip_fails(self):
        result = self.scenario(lambda test: test.skipTest("Synthetic skip"))
        self.assertFalse(result.wasSuccessful())
        self.assertEqual(len(result.failures), 1)

    def test_broad_expected_failure_is_not_accepted(self):
        class BroadFailure(unittest.TestCase):
            @unittest.expectedFailure
            def test_failure(self):
                raise RuntimeError("Synthetic fixture error")
        result = unittest.TextTestRunner(stream=io.StringIO(), resultclass=FinancialRegressionResult,
                                         verbosity=0).run(unittest.TestSuite([BroadFailure("test_failure")]))
        self.assertFalse(result.wasSuccessful())
        self.assertEqual((len(result.failures), len(result.expectedFailures)), (1, 0))
