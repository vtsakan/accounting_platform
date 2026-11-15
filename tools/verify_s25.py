#!/usr/bin/env python3
"""Operator-only S25 entry point. Does not rebuild or rerun S24A's 661 tests."""
import sys
from legacy_migration import main

if __name__ == '__main__':
    try:
        main(['rehearse', *sys.argv[1:]])
    except (Exception, KeyboardInterrupt) as error:
        print('S25 stopped: ' + (str(error) if isinstance(error,(ValueError,RuntimeError)) else type(error).__name__) + '; existing demo/VM data retained',file=sys.stderr)
        sys.exit(1)
