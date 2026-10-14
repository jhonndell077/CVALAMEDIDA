"""Regenerate the Firebase manifest from main.py before deployment on Windows."""
import os
from pathlib import Path

from firebase_functions.private.serving import functions_as_yaml, get_functions

root = Path(__file__).resolve().parent
os.chdir(root)
(root / "functions.yaml").write_text(
    functions_as_yaml(get_functions()), encoding="utf-8"
)
print("Manifiesto de Firebase actualizado desde main.py.")
