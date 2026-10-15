"""Run regression tests without inheriting deployed Streamlit secrets."""
import os
import unittest
from pathlib import Path


def main():
    import streamlit as st
    # Tests requiring database configuration supply their own mock settings.
    # Never let the developer's production connection leak into AppTest runs.
    os.environ.pop('DATABASE_URL', None)
    st.secrets = {}
    root = Path(__file__).resolve().parent
    suite = unittest.defaultTestLoader.discover(str(root / 'tests'))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
