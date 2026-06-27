"""
generate.py — Dashboard Generator for ABR Weather Monitor
ABR Weather Station Monitor — Plan 0412, Phase 3

Reads data/predictions.jsonl and data/calibration_report.json,
generates a self-contained docs/index.html with inline CSS and SVG charts.

Usage: python -m src.dashboard.generate

Metatron Dynamics, Inc.
"""

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Paths relative to repo root
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PREDICTIONS_PATH = REPO_ROOT / "data" / "predictions.jsonl"
CALIBRATION_PATH = REPO_ROOT / "data" / "calibration_report.json"
OUTPUT_PATH = REPO_ROOT / "docs" / "index.html"


def load_predictions() -> list:
    """Load all records from predictions.jsonl."""
    records = []
    if not PREDICTIONS_PATH.exists():
        return records
    with open(PREDICTIONS_PATH) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def load_calibration() -> dict:
    """Load calibration report."""
    if not CALIBRATION_PATH.exists():
        return {}
    with open(CALIBRATION_PATH) as f:
        return json.load(f)


def parse_records(records: list) -> tuple:
    """Separate records by type."""
    observations = [r for r in records if r.get("type") == "obs"]
    predictions = [r for r in records if r.get("type") == "pred"]
    verifications = [r for r in records if r.get("type") == "verify"]
    return observations, predictions, verifications


def determine_status(observations: list, calibration: dict) -> str:
    """Determine system status: active, calibrating, or data_gap."""
    if not observations:
        return "data_gap"

    # Check if in calibration period
    cal_end_str = calibration.get("gate", "")
    if cal_end_str == "BORDERLINE":
        return "calibrating"

    # Check data freshness
    last_obs = observations[-1]
    try:
        last_time = datetime.strptime(last_obs["data_time"], "%Y-%m-%dT%H:%M:%SZ")
        age_hours = (datetime.utcnow() - last_time).total_seconds() / 3600
        if age_hours > 6:
            return "data_gap"
    except (ValueError, KeyError):
        pass

    return "active"


def format_time_ago(iso_str: str) -> str:
    """Format an ISO timestamp as 'Xh Ym ago'."""
    try:
        t = datetime.strptime(iso_str, "%Y-%m-%dT%H:%M:%SZ")
        delta = datetime.utcnow() - t
        total_minutes = int(delta.total_seconds() / 60)
        if total_minutes < 1:
            return "just now"
        if total_minutes < 60:
            return f"{total_minutes}m ago"
        hours = total_minutes // 60
        minutes = total_minutes % 60
        if hours < 24:
            if minutes > 0:
                return f"{hours}h {minutes}m ago"
            return f"{hours}h ago"
        days = hours / 24
        return f"{days:.1f}d ago"
    except (ValueError, KeyError):
        return "unknown"


def escape_html(text: str) -> str:
    """Escape HTML special characters."""
    return (text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))


def format_dg_raw(value: float) -> str:
    """Format raw DeltaGamma for display.

    Raw values can range from tens to tens of thousands.
    Use scientific notation for large values.
    """
    if abs(value) < 0.01:
        return "0"
    if abs(value) >= 10000:
        return f"{value:.2e}"
    if abs(value) >= 100:
        return f"{value:+,.0f}"
    return f"{value:+.1f}"


def compute_run_days(observations: list) -> int:
    """Compute number of days the system has been running."""
    if not observations:
        return 0
    try:
        first = datetime.strptime(observations[0]["data_time"],
                                  "%Y-%m-%dT%H:%M:%SZ")
        last = datetime.strptime(observations[-1]["data_time"],
                                 "%Y-%m-%dT%H:%M:%SZ")
        return max(1, int((last - first).total_seconds() / 86400))
    except (ValueError, KeyError):
        return 0


