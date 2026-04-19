import csv
import json
from pathlib import Path

SRC = Path(__file__).parent / "telemetry_recording.json"
DST = Path(__file__).parent / "telemetry_recording.csv"

FIELD_MAP = [
    ("posx", "pos_x_m"),
    ("posy", "pos_y_m"),
    ("posz", "pos_z_m"),
    ("velx", "vel_x_ms"),
    ("vely", "vel_y_ms"),
    ("velz", "vel_z_ms"),
    ("q1", "quat_q1"),
    ("q2", "quat_q2"),
    ("q3", "quat_q3"),
    ("q4", "quat_q4"),
]

HEADER = ["unixtime"] + [name for name, _ in FIELD_MAP]


def extract_row(record):
    gen = record.get("generation")
    params = record.get("parameters") or {}
    if gen is None:
        return None
    row = [int(gen) / 1_000_000]
    for _, key in FIELD_MAP:
        p = params.get(key)
        if not p or p.get("value") is None:
            return None
        row.append(p["value"])
    return row


def main():
    written = 0
    skipped = 0
    with SRC.open("r", encoding="utf-8") as fin, DST.open("w", newline="", encoding="utf-8") as fout:
        writer = csv.writer(fout)
        writer.writerow(HEADER)
        for line in fin:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                skipped += 1
                continue
            row = extract_row(record)
            if row is None:
                skipped += 1
                continue
            writer.writerow(row)
            written += 1
    print(f"wrote {written} rows to {DST.name} ({skipped} skipped)")


if __name__ == "__main__":
    main()
