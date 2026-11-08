"""Strict, explicit accounting regression tracking on Django's unittest runner.

Only a registered, exactly matched financial assertion may be an expected
failure. Setup errors, ordinary assertions, skips and unexpected passes fail.
The ordinary Django runner still exposes the financial assertions as failures.
"""

from decimal import Decimal
import json
import os
from pathlib import Path
import unittest

from django.test.runner import DiscoverRunner

REGISTRY = json.loads(Path(__file__).with_name("regression_cases.json").read_text(encoding="utf-8"))
CASES = {case["case_id"]: case for case in REGISTRY["cases"]}
if len(CASES) != len(REGISTRY["cases"]) or any(case["expected_outcome"] not in {"known_failure", "pass"} for case in CASES.values()):
    raise ValueError("Invalid accounting regression registry")


def regression_case(case_id):
    if case_id not in CASES:
        raise ValueError("Unregistered regression case: " + case_id)

    def decorate(function):
        function.regression_case_id = case_id
        return function
    return decorate


class KnownFinancialMismatch(AssertionError):
    def __init__(self, case_id, observed, wanted):
        self.case_id, self.observed, self.wanted = case_id, observed, wanted
        super().__init__(f"{case_id}: observed {observed!r}; required {wanted!r}")


def assert_financial_equal(test, observed, wanted, *, legacy):
    """Assert the correct outcome; recognise only the specific legacy mismatch."""
    if observed == wanted:
        return
    test.assertEqual(observed, legacy, "Unexpected failure pattern; not the recorded legacy defect")
    case_id = getattr(getattr(test, test._testMethodName), "regression_case_id")
    raise KnownFinancialMismatch(case_id, observed, wanted)


def case_for(test):
    case_id = getattr(getattr(test, getattr(test, "_testMethodName", ""), None), "regression_case_id", None)
    if not case_id:
        return None
    case = CASES[case_id]
    if test.id() != case["test"]:
        raise ValueError("Test identity differs from its reviewed regression registry: " + case_id)
    return case


class FinancialRegressionResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.case_results = []

    def record_case(self, test, outcome, **details):
        case = case_for(test)
        if case:
            self.case_results.append({**case, "outcome": outcome, **details})

    def addFailure(self, test, err):
        case = case_for(test)
        error = err[1]
        if (case and case["expected_outcome"] == "known_failure"
                and isinstance(error, KnownFinancialMismatch) and error.case_id == case["case_id"]):
            super().addExpectedFailure(test, err)
            self.record_case(test, "known_failure_reproduced", observed=error.observed, required=error.wanted)
        else:
            super().addFailure(test, err)
            self.record_case(test, "unexpected_failure", exception=err[0].__name__)

    def addSuccess(self, test):
        case = case_for(test)
        if case and case["expected_outcome"] == "known_failure":
            super().addUnexpectedSuccess(test)
            self.record_case(test, "unexpected_success")
        else:
            super().addSuccess(test)
            self.record_case(test, "passed")

    def addError(self, test, err):
        super().addError(test, err)
        self.record_case(test, "error", exception=err[0].__name__)

    def addSkip(self, test, reason):
        if case_for(test):
            error = AssertionError("A tracked financial regression must not be skipped")
            super().addFailure(test, (AssertionError, error, None))
            self.record_case(test, "skipped")
        else:
            super().addSkip(test, reason)

    def addExpectedFailure(self, test, err):
        # An ordinary @expectedFailure catches arbitrary exceptions, including
        # broken fixtures. It cannot establish this financial baseline.
        error = AssertionError("Use a registered exact financial assertion instead of @expectedFailure")
        self.addFailure(test, (AssertionError, error, None))

    def report(self):
        return {"tests_run": self.testsRun,
                "tests_passed": self.testsRun - sum(map(len, (self.failures, self.errors, self.expectedFailures,
                                                               self.unexpectedSuccesses, self.skipped))),
                "known_failures_reproduced": len(self.expectedFailures),
                "unexpected_failures": len(self.failures), "unexpected_errors": len(self.errors),
                "unexpected_successes": len(self.unexpectedSuccesses), "skips": len(self.skipped),
                "cases": sorted(self.case_results, key=lambda case: case["case_id"])}


class FinancialRegressionRunner(DiscoverRunner):
    def get_resultclass(self):
        return FinancialRegressionResult

    def run_tests(self, *args, **kwargs):
        if self.parallel > 1 or self.pdb or self.debug_sql:
            raise ValueError("Use the serial accounting runner without --pdb or --debug-sql")
        return super().run_tests(*args, **kwargs)

    def run_suite(self, suite, **kwargs):
        result = super().run_suite(suite, **kwargs)
        path = os.environ.get("ACCOUNTING_REGRESSION_REPORT")
        if path:
            Path(path).write_text(json.dumps(result.report(), ensure_ascii=False, indent=2,
                                            default=lambda value: str(value) if isinstance(value, Decimal) else repr(value)) + "\n",
                                  encoding="utf-8")
        return result