def build_sparkline_svg(observations: list, predictions: list) -> str:
    """Build an inline SVG sparkline of DeltaGamma over last 48 hours.

    Shows normalized DeltaGamma values, threshold line, and prediction dots.
    Includes axis labels and threshold annotation.
    """
    if not observations:
        return (
            '<svg width="100%" height="160" viewBox="0 0 700 160" '
            'role="img" '
            'aria-label="No observation data available yet. The chart will '
            'populate as the system collects hourly weather station readings.">'
            '<rect x="0" y="0" width="700" height="160" fill="#fafafa" rx="4"/>'
            '<text x="350" y="85" text-anchor="middle" fill="#888" '
            'font-size="14" font-family="-apple-system, BlinkMacSystemFont, '
            'sans-serif">Awaiting data</text></svg>'
        )

    # Filter to last 48 observations (hours)
    recent = observations[-48:]
    dg_values = []
    timestamps = []
    thresholds = []

    for obs in recent:
        dg = obs.get("dg_norm", 0.0)
        dg_values.append(dg)
        timestamps.append(obs.get("data_time", ""))
        thresholds.append(obs.get("threshold_norm", 0.0))

    n = len(dg_values)
    if n == 0:
        return (
            '<svg width="100%" height="160" viewBox="0 0 700 160" '
            'role="img" aria-label="Empty chart - no data points available">'
            '<rect x="0" y="0" width="700" height="160" fill="#fafafa" rx="4"/>'
            '<text x="350" y="85" text-anchor="middle" fill="#888" '
            'font-size="14" font-family="-apple-system, BlinkMacSystemFont, '
            'sans-serif">No data</text></svg>'
        )

    # SVG dimensions
    w, h = 700, 160
    margin_left = 60
    margin_right = 15
    margin_top = 15
    margin_bottom = 30
    plot_w = w - margin_left - margin_right
    plot_h = h - margin_top - margin_bottom

    # Compute Y scale
    all_vals = dg_values + [t for t in thresholds if t > 0]
    min_val = min(all_vals) if all_vals else 0
    max_val = max(all_vals) if all_vals else 1
    val_range = max_val - min_val
    if val_range < 1e-10:
        val_range = max(abs(max_val), 0.01)
        min_val = min_val - val_range * 0.1
        max_val = max_val + val_range * 0.1
        val_range = max_val - min_val

    # Add 10% padding
    min_val -= val_range * 0.1
    max_val += val_range * 0.1
    val_range = max_val - min_val

    def x_pos(i):
        return margin_left + (i / max(n - 1, 1)) * plot_w

    def y_pos(v):
        return margin_top + plot_h - ((v - min_val) / val_range) * plot_h

    # Build polyline path for DeltaGamma
    points = " ".join(
        f"{x_pos(i):.1f},{y_pos(v):.1f}" for i, v in enumerate(dg_values)
    )

    # Threshold line (use max non-zero threshold if any)
    threshold_val = max((t for t in thresholds if t > 0), default=0)

    # Prediction dots: find which observation timestamps have predictions
    pred_times = set()
    for p in predictions:
        pred_times.add(p.get("data_time", ""))

    pred_dots = []
    for i, ts in enumerate(timestamps):
        if ts in pred_times:
            pred_dots.append((x_pos(i), y_pos(dg_values[i])))

    # Zero line y position
    zero_y = y_pos(0)

    # Time labels
    first_ts = timestamps[0] if timestamps else ""
    last_ts = timestamps[-1] if timestamps else ""
    first_label = first_ts[11:16] if len(first_ts) > 15 else ""
    last_label = last_ts[11:16] if len(last_ts) > 15 else ""
    first_date = first_ts[:10] if len(first_ts) > 9 else ""
    last_date = last_ts[:10] if len(last_ts) > 9 else ""
    if first_date and first_date != last_date:
        first_label = (
            first_ts[5:16].replace("T", " ") if len(first_ts) > 15 else ""
        )
        last_label = (
            last_ts[5:16].replace("T", " ") if len(last_ts) > 15 else ""
        )

    # Y axis tick values
    y_ticks = []
    tick_count = 4
    for i in range(tick_count + 1):
        v = min_val + (val_range * i / tick_count)
        y_ticks.append(v)

    # Build descriptive aria-label
    aria_parts = [
        f"Line chart showing how fast the relationship pattern is changing, "
        f"measured hourly over the last {n} hours.",
        f"Values range from {min(dg_values):.4f} to {max(dg_values):.4f}.",
    ]
    if threshold_val > 0:
        aria_parts.append(
            f"The prediction threshold is at {threshold_val:.4f}. "
            f"When the line crosses this threshold, a prediction is emitted."
        )
    if pred_dots:
        aria_parts.append(
            f"{len(pred_dots)} prediction(s) were emitted during this period."
        )
    else:
        aria_parts.append("No predictions were emitted during this period.")
    aria_label = " ".join(aria_parts)

    svg_parts = [
        f'<svg width="100%" height="160" viewBox="0 0 {w} {h}" '
        f'preserveAspectRatio="xMidYMid meet" '
        f'role="img" aria-label="{escape_html(aria_label)}">',
        f'<rect x="0" y="0" width="{w}" height="{h}" fill="#fafafa" rx="4"/>',
    ]

    # Y axis ticks and grid lines
    for v in y_ticks:
        y = y_pos(v)
        svg_parts.append(
            f'<line x1="{margin_left}" y1="{y:.1f}" '
            f'x2="{w - margin_right}" y2="{y:.1f}" '
            f'stroke="#eee" stroke-width="1"/>'
        )
        svg_parts.append(
            f'<text x="{margin_left - 8}" y="{y + 3:.1f}" '
            f'text-anchor="end" fill="#999" '
            f'font-size="10" font-family="-apple-system, BlinkMacSystemFont, '
            f'sans-serif">{v:.3f}</text>'
        )

    # Zero line
    if min_val < 0 < max_val:
        svg_parts.append(
            f'<line x1="{margin_left}" y1="{zero_y:.1f}" '
            f'x2="{w - margin_right}" y2="{zero_y:.1f}" '
            f'stroke="#ccc" stroke-width="1" stroke-dasharray="4,4"/>'
        )

    # X axis labels
    if first_label:
        svg_parts.append(
            f'<text x="{margin_left}" y="{h - 5}" '
            f'text-anchor="start" fill="#999" font-size="10" '
            f'font-family="-apple-system, BlinkMacSystemFont, sans-serif">'
            f'{escape_html(first_label)} UTC</text>'
        )
    if last_label:
        svg_parts.append(
            f'<text x="{w - margin_right}" y="{h - 5}" '
            f'text-anchor="end" fill="#999" font-size="10" '
            f'font-family="-apple-system, BlinkMacSystemFont, sans-serif">'
            f'{escape_html(last_label)} UTC</text>'
        )
    if n > 2:
        mid_idx = n // 2
        mid_ts = timestamps[mid_idx] if mid_idx < len(timestamps) else ""
        mid_label = mid_ts[11:16] if len(mid_ts) > 15 else ""
        if mid_label:
            svg_parts.append(
                f'<text x="{x_pos(mid_idx):.1f}" y="{h - 5}" '
                f'text-anchor="middle" fill="#999" font-size="10" '
                f'font-family="-apple-system, BlinkMacSystemFont, '
                f'sans-serif">{escape_html(mid_label)}</text>'
            )

    # Y axis title
    svg_parts.append(
        f'<text x="12" y="{margin_top + plot_h / 2}" '
        f'text-anchor="middle" fill="#999" font-size="10" '
        f'font-family="-apple-system, BlinkMacSystemFont, sans-serif" '
        f'transform="rotate(-90, 12, {margin_top + plot_h / 2})">'
        f'Change index</text>'
    )

    # Threshold line with label
    if threshold_val > 0:
        ty = y_pos(threshold_val)
        svg_parts.append(
            f'<line x1="{margin_left}" y1="{ty:.1f}" '
            f'x2="{w - margin_right}" y2="{ty:.1f}" '
            f'stroke="#e74c3c" stroke-width="1.5" '
            f'stroke-dasharray="6,3"/>'
        )
        svg_parts.append(
            f'<text x="{w - margin_right - 4}" y="{ty - 5:.1f}" '
            f'text-anchor="end" fill="#e74c3c" font-size="10" '
            f'font-weight="600" '
            f'font-family="-apple-system, BlinkMacSystemFont, sans-serif">'
            f'Prediction threshold</text>'
        )

    # DeltaGamma line
    svg_parts.append(
        f'<polyline points="{points}" fill="none" stroke="#2980b9" '
        f'stroke-width="2" stroke-linejoin="round"/>'
    )

    # Prediction dots
    for px, py in pred_dots:
        svg_parts.append(
            f'<circle cx="{px:.1f}" cy="{py:.1f}" r="5" '
            f'fill="#e67e22" stroke="#d35400" stroke-width="1.5"/>'
        )

    svg_parts.append("</svg>")
    return "\n".join(svg_parts)


def build_lead_time_histogram(verifications: list) -> str:
    """Build a small SVG histogram of lead times for verified hits."""
    hits = [v for v in verifications if v.get("status") == "hit"]
    if not hits:
        return ""

    lead_times = [v.get("lead_hours", 0.0) for v in hits]
    if not lead_times:
        return ""

    # Bin into 1-hour buckets
    max_lead = max(lead_times)
    n_bins = max(int(max_lead) + 1, 1)
    n_bins = min(n_bins, 12)  # cap at 12 bins
    bin_width = (max_lead + 0.01) / n_bins

    bins = [0] * n_bins
    for lt in lead_times:
        b = min(int(lt / bin_width), n_bins - 1)
        bins[b] += 1

    max_count = max(bins) if bins else 1

    w, h = 200, 60
    pad = 5
    bar_w = (w - 2 * pad) / n_bins

    svg_parts = [
        f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
        f'role="img" '
        f'aria-label="Histogram showing how far in advance the system '
        f'detected weather changes. {len(lead_times)} verified predictions '
        f'had lead times from {min(lead_times):.1f} to '
        f'{max(lead_times):.1f} hours.">',
        f'<rect x="0" y="0" width="{w}" height="{h}" fill="#fafafa" rx="3"/>',
    ]

    for i, count in enumerate(bins):
        bar_h = (count / max(max_count, 1)) * (h - 2 * pad - 12)
        bx = pad + i * bar_w + 1
        by = h - pad - bar_h
        svg_parts.append(
            f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bar_w - 2:.1f}" '
            f'height="{bar_h:.1f}" fill="#2980b9" rx="1"/>'
        )

    svg_parts.append(
        f'<text x="{w / 2}" y="{h - 1}" text-anchor="middle" '
        f'font-size="9" fill="#666" '
        f'font-family="-apple-system, BlinkMacSystemFont, sans-serif">'
        f'Hours of advance warning</text>'
    )

    svg_parts.append("</svg>")
    return "\n".join(svg_parts)


