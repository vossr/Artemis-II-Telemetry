"""
Artemis II Live Telemetry Scraper
Mirrors the exact fetch pattern used by nasa.gov/AROW:
  1. GET metadata  → extract current generation number
  2. GET ?alt=media&generation=<N>  → fetch that exact pinned version

Update cadence: ~60s (derived from observed generation timestamps).
Writes new frames to telemetry_recording.json (NDJSON).
Never shuts down — retries all errors indefinitely.
"""

import json
import hashlib
import math
import time
import datetime
import os
import sys
import requests

# ── Config ────────────────────────────────────────────────────────────────────

BUCKET        = "p-2-cen1"
BASE_URL      = f"https://storage.googleapis.com/storage/v1/b/{BUCKET}/o"
POLL_INTERVAL = 60.0        # seconds — confirmed from generation timestamp diff
OUTPUT_FILE   = "telemetry_recording.json"
EARTH_RADIUS_M = 6_371_000.0

CREW_FILES = {
    "October": ("October", "1", 105),
    "Io":      ("Io",      "2", 108),
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:149.0) Gecko/20100101 Firefox/149.0",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-GPC": "1",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "cross-site",
    "Referer": "https://www.nasa.gov/",
}

PARAM_INFO = {
    "2003": ("pos_x_m",    "m"),
    "2004": ("pos_y_m",    "m"),
    "2005": ("pos_z_m",    "m"),
    "2009": ("vel_x_ms",   "m/s"),
    "2010": ("vel_y_ms",   "m/s"),
    "2011": ("vel_z_ms",   "m/s"),
    "2012": ("quat_q1",    ""),
    "2013": ("quat_q2",    ""),
    "2014": ("quat_q3",    ""),
    "2015": ("quat_q4",    ""),
    "2016": ("mode_flags", "hex"),
    "2026": ("altitude",   "?"),
    "2040": ("status_2040","flag"),
    "2041": ("status_2041","flag"),
    "2042": ("status_2042","flag"),
}

# ── URL builders ──────────────────────────────────────────────────────────────

def obj_name(folder, slot, num):
    return f"{folder}/{slot}/{folder}_{num}_{slot}.txt"

def meta_url(folder, slot, num):
    return f"{BASE_URL}/{requests.utils.quote(obj_name(folder, slot, num), safe='')}"

def pinned_url(folder, slot, num, generation):
    """Exact pattern the website uses: ?alt=media&generation=<N>"""
    enc = requests.utils.quote(obj_name(folder, slot, num), safe="")
    return f"{BASE_URL}/{enc}?alt=media&generation={generation}"

def unpinned_url(folder, slot, num):
    enc = requests.utils.quote(obj_name(folder, slot, num), safe="")
    return f"{BASE_URL}/{enc}?alt=media"

# ── Parsing ───────────────────────────────────────────────────────────────────

def parse_frame(raw, crew, file_num, generation, received_at):
    file_hdr = raw.get("File", {})
    params   = {}
    for key, val in raw.items():
        if not key.startswith("Parameter_"):
            continue
        num = val.get("Number", "")
        if num not in PARAM_INFO:
            continue
        field, unit = PARAM_INFO[num]
        raw_val = val.get("Value", "")
        try:
            parsed = float(raw_val) if val.get("Type") == "2" else raw_val
        except (ValueError, TypeError):
            parsed = raw_val
        params[field] = {
            "value":  parsed,
            "unit":   unit,
            "status": val.get("Status", "unknown"),
            "time":   val.get("Time", ""),
        }

    derived = {}
    try:
        x, y, z = params["pos_x_m"]["value"], params["pos_y_m"]["value"], params["pos_z_m"]["value"]
        dist_m = math.sqrt(x*x + y*y + z*z)
        derived["distance_from_earth_km"] = round(dist_m / 1000.0, 3)
        derived["altitude_km"]            = round((dist_m - EARTH_RADIUS_M) / 1000.0, 3)
    except (KeyError, TypeError):
        pass
    try:
        vx, vy, vz = params["vel_x_ms"]["value"], params["vel_y_ms"]["value"], params["vel_z_ms"]["value"]
        spd = math.sqrt(vx*vx + vy*vy + vz*vz)
        derived["speed_ms"]  = round(spd, 4)
        derived["speed_kmh"] = round(spd * 3.6, 2)
    except (KeyError, TypeError):
        pass

    return {
        "received_at":  received_at,
        "crew":         crew,
        "file_num":     file_num,
        "generation":   generation,
        "mission_date": file_hdr.get("Date", ""),
        "activity":     file_hdr.get("Activity", ""),
        "type":         file_hdr.get("Type", ""),
        "parameters":   params,
        "derived":      derived,
    }

# ── I/O ───────────────────────────────────────────────────────────────────────

def append_frame(frame):
    with open(OUTPUT_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(frame) + "\n")

def log(msg):
    ts = datetime.datetime.utcnow().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{ts}] {msg}", flush=True)

def print_frame(frame):
    d   = frame["derived"]
    p   = frame["parameters"]
    act = frame["activity"]
    tag = "MISSION" if act == "MIS" else f"SIM" if act == "SIM" else act

    log(f"{'─'*60}")
    log(f"RECEIVED  [{tag}]  crew={frame['crew']}  "
        f"file=#{frame['file_num']}  gen={frame['generation']}")
    log(f"  mission_date : {frame['mission_date']}  type={frame['type']}")

    if "distance_from_earth_km" in d:
        log(f"  dist_earth   : {d['distance_from_earth_km']:>14,.3f} km")
    if "altitude_km" in d:
        log(f"  altitude     : {d['altitude_km']:>14,.3f} km")
    if "speed_ms" in d:
        log(f"  speed        : {d['speed_ms']:>14,.2f} m/s  ({d['speed_kmh']:,.1f} km/h)")

    log("")
    for field, info in p.items():
        ok  = "OK " if info["status"] == "Good" else "!! "
        val = info["value"]
        unt = info["unit"]
        if isinstance(val, float):
            log(f"  {ok} {field:<22} {val:>20.8f}  {unt}")
        else:
            log(f"  {ok} {field:<22} {str(val):>20}  {unt}")

