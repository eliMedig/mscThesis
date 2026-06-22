"""Make the poc/ directory importable in tests"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