def build_lead_time_timeline_svg(pred: dict, verif: dict) -> str:
    """Build an inline SVG timeline for a single verified hit.

    Shows a horizontal bar from detection time to scalar peak time
    with the lead time labeled. Makes the "early warning" claim
    visually concrete.
    """
    lead_hours = verif.get("lead_hours", 0.0)
    if lead_hours <= 0:
        return ""

    pred_time = pred.get("data_time", "")[:16]
    # The verification time is approximately detection + lead_hours
    verif_time = verif.get("scalar_peak_time", "")[:16]
    if not verif_time:
        # Estimate from detection time + lead hours
        try:
            dt = datetime.strptime(pred.get("data_time", ""),
                                   "%Y-%m-%dT%H:%M:%SZ")
            peak = dt + timedelta(hours=lead_hours)
            verif_time = peak.strftime("%H:%M")
        except (ValueError, KeyError):
            verif_time = ""

    pred_label = pred_time[11:16] if len(pred_time) >= 16 else pred_time
    peak_label = verif_time[11:16] if len(verif_time) >= 16 else verif_time

    w = 320
    h = 36
    bar_x = 10
    bar_w = w - 20
    bar_y = 12
    bar_h = 8

    return (
        f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
        f'role="img" aria-label="Timeline: ABR detected a structural change '
        f'{lead_hours:.1f} hours before conventional instruments confirmed '
        f'it." style="display:block;margin:2px 0;">'
        # Background bar (gray)
        f'<rect x="{bar_x}" y="{bar_y}" width="{bar_w}" height="{bar_h}" '
        f'fill="#e8e8e8" rx="4"/>'
        # Lead time bar (green)
        f'<rect x="{bar_x}" y="{bar_y}" width="{bar_w}" height="{bar_h}" '
        f'fill="#27ae60" rx="4" opacity="0.7"/>'
        # Left marker: ABR detection
        f'<circle cx="{bar_x + 2}" cy="{bar_y + bar_h // 2}" r="5" '
        f'fill="#2980b9" stroke="#fff" stroke-width="1.5"/>'
        # Right marker: scalar peak
        f'<circle cx="{bar_x + bar_w - 2}" cy="{bar_y + bar_h // 2}" r="5" '
        f'fill="#e74c3c" stroke="#fff" stroke-width="1.5"/>'
        # Lead time label (centered)
        f'<text x="{w // 2}" y="{bar_y + bar_h // 2 + 1}" '
        f'text-anchor="middle" dominant-baseline="central" '
        f'font-size="10" font-weight="700" fill="#fff" '
        f'font-family="-apple-system, BlinkMacSystemFont, sans-serif">'
        f'{lead_hours:.1f}h early</text>'
        # Time labels below
        f'<text x="{bar_x}" y="{h - 2}" text-anchor="start" '
        f'font-size="8" fill="#888" '
        f'font-family="-apple-system, BlinkMacSystemFont, sans-serif">'
        f'ABR {escape_html(pred_label)}</text>'
        f'<text x="{bar_x + bar_w}" y="{h - 2}" text-anchor="end" '
        f'font-size="8" fill="#888" '
        f'font-family="-apple-system, BlinkMacSystemFont, sans-serif">'
        f'Conventional {escape_html(peak_label)}</text>'
        f'</svg>'
    )


def build_status_badge(status: str) -> str:
    """Return HTML for a status badge."""
    colors = {
        "active": ("#27ae60", "#eafaf1", "ACTIVE"),
        "calibrating": ("#f39c12", "#fef9e7", "CALIBRATING"),
        "data_gap": ("#e74c3c", "#fdedec", "DATA GAP"),
    }
    bg, text_bg, label = colors.get(status, ("#95a5a6", "#f2f3f4", "UNKNOWN"))
    return (
        f'<span class="status-badge" style="background:{text_bg};'
        f'color:{bg};border-color:{bg};">{label}</span>'
    )


def build_prediction_row_class(pred: dict, verifications: list) -> str:
    """Get CSS class for a prediction row based on verification status."""
    pred_id = pred.get("id", "")
    for v in verifications:
        if v.get("pred_id") == pred_id:
            if v.get("status") == "hit":
                return "row-hit"
            elif v.get("status") == "false_alarm":
                return "row-false-alarm"
    if pred.get("calibration_period", False):
        return "row-calibration"
    return ""


def build_network_diagram_svg() -> str:
    """Build an inline SVG showing the station network concept."""
    return """<svg width="100%" height="200" viewBox="0 0 560 200" role="img"
  aria-label="Diagram showing how the system works. Eight weather station
  dots are connected by lines. The system measures differences between
  connected stations (labeled A), accumulates those differences along
  chains (labeled B), and detects cross-coupling between weather
  variables like temperature and pressure (labeled R). The output is
  Gamma, a single number measuring how much the whole network is
  reorganizing."
  style="max-width:560px;margin:1.5em auto;display:block;"
  font-family="-apple-system, BlinkMacSystemFont, sans-serif">
  <rect x="0" y="0" width="560" height="200" fill="#f8f9fa" rx="8"
    stroke="#e0e0e0" stroke-width="1"/>

  <!-- Station dots -->
  <circle cx="80" cy="50" r="8" fill="#2980b9" opacity="0.85"/>
  <circle cx="200" cy="35" r="8" fill="#2980b9" opacity="0.85"/>
  <circle cx="310" cy="55" r="8" fill="#2980b9" opacity="0.85"/>
  <circle cx="420" cy="40" r="8" fill="#2980b9" opacity="0.85"/>
  <circle cx="120" cy="130" r="8" fill="#2980b9" opacity="0.85"/>
  <circle cx="240" cy="145" r="8" fill="#2980b9" opacity="0.85"/>
  <circle cx="360" cy="125" r="8" fill="#2980b9" opacity="0.85"/>
  <circle cx="460" cy="140" r="8" fill="#2980b9" opacity="0.85"/>

  <!-- Edges -->
  <line x1="80" y1="50" x2="200" y2="35" stroke="#2980b9" stroke-width="1.5"
    opacity="0.3"/>
  <line x1="200" y1="35" x2="310" y2="55" stroke="#2980b9" stroke-width="1.5"
    opacity="0.3"/>
  <line x1="310" y1="55" x2="420" y2="40" stroke="#2980b9" stroke-width="1.5"
    opacity="0.3"/>
  <line x1="80" y1="50" x2="120" y2="130" stroke="#2980b9" stroke-width="1.5"
    opacity="0.3"/>
  <line x1="200" y1="35" x2="240" y2="145" stroke="#2980b9" stroke-width="1.5"
    opacity="0.3"/>
  <line x1="310" y1="55" x2="360" y2="125" stroke="#2980b9" stroke-width="1.5"
    opacity="0.3"/>
  <line x1="420" y1="40" x2="460" y2="140" stroke="#2980b9" stroke-width="1.5"
    opacity="0.3"/>
  <line x1="120" y1="130" x2="240" y2="145" stroke="#2980b9" stroke-width="1.5"
    opacity="0.3"/>
  <line x1="240" y1="145" x2="360" y2="125" stroke="#2980b9" stroke-width="1.5"
    opacity="0.3"/>
  <line x1="360" y1="125" x2="460" y2="140" stroke="#2980b9" stroke-width="1.5"
    opacity="0.3"/>
  <line x1="200" y1="35" x2="120" y2="130" stroke="#2980b9" stroke-width="1.5"
    opacity="0.3"/>
  <line x1="310" y1="55" x2="240" y2="145" stroke="#2980b9" stroke-width="1.5"
    opacity="0.3"/>

  <!-- Highlighted: A (difference between two stations) -->
  <line x1="200" y1="35" x2="310" y2="55" stroke="#e67e22" stroke-width="2.5"
    opacity="0.9"/>
  <text x="255" y="28" text-anchor="middle" font-size="11" fill="#e67e22"
    font-weight="600">A: measure differences</text>

  <!-- Highlighted: B (chain accumulation) -->
  <line x1="80" y1="50" x2="200" y2="35" stroke="#27ae60" stroke-width="2.5"
    opacity="0.8"/>
  <line x1="200" y1="35" x2="310" y2="55" stroke="#27ae60" stroke-width="2.5"
    opacity="0.5"/>
  <line x1="310" y1="55" x2="420" y2="40" stroke="#27ae60" stroke-width="2.5"
    opacity="0.3"/>
  <text x="250" y="78" text-anchor="middle" font-size="11" fill="#27ae60"
    font-weight="600">B: track patterns along chains</text>

  <!-- R label -->
  <text x="340" y="100" text-anchor="middle" font-size="11" fill="#8e44ad"
    font-weight="600">R: detect cross-coupling</text>

  <!-- Station labels -->
  <text x="80" y="50" dy="-14" text-anchor="middle" font-size="9"
    fill="#555">SBA</text>
  <text x="200" y="35" dy="-14" text-anchor="middle" font-size="9"
    fill="#555">VNY</text>
  <text x="310" y="55" dy="-14" text-anchor="middle" font-size="9"
    fill="#555">ONT</text>
  <text x="420" y="40" dy="-14" text-anchor="middle" font-size="9"
    fill="#555">PSP</text>
  <text x="120" y="130" dy="20" text-anchor="middle" font-size="9"
    fill="#555">LAX</text>
  <text x="240" y="145" dy="20" text-anchor="middle" font-size="9"
    fill="#555">LGB</text>
  <text x="360" y="125" dy="20" text-anchor="middle" font-size="9"
    fill="#555">SAN</text>
  <text x="460" y="140" dy="20" text-anchor="middle" font-size="9"
    fill="#555">MYF</text>

  <!-- Output -->
  <text x="500" y="88" text-anchor="start" font-size="12" fill="#1a1a2e"
    font-weight="700">&#8594; &#915;</text>
</svg>"""


