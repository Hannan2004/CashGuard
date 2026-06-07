import json
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).parent / "data"

def load_json(filename: str) -> list[dict[str, Any]]:
    file_path = DATA_DIR / filename

    with file_path.open("r", encoding="utf-8") as file:
        return json.load(file)
    
def find_one(items: list[dict[str, Any]], key: str, value: str) -> dict[str, Any] | None:
    for item in items:
        if item.get(key) == value:
            return item
        
    return None