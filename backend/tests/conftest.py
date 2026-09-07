"""Puts backend/ on sys.path so pytest works from the repo root or from
backend/ -- the tests import `trading`, `ensemble` etc. as top-level modules,
exactly as the production code does."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