# ── Per-crew poller ───────────────────────────────────────────────────────────

class CrewPoller:
    def __init__(self, name, folder, slot, file_num):
        self.name          = name
        self.folder        = folder
        self.slot          = slot
        self.file_num      = file_num
        self.last_gen      = None   # last seen generation number
        self.session       = requests.Session()
        self.session.headers.update(HEADERS)
        self._backoff      = 0

    # ── resilient GET ────────────────────────────────────────────────────────

    def _get(self, url, timeout=10):
        """GET with exponential backoff. Never raises — returns None on failure."""
        delay = min(2 ** self._backoff, 120)
        try:
            r = self.session.get(url, timeout=timeout)
            self._backoff = 0
            return r
        except requests.exceptions.ConnectionError as e:
            log(f"[{self.name}] connection error (backoff {delay}s): {e}")
        except requests.exceptions.Timeout:
            log(f"[{self.name}] timeout (backoff {delay}s)")
        except requests.exceptions.RequestException as e:
            log(f"[{self.name}] request error (backoff {delay}s): {e}")
        self._backoff += 1
        time.sleep(delay)
        return None

    # ── file rollover check ──────────────────────────────────────────────────

    def _try_advance(self):
        """Check if the next file number exists; advance if so."""
        r = self._get(meta_url(self.folder, self.slot, self.file_num + 1))
        if r is not None and r.status_code == 200:
            self.file_num += 1
            self.last_gen  = None
            log(f"[{self.name}] file rolled over → #{self.file_num}")
            return True
        return False

    # ── main poll ────────────────────────────────────────────────────────────

    def poll(self):
        """
        Step 1: fetch metadata → get current generation.
        Step 2: if generation changed, fetch pinned content URL.
        Returns True if a new frame was written.
        """

        # ── Step 1: metadata ─────────────────────────────────────────────────
        r_meta = self._get(meta_url(self.folder, self.slot, self.file_num))
        if r_meta is None:
            return False

        if r_meta.status_code == 404:
            self._try_advance()
            return False

        if r_meta.status_code != 200:
            log(f"[{self.name}] metadata status {r_meta.status_code}")
            return False

        try:
            meta = r_meta.json()
        except json.JSONDecodeError as e:
            log(f"[{self.name}] metadata JSON error: {e}")
            return False

        generation = meta.get("generation")
        if generation is None:
            log(f"[{self.name}] no generation in metadata")
            return False

        # ── Step 2: check if new ─────────────────────────────────────────────
        if generation == self.last_gen:
            return False   # same generation — no new data

        self.last_gen = generation

        # ── Step 3: fetch pinned content URL (exactly like the website) ──────
        r_content = self._get(
            pinned_url(self.folder, self.slot, self.file_num, generation)
        )
        if r_content is None:
            return False

        if r_content.status_code != 200:
            # Fall back to unpinned if pinned 404s (edge case: file just rolled)
            log(f"[{self.name}] pinned fetch status {r_content.status_code}, trying unpinned")
            r_content = self._get(unpinned_url(self.folder, self.slot, self.file_num))
            if r_content is None or r_content.status_code != 200:
                return False

        try:
            raw = json.loads(r_content.content)
        except json.JSONDecodeError as e:
            log(f"[{self.name}] content JSON error: {e}")
            return False

        received_at = datetime.datetime.utcnow().isoformat() + "Z"

        try:
            frame = parse_frame(raw, self.name, self.file_num, generation, received_at)
        except Exception as e:
            log(f"[{self.name}] parse error: {e!r}")
            return False

        try:
            append_frame(frame)
        except OSError as e:
            log(f"[{self.name}] disk write error: {e}")

        print_frame(frame)

        # Check for next file after each successful frame
        self._try_advance()
        return True


# ── Main loop ─────────────────────────────────────────────────────────────────

def main():
    log("=" * 60)
    log("  Artemis II Telemetry Scraper")
    log(f"  Cadence: {POLL_INTERVAL}s  |  Output: {OUTPUT_FILE}")
    log(f"  Pattern: metadata → pinned generation fetch (mirrors AROW)")
    log("=" * 60)

    if not os.path.exists(OUTPUT_FILE):
        open(OUTPUT_FILE, "w").close()
        log(f"Created {OUTPUT_FILE}")
    else:
        with open(OUTPUT_FILE) as f:
            n = sum(1 for l in f if l.strip())
        log(f"Appending to {OUTPUT_FILE}  ({n} frames already recorded)")

    pollers = [
        CrewPoller(name, folder, slot, num)
        for name, (folder, slot, num) in CREW_FILES.items()
    ]

    frame_count = 0

    while True:
        tick_start = time.monotonic()

        for poller in pollers:
            try:
                if poller.poll():
                    frame_count += 1
                    log(f"  → {OUTPUT_FILE}  (total: {frame_count} frames)")
            except Exception as e:
                log(f"[{poller.name}] UNHANDLED: {e!r} — continuing")

        elapsed   = time.monotonic() - tick_start
        sleep_for = max(0.0, POLL_INTERVAL - elapsed)

        next_ts = (datetime.datetime.utcnow() +
                   datetime.timedelta(seconds=sleep_for)).strftime("%H:%M:%S")
        log(f"Next poll at {next_ts}  (sleeping {sleep_for:.1f}s)")
        time.sleep(sleep_for)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("Stopped.")
        sys.exit(0)
