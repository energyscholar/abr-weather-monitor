"""
noaa_pipeline.py — METAR/ASOS Data Acquisition
ABR Weather Station Monitor — Phase 0

Fetches parsed METAR observations from Iowa Environmental Mesonet (IEM).
No API key required. Returns CSV with station metadata and hourly obs.

Metatron Dynamics, Inc.
"""

import csv
import io
import json
import urllib.request
import urllib.parse
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Optional


# =============================================================
# 1. TYPES
# =============================================================

@dataclass
class StationMeta:
    """Fixed station metadata from IEM network list."""
    station_id: str
    name: str
    lat: float
    lon: float
    elevation_m: float


@dataclass
class Observation:
    """Single METAR observation, parsed to declared components.
    
    Component vector: [temp_C, pressure_hPa, humidity_pct,
                       wind_u_kt, wind_v_kt, dewpoint_c]
    
    Wind direction transformed within M:
      u = -wind_speed * sin(theta)
      v = -wind_speed * cos(theta)
    Declared: preserves speed/direction info, discards circular rep.
    
    Dewpoint replaces precipitation in component vector.
    Precipitation is a threshold event downstream of the relational
    structure between temperature, moisture, and pressure — not a
    continuous relational variable. Dewpoint is continuously varying,
    directly measured (METAR dwpf), and its relational position
    relative to temperature and humidity encodes the thermodynamic
    structure that determines precipitation potential.
    """
    station_id: str
    timestamp: datetime
    temp_c: float
    pressure_hpa: float
    humidity_pct: float
    wind_u_kt: float
    wind_v_kt: float
    dewpoint_c: float


@dataclass
class HourlySnapshot:
    """All valid observations at a single hour.
    
    Stations missing any component are excluded per
    declared missing data protocol (domain_declaration.md).
    """
    timestamp: datetime
    observations: list  # list[Observation]
    station_ids: list   # list[str] — stations present this hour


# =============================================================
# 2. IEM NETWORK METADATA
# =============================================================

IEM_NETWORKS_URL = "https://mesonet.agron.iastate.edu/geojson/network/{network}.geojson"
IEM_ASOS_URL = (
    "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?"
)

# ASOS network codes by state
# California: CA_ASOS
# Can extend to multi-state regions
NETWORK_CODES = {
    "CA": "CA_ASOS",
    "OR": "OR_ASOS",
    "WA": "WA_ASOS",
    "AZ": "AZ_ASOS",
    "NV": "NV_ASOS",
}


def fetch_station_metadata(state: str = "CA") -> list:
    """Fetch station positions from IEM GeoJSON endpoint.
    
    Returns list[StationMeta] for all ASOS stations in the
    declared state network.
    """
    network = NETWORK_CODES.get(state)
    if network is None:
        raise ValueError(f"No network code for state: {state}")

    url = IEM_NETWORKS_URL.format(network=network)
    with urllib.request.urlopen(url) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    stations = []
    for feat in data.get("features", []):
        props = feat.get("properties", {})
        geom = feat.get("geometry", {})
        coords = geom.get("coordinates", [None, None])

        sid = props.get("sid", "")
        name = props.get("sname", "")
        lon = coords[0]
        lat = coords[1]
        elev = props.get("elevation", 0.0)

        if sid and lat is not None and lon is not None:
            stations.append(StationMeta(
                station_id=sid,
                name=name,
                lat=float(lat),
                lon=float(lon),
                elevation_m=float(elev) if elev else 0.0,
            ))

    return stations


# =============================================================
# 3. OBSERVATION FETCH
# =============================================================

def _build_asos_url(
    stations: list,
    start: datetime,
    end: datetime,
) -> str:
    """Build IEM ASOS download URL for declared stations and window.
    
    Requests: tmpf, mslp, relh, sknt, drct, p01i
    (temp °F, sea-level pressure mb, relative humidity %,
     wind speed kt, wind direction deg, 1-hour precip inches)
    """
    params = {
        "station": [s.station_id for s in stations],
        "data": ["tmpf", "mslp", "relh", "sknt", "drct", "dwpf"],
        "tz": "Etc/UTC",
        "format": "onlycomma",
        "latlon": "no",
        "elev": "no",
        "missing": "M",
        "trace": "T",
        "direct": "no",
        "report_type": ["3", "4"],  # ASOS/AWOS routine + special
        "year1": str(start.year),
        "month1": str(start.month),
        "day1": str(start.day),
        "hour1": str(start.hour),
        "minute1": "0",
        "year2": str(end.year),
        "month2": str(end.month),
        "day2": str(end.day),
        "hour2": str(end.hour),
        "minute2": "0",
    }

    # IEM expects repeated 'station' and 'data' params
    parts = []
    for k, v in params.items():
        if isinstance(v, list):
            for item in v:
                parts.append(f"{k}={urllib.parse.quote(str(item))}")
        else:
            parts.append(f"{k}={urllib.parse.quote(str(v))}")

    return IEM_ASOS_URL + "&".join(parts)


