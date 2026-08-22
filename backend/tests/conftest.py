"""
Pytest bootstrap: make the `app` package importable when running from backend/.

These tests don't touch a real database or a real directory server — the async
DB session is mocked and ldap3 is patched — so no services need to be running.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
