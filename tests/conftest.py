from __future__ import annotations

import os
import tempfile


_TEST_DATA_DIR = tempfile.mkdtemp(prefix="agentkiln-tests-")
os.environ.setdefault("AML_DATABASE_PATH", f"{_TEST_DATA_DIR}/memory.db")
os.environ.setdefault("AML_LLM_MODE", "off")