import math

def _wind_to_uv(speed_kt: float, direction_deg: float) -> tuple:
    """Transform (speed, direction) to (u, v) within M.
    
    u = -speed * sin(theta)  [east-west, positive = from west]
    v = -speed * cos(theta)  [north-south, positive = from south]
    
    Declared within M. Preserves: speed and direction information.
    Discards: circular angular representation.
    """
    theta = math.radians(direction_deg)
    u = -speed_kt * math.sin(theta)
    v = -speed_kt * math.cos(theta)
    return u, v


def _parse_float(val: str) -> Optional[float]:
    """Parse a string to float, returning None for missing data."""
    if val is None or val.strip() in ("", "M", "T"):
        return None
    try:
        return float(val.strip())
    except (ValueError, TypeError):
        return None


def _f_to_c(temp_f: float) -> float:
    """Fahrenheit to Celsius. Declared unit choice within M."""
    return (temp_f - 32.0) * 5.0 / 9.0


def _inches_to_mm(inches: float) -> float:
    """Inches to millimeters. Declared unit choice within M."""
    return inches * 25.4


def fetch_observations(
    stations: list,
    start: datetime,
    end: datetime,
) -> list:
    """Fetch METAR observations from IEM for declared stations/window.
    
    Returns list[dict] with raw parsed fields before unit conversion.
    """
    url = _build_asos_url(stations, start, end)

    with urllib.request.urlopen(url) as resp:
        raw = resp.read().decode("utf-8")

    reader = csv.DictReader(io.StringIO(raw))
    rows = []
    for row in reader:
        rows.append(row)

    return rows


def rows_to_observations(rows: list) -> list:
    """Convert raw IEM CSV rows to Observation objects.
    
    Applies declared unit conversions within M:
      temp: °F → °C
      pressure: mbar (= hPa, no conversion needed)
      humidity: % (no conversion)
      wind: (speed_kt, dir_deg) → (u_kt, v_kt)
      precip: inches → mm
    
    Rows with ANY missing component are excluded per
    declared missing data protocol.
    """
    observations = []

    for row in rows:
        # Parse timestamp
        ts_str = row.get("valid", "").strip()
        if not ts_str:
            continue
        try:
            ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M")
        except ValueError:
            continue

        sid = row.get("station", "").strip()
        if not sid:
            continue

        # Parse all components — any None means exclude
        tmpf = _parse_float(row.get("tmpf"))
        mslp = _parse_float(row.get("mslp"))
        relh = _parse_float(row.get("relh"))
        sknt = _parse_float(row.get("sknt"))
        drct = _parse_float(row.get("drct"))
        dwpf = _parse_float(row.get("dwpf"))

        # Missing data protocol: exclude if any component absent
        if any(v is None for v in [tmpf, mslp, relh, sknt, drct, dwpf]):
            continue

        # Physical sanity bounds
        if not (-80 <= tmpf <= 140):
            continue
        if not (900 <= mslp <= 1100):
            continue
        if not (0 <= relh <= 100):
            continue
        if sknt < 0 or sknt > 200:
            continue
        if not (0 <= drct <= 360):
            continue
        if not (-80 <= dwpf <= 140):
            continue

        # Unit conversions (declared within M)
        temp_c = _f_to_c(tmpf)
        pressure_hpa = mslp  # mbar == hPa
        humidity_pct = relh
        wind_u, wind_v = _wind_to_uv(sknt, drct)
        dewpoint_c = _f_to_c(dwpf)

        observations.append(Observation(
            station_id=sid,
            timestamp=ts,
            temp_c=temp_c,
            pressure_hpa=pressure_hpa,
            humidity_pct=humidity_pct,
            wind_u_kt=wind_u,
            wind_v_kt=wind_v,
            dewpoint_c=dewpoint_c,
        ))

    return observations


# =============================================================
# 4. HOURLY BINNING
# =============================================================