def build_region_map_svg() -> str:
    """Build a simple inline SVG showing the approximate SoCal monitoring area."""
    return """<svg width="100%" height="220" viewBox="0 0 300 220" role="img"
  aria-label="Simplified map showing the monitoring area along the southern
  California coast, from Santa Barbara in the north to San Diego in the south."
  style="max-width:300px;margin:1em auto;display:block;"
  font-family="-apple-system, BlinkMacSystemFont, sans-serif">
  <rect x="0" y="0" width="300" height="220" fill="#f0f4f8" rx="6"
    stroke="#e0e0e0" stroke-width="1"/>

  <!-- Simplified coast outline -->
  <polyline points="40,10 35,30 30,50 28,70 32,90 45,100 55,108
    70,115 85,118 95,125 100,140 108,155 120,165 135,175 155,185
    175,195 200,200 220,205"
    fill="none" stroke="#8899aa" stroke-width="2" opacity="0.6"/>

  <text x="25" y="160" font-size="10" fill="#8899aa"
    transform="rotate(-60, 25, 160)" opacity="0.5">Pacific Ocean</text>

  <!-- Monitoring area -->
  <rect x="55" y="30" width="180" height="155" fill="#2980b9" opacity="0.08"
    stroke="#2980b9" stroke-width="1.5" stroke-dasharray="4,3" rx="3"/>

  <!-- Cities -->
  <circle cx="60" cy="48" r="3" fill="#e74c3c"/>
  <text x="68" y="52" font-size="9" fill="#555">Santa Barbara</text>
  <circle cx="95" cy="108" r="3" fill="#e74c3c"/>
  <text x="103" y="112" font-size="9" fill="#555">Los Angeles</text>
  <circle cx="155" cy="168" r="3" fill="#e74c3c"/>
  <text x="163" y="172" font-size="9" fill="#555">San Diego</text>

  <text x="145" y="22" text-anchor="middle" font-size="10" fill="#2980b9"
    font-weight="600">Monitoring Area</text>
  <text x="145" y="200" text-anchor="middle" font-size="9" fill="#888">
    33.5&#176;N&#8211;36.0&#176;N, 117.0&#176;W&#8211;121.0&#176;W</text>
</svg>"""


