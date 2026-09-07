from datetime import date
from pathlib import Path
import importlib.util

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("plymouth_ingest", HERE / "plymouth_ingest.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

text = (HERE / "fixtures" / "plymouth_2026-08-29.txt").read_text()
rows = mod.normalize(text, date(2026, 8, 29), min_minutes=60)

got = [(r.sheet, r.start, r.end, r.duration_minutes) for r in rows]
expected = [
    ("Rink A", "07:00", "08:30", 90),
    ("Rink A", "20:30", "24:00", 210),
    ("Rink B", "20:45", "24:00", 195),
    ("Rink C", "21:00", "24:00", 180),
]
assert got == expected, (got, expected)
print("PASS:", got)
