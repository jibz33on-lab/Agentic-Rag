import sys
from pathlib import Path

# src/ rather than src/bedrock_rag: the package is what gets imported, and its
# name is what keeps these modules distinct from project 01's. See
# src/bedrock_rag/__init__.py.
sys.path.insert(0, str(Path(__file__).parent / "src"))