def generate_html(records: list, calibration: dict) -> str:
    """Generate the complete dashboard HTML."""
    observations, predictions, verifications = parse_records(records)
    status = determine_status(observations, calibration)
    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

    # Latest observation data
    latest_obs = observations[-1] if observations else None
    latest_dg_norm = latest_obs.get("dg_norm", 0.0) if latest_obs else 0.0
    latest_dg_raw = latest_obs.get("dg_raw", 0.0) if latest_obs else 0.0
    latest_stations = latest_obs.get("n_stations", 0) if latest_obs else 0
    latest_data_time = latest_obs.get("data_time", "") if latest_obs else ""
    data_freshness = (
        format_time_ago(latest_data_time) if latest_data_time else "no data"
    )

    # Calibration info
    cal_k = calibration.get("recommended_k", "N/A")
    cal_variant = calibration.get("recommended_b_variant", "N/A")
    cal_gate = calibration.get("gate", "N/A")

    run_days = compute_run_days(observations)

    # Active predictions (pending, window not yet closed)
    now = datetime.utcnow()
    active_preds = []
    for p in predictions:
        if p.get("status") != "pending":
            continue
        try:
            window_end = datetime.strptime(
                p["window_end"], "%Y-%m-%dT%H:%M:%SZ"
            )
            if window_end > now:
                active_preds.append(p)
        except (ValueError, KeyError):
            continue

    # Recent verified predictions (last 30)
    verified_pred_ids = {v.get("pred_id"): v for v in verifications}
    verified_preds = []
    for p in predictions:
        pid = p.get("id", "")
        if pid in verified_pred_ids:
            verified_preds.append((p, verified_pred_ids[pid]))
    verified_preds = verified_preds[-30:]

    # Performance stats (exclude calibration-period predictions)
    cal_ids = set()
    for p in predictions:
        if p.get("calibration_period", False):
            cal_ids.add(p.get("id", ""))
    post_cal_verifications = [
        v for v in verifications if v.get("pred_id") not in cal_ids
    ]

    total_pred_count = len(predictions)
    total_verify_count = len(verifications)
    post_cal_hits = sum(
        1 for v in post_cal_verifications if v.get("status") == "hit"
    )
    post_cal_fa = sum(
        1 for v in post_cal_verifications if v.get("status") == "false_alarm"
    )
    post_cal_miss = sum(
        1 for v in post_cal_verifications if v.get("status") == "miss"
    )
    has_post_cal_stats = len(post_cal_verifications) > 0

    precision = (
        post_cal_hits / (post_cal_hits + post_cal_fa)
        if (post_cal_hits + post_cal_fa) > 0
        else 0.0
    )
    recall = (
        post_cal_hits / (post_cal_hits + post_cal_miss)
        if (post_cal_hits + post_cal_miss) > 0
        else 0.0
    )
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )

    hit_leads = [
        v.get("lead_hours", 0.0)
        for v in post_cal_verifications
        if v.get("status") == "hit"
    ]
    mean_lead = sum(hit_leads) / len(hit_leads) if hit_leads else 0.0

    # Build SVG components
    sparkline_svg = build_sparkline_svg(observations, predictions)
    histogram_svg = build_lead_time_histogram(post_cal_verifications)
    status_badge = build_status_badge(status)
    network_svg = build_network_diagram_svg()
    region_map_svg = build_region_map_svg()

    # Build active predictions HTML
    if active_preds:
        active_rows = ""
        for p in active_preds:
            window_end_str = p.get("window_end", "")
            active_rows += (
                f'<tr>'
                f'<td><code>{escape_html(p.get("id", ""))}</code></td>'
                f'<td>{escape_html(p.get("data_time", "")[:16])} UTC</td>'
                f'<td>{p.get("exceedance", 0):.1f}x above normal</td>'
                f'<td>{escape_html(window_end_str[:16])} UTC</td>'
                f'</tr>\n'
            )
        active_section = f"""
        <table class="data-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>When detected</th>
              <th>How strong</th>
              <th>Check by</th>
            </tr>
          </thead>
          <tbody>
            {active_rows}
          </tbody>
        </table>
        <p class="table-note">The system is claiming that conventional weather
        instruments across the network will show significant coordinated
        changes before the "check by" time. After that time, the system will
        automatically verify whether this happened.</p>"""
    else:
        active_section = (
            '<p class="empty-state">No active predictions right now. '
            'The system watches continuously and emits a prediction when '
            'it detects the station network reorganizing structurally. '
            'During calm, stable weather, this can take days or weeks.</p>'
        )

    # Build recent outcomes HTML with timeline bars for hits
    if verified_preds:
        outcome_rows = ""
        for p, v in verified_preds:
            row_class = build_prediction_row_class(p, verifications)
            status_label = v.get("status", "unknown")

            # Status display with friendly labels
            if status_label == "hit":
                status_display = (
                    '<span class="status-hit">Confirmed</span>'
                )
                lead_hours = v.get("lead_hours", 0.0)
                # Build inline timeline SVG for hits
                timeline = build_lead_time_timeline_svg(p, v)
                lead_cell = f'<td>{timeline}</td>' if timeline else (
                    f'<td>{lead_hours:.1f}h early</td>'
                )
            elif status_label == "false_alarm":
                status_display = (
                    '<span class="status-false_alarm">False alarm</span>'
                )
                lead_cell = '<td>&mdash;</td>'
            elif status_label == "miss":
                status_display = (
                    '<span class="status-miss">Missed</span>'
                )
                lead_cell = '<td>&mdash;</td>'
            else:
                status_display = escape_html(status_label)
                lead_cell = '<td>&mdash;</td>'

            outcome_rows += (
                f'<tr class="{row_class}">'
                f'<td>{escape_html(p.get("data_time", "")[:10])}</td>'
                f'<td>{p.get("exceedance", 0):.1f}x</td>'
                f'<td>{status_display}</td>'
                f'{lead_cell}'
                f'</tr>\n'
            )
        outcomes_section = f"""
        <div class="table-explain">
          <p><strong>Confirmed</strong> = conventional instruments showed
          significant coordinated changes within the prediction window
          (the math was right).
          <strong>False alarm</strong> = the system predicted a change
          that didn't materialize (the math was wrong).
          <strong>Missed</strong> = a real weather transition happened
          but the system didn't predict it.</p>
        </div>
        <table class="data-table">
          <thead>
            <tr>
              <th>Date</th>
              <th>Strength</th>
              <th>Result</th>
              <th>How far ahead</th>
            </tr>
          </thead>
          <tbody>
            {outcome_rows}
          </tbody>
        </table>"""
    else:
        days_str = (
            f"{run_days} day{'s' if run_days != 1 else ''}"
            if run_days > 0
            else "less than a day"
        )
        outcomes_section = (
            f'<p class="empty-state">The system has been collecting data for '
            f'{days_str}. Predictions only happen when the relationship '
            f'pattern changes sharply &mdash; during calm, stable weather, '
            f'this may not occur for days or weeks. Each prediction will be '
            f'automatically checked after its time window closes.</p>'
        )

    # Performance stats section
    if has_post_cal_stats:
        # Headline lead time stat
        lead_headline = ""
        if mean_lead > 0:
            lead_headline = (
                f'<div class="lead-headline">'
                f'<span class="lead-number">{mean_lead:.1f}</span> '
                f'<span class="lead-unit">hours of advance warning '
                f'(average)</span></div>'
            )

        stats_section = f"""
        {lead_headline}
        <div class="stats-explain">
          <p><strong>Hit rate</strong> (precision) = of all predictions
          the system made, what percentage turned out to be correct.
          <strong>Detection rate</strong> (recall) = of all real weather
          transitions, what percentage did the system predict in advance.
          <strong>F1</strong> = overall accuracy score combining both.
          <strong>Mean lead</strong> = on average, how many hours ahead
          the system detected the change.</p>
        </div>
        <div class="stats-grid">
          <div class="stat-card">
            <div class="stat-value">{precision:.0%}</div>
            <div class="stat-label">Hit rate</div>
          </div>
          <div class="stat-card">
            <div class="stat-value">{recall:.0%}</div>
            <div class="stat-label">Detection rate</div>
          </div>
          <div class="stat-card">
            <div class="stat-value">{f1:.3f}</div>
            <div class="stat-label">F1 score</div>
          </div>
          <div class="stat-card">
            <div class="stat-value">{mean_lead:.1f}h</div>
            <div class="stat-label">Mean lead time</div>
          </div>
        </div>
        <div class="stats-detail">
          <p>Total predictions: {total_pred_count} &middot;
             Verified: {total_verify_count} &middot;
             Confirmed: {post_cal_hits} &middot;
             False alarms: {post_cal_fa} &middot;
             Missed transitions: {post_cal_miss}</p>
          {f'<div class="histogram-container"><p class="chart-label">Distribution of advance warning times</p>{histogram_svg}</div>' if histogram_svg else ''}
        </div>"""
    else:
        stats_section = (
            '<p class="empty-state">Performance statistics will appear '
            'once predictions have been made and verified. During the '
            'calibration period, the system is learning what "normal" '
            'looks like for this station network so it can identify '
            'departures from normal.</p>'
        )

    # Calibration notice
    calibration_notice = ""
    if status == "calibrating":
        calibration_notice = (
            '<div class="notice notice-calibration">'
            '<strong>Calibration period</strong> &mdash; the system is '
            'establishing what "normal" looks like for this station network. '
            'Predictions during calibration are logged but not counted '
            'toward the accuracy statistics above.'
            '</div>'
        )

    raw_dg_display = format_dg_raw(latest_dg_raw)

    # Assemble HTML
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="robots" content="noindex">
  <meta name="description" content="Live public experiment testing whether
    relational mathematics can detect weather changes before conventional
    instruments. Southern California station network.">
  <title>ABR Weather Monitor</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
                   "Helvetica Neue", Arial, sans-serif;
      font-size: 16px;
      line-height: 1.6;
      color: #333;
      background: #f5f6f7;
    }}

    /* --- Header --- */
    .header {{
      background: #1a1a2e;
      color: #fff;
      padding: 3em 1.5em 2.5em;
      text-align: center;
    }}
    .header h1 {{
      margin: 0 0 0.4em;
      font-size: 2em;
      font-weight: 700;
      letter-spacing: -0.02em;
    }}
    .header .subtitle {{
      margin: 0 0 0.5em;
      font-size: 1.1em;
      color: #d0d0e8;
      max-width: 640px;
      margin-left: auto;
      margin-right: auto;
      line-height: 1.5;
    }}
    .header .elevator {{
      margin: 0 0 1.2em;
      font-size: 0.92em;
      color: #9898b8;
      max-width: 600px;
      margin-left: auto;
      margin-right: auto;
      line-height: 1.5;
    }}
    .header .meta {{
      font-size: 0.85em;
      color: #8888aa;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 1em;
      flex-wrap: wrap;
    }}
    .status-badge {{
      display: inline-block;
      padding: 4px 14px;
      border: 1.5px solid;
      border-radius: 12px;
      font-weight: 600;
      font-size: 0.82em;
      letter-spacing: 0.5px;
    }}

    /* --- Layout --- */
    .container {{
      max-width: 860px;
      margin: 0 auto;
      padding: 2em 1.2em;
    }}
    .section {{
      background: #fff;
      border: 1px solid #e0e0e0;
      border-radius: 8px;
      padding: 1.8em 2em;
      margin-bottom: 1.5em;
    }}
    .section h2 {{
      margin: 0 0 1em;
      font-size: 1.25em;
      font-weight: 700;
      color: #1a1a2e;
      border-bottom: 2px solid #f0f0f0;
      padding-bottom: 0.5em;
    }}
    .section p {{
      margin: 0.6em 0;
    }}

    /* --- Explainer --- */
    .explainer p {{
      color: #444;
      max-width: 700px;
    }}
    .explainer strong {{
      color: #1a1a2e;
    }}
    .key-claim {{
      background: #f0f4ff;
      border-left: 4px solid #2980b9;
      padding: 1em 1.2em;
      margin: 1.2em 0;
      border-radius: 0 6px 6px 0;
      font-size: 0.95em;
      color: #2c3e50;
    }}
    .operator-list {{
      list-style: none;
      padding: 0;
      margin: 1em 0;
    }}
    .operator-list li {{
      padding: 0.6em 0;
      border-bottom: 1px solid #f5f5f5;
      line-height: 1.5;
    }}
    .operator-list li:last-child {{
      border-bottom: none;
    }}
    .op-name {{
      display: inline-block;
      font-weight: 700;
      min-width: 2.8em;
      color: #2980b9;
    }}
    .op-gamma {{
      color: #8e44ad;
    }}

    /* --- Current State --- */
    .current-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
      gap: 1.2em;
    }}
    .current-item {{
      text-align: center;
      padding: 1em;
      background: #f8f9fa;
      border-radius: 8px;
      border: 1px solid #eee;
    }}
    .current-value {{
      font-size: 1.4em;
      font-weight: 700;
      color: #1a1a2e;
      font-variant-numeric: tabular-nums;
    }}
    .current-label {{
      font-size: 0.82em;
      color: #888;
      margin-top: 0.3em;
    }}
    .current-explain {{
      font-size: 0.75em;
      color: #aaa;
      margin-top: 0.2em;
      line-height: 1.3;
    }}

    /* --- Sparkline --- */
    .sparkline-container {{
      padding: 0.5em 0;
    }}
    .sparkline-explain {{
      font-size: 0.88em;
      color: #777;
      margin-bottom: 0.5em;
    }}
    .sparkline-legend {{
      display: flex;
      gap: 2em;
      font-size: 0.82em;
      color: #666;
      margin-top: 0.5em;
      flex-wrap: wrap;
    }}
    .legend-item {{
      display: flex;
      align-items: center;
      gap: 0.5em;
    }}
    .legend-line {{
      display: inline-block;
      width: 20px;
      height: 2px;
    }}
    .legend-dot {{
      display: inline-block;
      width: 10px;
      height: 10px;
      border-radius: 50%;
    }}

    /* --- Tables --- */
    .data-table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.9em;
    }}
    .data-table th {{
      text-align: left;
      padding: 0.6em 0.8em;
      border-bottom: 2px solid #e0e0e0;
      color: #555;
      font-weight: 600;
      font-size: 0.88em;
    }}
    .data-table td {{
      padding: 0.5em 0.8em;
      border-bottom: 1px solid #f0f0f0;
      font-variant-numeric: tabular-nums;
      vertical-align: middle;
    }}
    .data-table code {{
      font-size: 0.85em;
      background: #f5f5f5;
      padding: 0.15em 0.4em;
      border-radius: 3px;
    }}
    .table-note {{
      font-size: 0.85em;
      color: #777;
      margin-top: 0.8em;
      font-style: italic;
    }}
    .table-explain {{
      margin-bottom: 1em;
      padding: 0.8em 1.2em;
      background: #f8f9fa;
      border-radius: 6px;
      font-size: 0.88em;
      color: #555;
      line-height: 1.6;
    }}
    .table-explain p {{
      margin: 0;
    }}
    .row-hit {{ background: #eafaf1; }}
    .row-false-alarm {{ background: #fdedec; }}
    .row-calibration {{ background: #f8f9fa; color: #999; }}
    .status-hit {{ color: #27ae60; font-weight: 600; }}
    .status-false_alarm {{ color: #e74c3c; font-weight: 600; }}
    .status-miss {{ color: #f39c12; font-weight: 600; }}

    /* --- Lead time headline --- */
    .lead-headline {{
      text-align: center;
      padding: 1.2em;
      margin-bottom: 1.2em;
      background: #eafaf1;
      border: 1px solid #a3d9b1;
      border-radius: 8px;
    }}
    .lead-number {{
      font-size: 2.5em;
      font-weight: 700;
      color: #27ae60;
      font-variant-numeric: tabular-nums;
    }}
    .lead-unit {{
      font-size: 1em;
      color: #555;
      display: block;
      margin-top: 0.2em;
    }}

    /* --- Stats --- */
    .stats-explain {{
      margin-bottom: 1.2em;
      padding: 0.8em 1.2em;
      background: #f8f9fa;
      border-radius: 6px;
      font-size: 0.88em;
      color: #555;
      line-height: 1.6;
    }}
    .stats-explain p {{
      margin: 0;
    }}
    .stats-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
      gap: 1em;
      margin-bottom: 1.2em;
    }}
    .stat-card {{
      text-align: center;
      padding: 1em;
      background: #f8f9fa;
      border-radius: 8px;
      border: 1px solid #eee;
    }}
    .stat-value {{
      font-size: 1.6em;
      font-weight: 700;
      color: #1a1a2e;
      font-variant-numeric: tabular-nums;
    }}
    .stat-label {{
      font-size: 0.8em;
      color: #888;
      margin-top: 0.3em;
    }}
    .stats-detail {{
      font-size: 0.88em;
      color: #666;
    }}
    .histogram-container {{
      margin-top: 1em;
    }}
    .chart-label {{
      font-size: 0.85em;
      color: #888;
      margin-bottom: 0.3em;
    }}

    /* --- Notices --- */
    .notice {{
      padding: 1em 1.2em;
      border-radius: 6px;
      margin-bottom: 1.5em;
      font-size: 0.92em;
      line-height: 1.5;
    }}
    .notice-calibration {{
      background: #fef9e7;
      border: 1px solid #f9e79f;
      color: #7d6608;
    }}

    /* --- Collapsed sections --- */
    .empty-state {{
      color: #888;
      font-style: italic;
      padding: 0.5em 0;
      line-height: 1.6;
    }}
    details {{
      border: 1px solid #e0e0e0;
      border-radius: 8px;
      background: #fff;
      margin-bottom: 1.5em;
    }}
    details summary {{
      padding: 1em 1.5em;
      cursor: pointer;
      font-weight: 600;
      color: #1a1a2e;
      font-size: 1em;
    }}
    details summary:hover {{
      background: #f8f9fa;
      border-radius: 8px;
    }}
    details .details-content {{
      padding: 0 1.5em 1.5em;
      font-size: 0.92em;
      color: #555;
      line-height: 1.6;
    }}

    /* --- Region --- */
    .region-grid {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 1.5em;
      align-items: start;
    }}
    .region-info p {{
      margin: 0.4em 0;
      font-size: 0.92em;
      color: #555;
    }}
    .region-info strong {{
      color: #1a1a2e;
    }}
    .coming-soon {{
      display: inline-block;
      padding: 2px 8px;
      background: #eef2ff;
      color: #4a5568;
      border-radius: 4px;
      font-size: 0.82em;
      margin-top: 0.5em;
    }}

    /* --- Verification list --- */
    .verify-list {{
      list-style: none;
      padding: 0;
    }}
    .verify-list li {{
      padding: 0.6em 0;
      border-bottom: 1px solid #f5f5f5;
      font-size: 0.92em;
      color: #555;
    }}
    .verify-list li:last-child {{
      border-bottom: none;
    }}
    .verify-list a {{
      color: #2980b9;
    }}

    /* --- Footer --- */
    .footer {{
      text-align: center;
      padding: 2em 1.5em;
      font-size: 0.82em;
      color: #999;
      border-top: 1px solid #e0e0e0;
      margin-top: 0.5em;
      line-height: 1.8;
    }}
    .footer a {{
      color: #888;
    }}

    /* --- Mobile --- */
    @media (max-width: 600px) {{
      .header {{ padding: 2em 1em 1.5em; }}
      .header h1 {{ font-size: 1.5em; }}
      .header .subtitle {{ font-size: 0.95em; }}
      .container {{ padding: 1em 0.6em; }}
      .section {{ padding: 1.2em 1em; }}
      .current-grid {{ grid-template-columns: repeat(2, 1fr); }}
      .stats-grid {{ grid-template-columns: repeat(2, 1fr); }}
      .data-table {{ font-size: 0.8em; }}
      .data-table th, .data-table td {{ padding: 0.35em 0.4em; }}
      .region-grid {{ grid-template-columns: 1fr; }}
      .lead-number {{ font-size: 2em; }}
    }}
  </style>
</head>
<body>

<!-- ============================================================
     HEADER
     ============================================================ -->
<header class="header">
  <h1>ABR Weather Monitor</h1>
  <p class="subtitle">A live experiment: can math detect weather changes
    before conventional instruments do?</p>
  <p class="elevator">{latest_stations} NOAA weather stations across
    Southern California, analyzed every hour. Instead of looking at
    individual readings, this system analyzes the <em>relationships
    between stations</em> and watches for the pattern to reorganize.</p>
  <div class="meta">
    <span>{status_badge}</span>
    <span>Last updated: {now_str}</span>
  </div>
</header>

<div class="container">

  {calibration_notice}

  <!-- ============================================================
       WHAT IS THIS?
       ============================================================ -->
  <div class="section explainer">
    <h2>What is this?</h2>

    <p>Every hour, roughly {latest_stations} NOAA weather stations
    across Southern California report temperature, pressure, humidity,
    wind speed, and dewpoint. Conventional weather analysis looks at
    these numbers station by station: "Is LAX getting warmer? Is
    pressure dropping at San Diego?"</p>

    <p>This system does something different. It ignores the individual
    readings and instead analyzes the <strong>relationships between
    stations</strong> &mdash; how does temperature at Santa Barbara
    differ from Van Nuys? When pressure diverges between two stations,
    does humidity also diverge? It builds a mathematical picture of
    how the entire network of stations is connected.</p>

    <p>The key finding: <strong>when a weather system is
    approaching</strong> (a front, marine surge, Santa Ana event),
    the pattern of relationships across the station network begins to
    reorganize <em>before</em> any individual station's readings show
    obvious changes. The system detects this reorganization and makes
    a timestamped, public prediction.</p>

    <div class="key-claim">
      <strong>The claim being tested:</strong> This mathematical
      analysis of station relationships detects approaching weather
      changes approximately 4&ndash;10 hours before conventional
      instruments show them. Every prediction is publicly logged and
      automatically verified. This dashboard is the scoreboard.
    </div>

    {network_svg}
  </div>

  <!-- ============================================================
       HOW IT WORKS
       ============================================================ -->
  <div class="section explainer">
    <h2>How does the math work?</h2>

    <p>Three mathematical operators (A, B, R) are applied to the
    station network each hour. Each one builds on the previous:</p>

    <ul class="operator-list">
      <li>
        <span class="op-name">A</span>
        <strong>Measure differences</strong> &mdash; For every pair of
        nearby stations, compute how their readings differ. "Santa
        Barbara is 5&deg;F warmer than Van Nuys. LAX has 2 mb more
        pressure than Ontario." These pairwise differences are the
        raw signal.
      </li>
      <li>
        <span class="op-name">B</span>
        <strong>Track patterns along chains</strong> &mdash; A single
        station pair might show a random fluctuation. But when
        differences build up consistently along a chain of stations
        from coast to inland, that indicates a real spatial pattern.
        B accumulates differences along these chains.
      </li>
      <li>
        <span class="op-name">R</span>
        <strong>Detect cross-coupling</strong> &mdash; This is the key
        step. R asks: when the temperature gradient between two
        stations is large, does the pressure gradient respond too?
        Does humidity couple with wind? When weather variables start
        moving together across the network, something is coming.
      </li>
      <li>
        <span class="op-name op-gamma">&Gamma;</span>
        <strong>The output number</strong> &mdash; &Gamma; (Gamma)
        is a single number summarizing how much cross-coupling the
        whole network shows right now.
        <strong>&Delta;&Gamma;</strong> (Delta Gamma) is how fast
        &Gamma; is changing. A spike in &Delta;&Gamma; means the
        network's relational structure is reorganizing rapidly.
      </li>
    </ul>

    <div class="key-claim">
      When the change index (&Delta;&Gamma;) spikes above its
      statistical threshold, the system predicts that conventional
      weather readings across the network will show significant
      coordinated changes within 4&ndash;10 hours. The chart below
      shows this index in real time.
    </div>
  </div>

  <!-- ============================================================
       CURRENT STATE
       ============================================================ -->
  <div class="section">
    <h2>Live readings</h2>
    <div class="current-grid">
      <div class="current-item">
        <div class="current-value">{latest_dg_norm:+.4f}</div>
        <div class="current-label">Relationship change index</div>
        <div class="current-explain">How fast the pattern of station
          relationships is changing right now</div>
      </div>
      <div class="current-item">
        <div class="current-value">{latest_stations}</div>
        <div class="current-label">Active stations</div>
        <div class="current-explain">NOAA sites reporting this hour</div>
      </div>
      <div class="current-item">
        <div class="current-value" id="freshness">{data_freshness}</div>
        <div class="current-label">Data age</div>
        <div class="current-explain">Time since last station data</div>
      </div>
      <div class="current-item">
        <div class="current-value">CA-SoCal</div>
        <div class="current-label">Region</div>
        <div class="current-explain">Santa Barbara to San Diego</div>
      </div>
    </div>
  </div>

  <!-- ============================================================
       DELTA-GAMMA TREND
       ============================================================ -->
  <div class="section">
    <h2>Relationship change index &mdash; last 48 hours</h2>
    <p class="sparkline-explain">This chart shows how fast the
      relationship pattern is changing over time. When the blue line
      crosses the red dashed threshold, the system emits a prediction
      (orange dot).</p>
    <div class="sparkline-container">
      {sparkline_svg}
    </div>
    <div class="sparkline-legend">
      <span class="legend-item">
        <span class="legend-line" style="background:#2980b9;"></span>
        Change index (&Delta;&Gamma;)
      </span>
      <span class="legend-item">
        <span class="legend-line"
          style="background:transparent;border-top:2px dashed #e74c3c;height:0;">
        </span>
        Prediction threshold
      </span>
      <span class="legend-item">
        <span class="legend-dot" style="background:#e67e22;"></span>
        Prediction emitted
      </span>
    </div>
  </div>

  <!-- ============================================================
       ACTIVE PREDICTIONS
       ============================================================ -->
  <div class="section">
    <h2>Active predictions</h2>
    {active_section}
  </div>

  <!-- ============================================================
       RECENT OUTCOMES
       ============================================================ -->
  <div class="section">
    <h2>Results: was the system right?</h2>
    {outcomes_section}
  </div>

  <!-- ============================================================
       PERFORMANCE
       ============================================================ -->
  <div class="section">
    <h2>Overall accuracy</h2>
    {stats_section}
  </div>

  <!-- ============================================================
       REGION INFO
       ============================================================ -->
  <div class="section">
    <h2>Monitoring region</h2>
    <div class="region-grid">
      <div class="region-info">
        <p><strong>Southern California</strong></p>
        <p>Santa Barbara to San Diego, coast to inland valleys</p>
        <p>Latitude: 33.5&deg;N &ndash; 36.0&deg;N</p>
        <p>Longitude: 121.0&deg;W &ndash; 117.0&deg;W</p>
        <p>Stations: 23&ndash;31 NOAA ASOS/METAR sites
        (count varies hourly depending on data availability)</p>
        <p><span class="coming-soon">Additional regions planned</span></p>
      </div>
      <div>
        {region_map_svg}
      </div>
    </div>
  </div>

  <!-- ============================================================
       TECHNICAL DETAILS (collapsed)
       ============================================================ -->
  <details>
    <summary>Technical details</summary>
    <div class="details-content">
      <p><strong>Raw &Delta;&Gamma; value:</strong> {raw_dg_display}
      (before normalization)</p>
      <p>The "relationship change index" shown on this dashboard is the
      normalized &Delta;&Gamma;: the raw change divided by the current
      &Gamma; magnitude. This produces a dimensionless ratio that is
      comparable across different network sizes and conditions. The raw
      value is in arbitrary units determined by station geometry.</p>

      <p><strong>Detection parameters:</strong></p>
      <ul>
        <li>Threshold: {cal_k} standard deviations above rolling baseline</li>
        <li>Operator variant: {cal_variant}</li>
        <li>Prediction window: 4&ndash;10 hours after detection</li>
        <li>Debounce: 6-hour cooldown between predictions (prevents
        clustering)</li>
        <li>Topology guard: detection suppressed if more than 2 stations
        drop/join (avoids artifacts from network reconfiguration)</li>
      </ul>

      <p><strong>Calibration status:</strong> {cal_gate}</p>
      <p><strong>Mathematical basis:</strong> V4 ABR operators (A: gradient,
      B: accumulation, R: circulation) applied over declared station-pair
      relations with 5 weather components (temperature, pressure, humidity,
      wind speed, dewpoint depression).</p>
    </div>
  </details>

  <!-- ============================================================
       VERIFICATION & TRANSPARENCY
       ============================================================ -->
  <div class="section">
    <h2>Verification &amp; transparency</h2>
    <p>This experiment is designed to be publicly auditable. You don't
    have to take our word for any of the results above.</p>
    <ul class="verify-list">
      <li><strong>Every prediction is a git commit</strong> &mdash;
      timestamped and immutable. You can verify no predictions were
      added after the fact:
      <a href="https://github.com/energyscholar/abr-weather-monitor/commits/main/data/predictions.jsonl"
        >view commit history</a></li>
      <li><strong>Data source</strong> &mdash; Iowa Environmental
      Mesonet (IEM) / NOAA ASOS and METAR network. All data is public
      domain and freely available.</li>
      <li><strong>Source code</strong> &mdash; the analysis code,
      operators, and this dashboard generator are all open source:
      <a href="https://github.com/energyscholar/abr-weather-monitor"
        >github.com/.../abr-weather-monitor</a></li>
      <li><strong>Built on</strong> V4 ABR relational operators by
      Robin Macomber / Metatron Dynamics.</li>
    </ul>
  </div>

  <!-- ============================================================
       FOOTER
       ============================================================ -->
  <div class="footer">
    <p>Data: Iowa Environmental Mesonet / NOAA ASOS &amp; METAR
    &middot; Public domain</p>
    <p>Last generated: {now_str}</p>
    <p><a href="https://github.com/energyscholar/abr-weather-monitor"
      >Source on GitHub</a></p>
  </div>

</div>

<script>
// Live data-age counter
(function() {{
  var el = document.getElementById('freshness');
  if (!el) return;
  var dataTime = '{latest_data_time}';
  if (!dataTime) return;
  function update() {{
    var t = new Date(dataTime);
    var now = new Date();
    var diffMs = now - t;
    var totalMin = Math.floor(diffMs / 60000);
    if (totalMin < 1) {{
      el.textContent = 'just now';
    }} else if (totalMin < 60) {{
      el.textContent = totalMin + 'm ago';
    }} else if (totalMin < 1440) {{
      var h = Math.floor(totalMin / 60);
      var m = totalMin % 60;
      el.textContent = m > 0 ? h + 'h ' + m + 'm ago' : h + 'h ago';
    }} else {{
      el.textContent = (totalMin / 1440).toFixed(1) + 'd ago';
    }}
  }}
  update();
  setInterval(update, 60000);
}})();
</script>

</body>
</html>"""

    return html


def main():
    """Generate the dashboard HTML file."""
    records = load_predictions()
    calibration = load_calibration()

    html = generate_html(records, calibration)

    # Ensure output directory exists
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with open(OUTPUT_PATH, "w") as f:
        f.write(html)

    # Report
    obs_count = sum(1 for r in records if r.get("type") == "obs")
    pred_count = sum(1 for r in records if r.get("type") == "pred")
    verify_count = sum(1 for r in records if r.get("type") == "verify")

    print(f"Dashboard generated: {OUTPUT_PATH}")
    print(f"  Records: {obs_count} obs, {pred_count} pred, {verify_count} verify")
    print(f"  File size: {OUTPUT_PATH.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
