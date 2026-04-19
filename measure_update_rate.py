"""
Artemis II Telemetry — Update Rate Measurement
Hammers the content endpoint as fast as possible and records
the exact wall-clock time of every hash change to determine
NASA's true push cadence.
"""

import json
import hashlib
import time
import statistics
import requests

BUCKET   = "p-2-cen1"
BASE_URL = f"https://storage.googleapis.com/storage/v1/b/{BUCKET}/o"

CREW_FILES = {
    "Io":      ("Io",      "2", 108),
    "October": ("October", "1", 105),
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:149.0) Gecko/20100101 Firefox/149.0",
    "Accept": "*/*",
    "Referer": "https://www.nasa.gov/",
}

MEASURE_SECONDS = 120    # how long to run the measurement
TARGET_NAME     = "October"   # crew member to measure (most data)


def content_url(folder, slot, file_num):
    name = f"{folder}/{slot}/{folder}_{file_num}_{slot}.txt"
    enc  = requests.utils.quote(name, safe="")
    return f"{BASE_URL}/{enc}?alt=media"


def next_file_url(folder, slot, file_num):
    name = f"{folder}/{slot}/{folder}_{file_num + 1}_{slot}.txt"
    enc  = requests.utils.quote(name, safe="")
    return f"{BASE_URL}/{enc}"


def measure(name, folder, slot, file_num):
    session = requests.Session()
    session.headers.update(HEADERS)

    url = content_url(folder, slot, file_num)

    last_hash     = None
    last_change_t = None
    change_times  = []      # wall-clock times of each change
    intervals     = []      # seconds between changes
    request_count = 0
    error_count   = 0

    t_start = time.monotonic()
    t_end   = t_start + MEASURE_SECONDS

    print(f"\nMeasuring '{name}' for {MEASURE_SECONDS}s — hammering as fast as possible…")
    print(f"URL: {url}\n")

    while time.monotonic() < t_end:
        time.sleep(1.0)
        t_req = time.monotonic()
        try:
            r = session.get(url, timeout=5)
            request_count += 1
        except Exception as e:
            error_count += 1
            print(f"  [err] {e}")
            continue

        if r.status_code != 200:
            # Check for file rollover
            chk = session.get(next_file_url(folder, slot, file_num), timeout=5)
            if chk.status_code == 200:
                file_num += 1
                url = content_url(folder, slot, file_num)
                print(f"  [info] rolled to file #{file_num}")
            else:
                error_count += 1
            continue

        digest = hashlib.md5(r.content).hexdigest()
        now    = time.time()   # wall clock for reporting

        if digest != last_hash:
            if last_hash is not None:   # skip the very first
                dt = now - last_change_t
                intervals.append(dt)
                change_times.append(now)

                elapsed = time.monotonic() - t_start
                print(f"  [{elapsed:6.2f}s] NEW DATA  interval={dt:.4f}s  "
                      f"({1/dt:.2f} Hz)  "
                      f"req_since_last={request_count - (len(intervals))}")

            last_hash     = digest
            last_change_t = now

        # No sleep — hammer as fast as possible to get tight timing

    # ── Summary ──────────────────────────────────────────────────────────────
    elapsed_total = time.monotonic() - t_start
    print(f"\n{'='*60}")
    print(f"  Results for '{name}'  ({elapsed_total:.1f}s measured)")
    print(f"{'='*60}")
    print(f"  Total requests     : {request_count}")
    print(f"  Errors             : {error_count}")
    print(f"  Data changes seen  : {len(intervals)}")

    if not intervals:
        print("  No changes detected — data may be static or file rolled over.")
        return

    print(f"\n  Update interval stats (seconds):")
    print(f"    Min      : {min(intervals):.4f}s  ({1/min(intervals):.2f} Hz)")
    print(f"    Max      : {max(intervals):.4f}s  ({1/max(intervals):.2f} Hz)")
    print(f"    Mean     : {statistics.mean(intervals):.4f}s  "
          f"({1/statistics.mean(intervals):.2f} Hz)")
    print(f"    Median   : {statistics.median(intervals):.4f}s  "
          f"({1/statistics.median(intervals):.2f} Hz)")
    if len(intervals) > 1:
        print(f"    Std dev  : {statistics.stdev(intervals):.4f}s")

    print(f"\n  Effective request rate : {request_count/elapsed_total:.1f} req/s")
    print(f"  Effective update rate  : {len(intervals)/elapsed_total:.3f} Hz")

    # Histogram of intervals
    buckets = {}
    for iv in intervals:
        bucket = round(iv * 2) / 2   # round to nearest 0.5s
        buckets[bucket] = buckets.get(bucket, 0) + 1
    print(f"\n  Interval histogram (rounded to 0.5s):")
    for k in sorted(buckets):
        bar = "█" * buckets[k]
        print(f"    {k:5.1f}s  {bar}  ({buckets[k]})")


if __name__ == "__main__":
    folder, slot, file_num = CREW_FILES[TARGET_NAME]
    measure(TARGET_NAME, folder, slot, file_num)
