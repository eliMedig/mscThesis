"""Make the poc/ directory importable in tests (so `import config` / `from teaf …`
resolve) regardless of how pytest is launched."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
