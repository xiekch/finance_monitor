import sys
from pathlib import Path

# Make project root importable so tests can do `from app import ...`
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
