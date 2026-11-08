#!/usr/bin/env python3
"""Continuing CI: test all current source, preserving reviewed regression policy.

Unlike the historical S07 verifier, this allows planned model/migration changes,
discovers new tests, and follows reviewed known-failure outcomes in the registry.
It requires the real Docker image gate and never rewrites step records.
"""

from verify_s07 import main


if __name__ == "__main__":
    main(current_source=True)