def bin_to_hourly(observations: list) -> list:
    """Bin observations to hourly snapshots.
    
    For each station-hour, takes the observation closest to
    the top of the hour (minute 53-56 for standard METAR).
    
    If a station has multiple obs in an hour, the one closest
    to :00 is retained. This is a declared choice within M.
    Preserved: closest-to-hour observation.
    Discarded: sub-hourly variation within the hour.
    """
    from collections import defaultdict

    # Group by (station, hour)
    hourly = defaultdict(list)
    for obs in observations:
        hour_key = obs.timestamp.replace(minute=0, second=0, microsecond=0)
        hourly[(obs.station_id, hour_key)].append(obs)

    # For each group, pick closest to top of hour
    best = {}
    for (sid, hour), obs_list in hourly.items():
        closest = min(obs_list, key=lambda o: abs(o.timestamp.minute))
        # Re-stamp to the hour for alignment
        closest_aligned = Observation(
            station_id=closest.station_id,
            timestamp=hour,
            temp_c=closest.temp_c,
            pressure_hpa=closest.pressure_hpa,
            humidity_pct=closest.humidity_pct,
            wind_u_kt=closest.wind_u_kt,
            wind_v_kt=closest.wind_v_kt,
            dewpoint_c=closest.dewpoint_c,
        )
        best[(sid, hour)] = closest_aligned

    # Group by hour → HourlySnapshot
    hour_groups = defaultdict(list)
    for (sid, hour), obs in best.items():
        hour_groups[hour].append(obs)

    snapshots = []
    for hour in sorted(hour_groups.keys()):
        obs_list = hour_groups[hour]
        sids = sorted([o.station_id for o in obs_list])
        snapshots.append(HourlySnapshot(
            timestamp=hour,
            observations=sorted(obs_list, key=lambda o: o.station_id),
            station_ids=sids,
        ))

    return snapshots


# =============================================================
# 5. PIPELINE ENTRY POINT
# =============================================================

def run_pipeline(
    state: str = "CA",
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    bbox: Optional[tuple] = None,
) -> tuple:
    """Full Phase 0 data pipeline.
    
    Args:
        state: State code for ASOS network
        start: UTC start time (default: 72 hours ago)
        end: UTC end time (default: now)
        bbox: Optional (min_lat, max_lat, min_lon, max_lon)
              to filter stations to a geographic region.
    
    Returns:
        (stations, snapshots) where:
          stations: list[StationMeta] — all stations in region
          snapshots: list[HourlySnapshot] — hourly binned obs
    """
    if end is None:
        end = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
    if start is None:
        start = end - timedelta(hours=72)

    print(f"Fetching station metadata for {state}...")
    stations = fetch_station_metadata(state)
    print(f"  Found {len(stations)} stations in {state}_ASOS")

    # Geographic filter if bbox declared
    if bbox is not None:
        min_lat, max_lat, min_lon, max_lon = bbox
        stations = [
            s for s in stations
            if min_lat <= s.lat <= max_lat
            and min_lon <= s.lon <= max_lon
        ]
        print(f"  After bbox filter: {len(stations)} stations")

    if len(stations) == 0:
        raise ValueError("No stations in declared region")

    print(f"Fetching observations {start} to {end} UTC...")
    raw_rows = fetch_observations(stations, start, end)
    print(f"  Received {len(raw_rows)} raw rows")

    print("Parsing and applying M (unit conversions, wind decomposition)...")
    obs = rows_to_observations(raw_rows)
    print(f"  {len(obs)} valid observations after missing data exclusion")

    print("Binning to hourly snapshots...")
    snapshots = bin_to_hourly(obs)
    print(f"  {len(snapshots)} hourly snapshots")

    if snapshots:
        counts = [len(s.station_ids) for s in snapshots]
        print(f"  Stations per hour: min={min(counts)}, "
              f"max={max(counts)}, mean={sum(counts)/len(counts):.1f}")

    return stations, snapshots


# =============================================================
# 6. DIAGNOSTIC OUTPUT
# =============================================================

def print_snapshot_summary(snapshots: list, n: int = 5):
    """Print first n snapshots for verification."""
    for snap in snapshots[:n]:
        print(f"\n{snap.timestamp} UTC — {len(snap.observations)} stations")
        for obs in snap.observations[:3]:
            print(f"  {obs.station_id}: "
                  f"T={obs.temp_c:.1f}°C "
                  f"P={obs.pressure_hpa:.1f}hPa "
                  f"RH={obs.humidity_pct:.0f}% "
                  f"u={obs.wind_u_kt:.1f}kt "
                  f"v={obs.wind_v_kt:.1f}kt "
                  f"Td={obs.dewpoint_c:.1f}°C")
        if len(snap.observations) > 3:
            print(f"  ... and {len(snap.observations) - 3} more")


if __name__ == "__main__":
    # Default: California Central Coast / SoCal region
    # bbox: roughly Santa Barbara to San Diego, inland to desert edge
    stations, snapshots = run_pipeline(
        state="CA",
        bbox=(33.5, 36.0, -121.0, -117.0),
    )
    print_snapshot_summary(snapshots)
