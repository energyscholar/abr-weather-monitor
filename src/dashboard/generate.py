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
        # We're in early calibration
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
    """Format an ISO timestamp as 'N hours ago' or 'N minutes ago'."""
    try:
        t = datetime.strptime(iso_str, "%Y-%m-%dT%H:%M:%SZ")
        delta = datetime.utcnow() - t
        hours = delta.total_seconds() / 3600
        if hours < 1:
            minutes = int(delta.total_seconds() / 60)
            return f"{minutes}m ago"
        if hours < 24:
            return f"{hours:.1f}h ago"
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


def build_sparkline_svg(observations: list, predictions: list) -> str:
    """Build an inline SVG sparkline of DeltaGamma over last 48 hours.

    Shows normalized DeltaGamma values, threshold line, and prediction dots.
    """
    if not observations:
        return (
            '<svg width="100%" height="80" viewBox="0 0 600 80" '
            'aria-label="No observation data available for sparkline chart">'
            '<text x="300" y="45" text-anchor="middle" fill="#888" '
            'font-size="14">No data yet</text></svg>'
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
            '<svg width="100%" height="80" viewBox="0 0 600 80" '
            'aria-label="Empty sparkline chart">'
            '<text x="300" y="45" text-anchor="middle" fill="#888" '
            'font-size="14">No data</text></svg>'
        )

    # SVG dimensions
    w, h = 600, 80
    pad_x, pad_y = 10, 10
    plot_w = w - 2 * pad_x
    plot_h = h - 2 * pad_y

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
        return pad_x + (i / max(n - 1, 1)) * plot_w

    def y_pos(v):
        return pad_y + plot_h - ((v - min_val) / val_range) * plot_h

    # Build polyline path for DeltaGamma
    points = " ".join(f"{x_pos(i):.1f},{y_pos(v):.1f}" for i, v in enumerate(dg_values))

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

    # Build SVG
    svg_parts = [
        f'<svg width="100%" height="80" viewBox="0 0 {w} {h}" '
        f'preserveAspectRatio="xMidYMid meet" '
        f'aria-label="DeltaGamma sparkline showing {n} hourly observations. '
        f'Values range from {min(dg_values):.4f} to {max(dg_values):.4f}. '
        f'{len(pred_dots)} prediction(s) marked.">',
        # Background
        f'<rect x="0" y="0" width="{w}" height="{h}" fill="#fafafa" rx="4"/>',
        # Zero line
        f'<line x1="{pad_x}" y1="{zero_y:.1f}" x2="{w - pad_x}" '
        f'y2="{zero_y:.1f}" stroke="#ddd" stroke-width="1" '
        f'stroke-dasharray="4,4"/>',
    ]

    # Threshold line
    if threshold_val > 0:
        ty = y_pos(threshold_val)
        svg_parts.append(
            f'<line x1="{pad_x}" y1="{ty:.1f}" x2="{w - pad_x}" '
            f'y2="{ty:.1f}" stroke="#e74c3c" stroke-width="1.5" '
            f'stroke-dasharray="6,3" aria-label="Threshold at {threshold_val:.4f}"/>'
        )

    # DeltaGamma line
    svg_parts.append(
        f'<polyline points="{points}" fill="none" stroke="#2980b9" '
        f'stroke-width="1.5" stroke-linejoin="round" '
        f'aria-label="DeltaGamma normalized values"/>'
    )

    # Prediction dots
    for px, py in pred_dots:
        svg_parts.append(
            f'<circle cx="{px:.1f}" cy="{py:.1f}" r="4" '
            f'fill="#e67e22" stroke="#d35400" stroke-width="1" '
            f'aria-label="Prediction emitted at this time"/>'
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

    # SVG dimensions
    w, h = 200, 60
    pad = 5
    bar_w = (w - 2 * pad) / n_bins

    svg_parts = [
        f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
        f'aria-label="Lead time histogram with {len(lead_times)} hits. '
        f'Lead times range from {min(lead_times):.1f} to {max(lead_times):.1f} hours.">',
        f'<rect x="0" y="0" width="{w}" height="{h}" fill="#fafafa" rx="3"/>',
    ]

    for i, count in enumerate(bins):
        bar_h = (count / max(max_count, 1)) * (h - 2 * pad - 12)
        bx = pad + i * bar_w + 1
        by = h - pad - bar_h
        svg_parts.append(
            f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bar_w - 2:.1f}" '
            f'height="{bar_h:.1f}" fill="#2980b9" rx="1" '
            f'aria-label="{count} predictions with lead time '
            f'{i * bin_width:.0f}-{(i + 1) * bin_width:.0f}h"/>'
        )

    # X axis label
    svg_parts.append(
        f'<text x="{w / 2}" y="{h - 1}" text-anchor="middle" '
        f'font-size="9" fill="#666">Lead time (hours)</text>'
    )

    svg_parts.append("</svg>")
    return "\n".join(svg_parts)


def build_status_badge(status: str) -> str:
    """Return HTML for a status badge."""
    colors = {
        "active": ("#27ae60", "#eafaf1", "ACTIVE"),
        "calibrating": ("#f39c12", "#fef9e7", "CALIBRATING"),
        "data_gap": ("#e74c3c", "#fdedec", "DATA GAP"),
    }
    bg, text_bg, label = colors.get(status, ("#95a5a6", "#f2f3f4", "UNKNOWN"))
    return (
        f'<span style="display:inline-block;padding:4px 12px;'
        f'background:{text_bg};color:{bg};border:1px solid {bg};'
        f'border-radius:12px;font-weight:600;font-size:0.85em;'
        f'letter-spacing:0.5px;">{label}</span>'
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
    data_freshness = format_time_ago(latest_data_time) if latest_data_time else "no data"

    # Calibration info
    cal_k = calibration.get("recommended_k", "N/A")
    cal_variant = calibration.get("recommended_b_variant", "N/A")
    cal_gate = calibration.get("gate", "N/A")

    # Active predictions (pending, window not yet closed)
    now = datetime.utcnow()
    active_preds = []
    for p in predictions:
        if p.get("status") != "pending":
            continue
        try:
            window_end = datetime.strptime(p["window_end"], "%Y-%m-%dT%H:%M:%SZ")
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
    verified_preds = verified_preds[-30:]  # last 30

    # Performance stats (exclude calibration)
    cal_ids = set()
    for p in predictions:
        if p.get("calibration_period", False):
            cal_ids.add(p.get("id", ""))
    post_cal_verifications = [
        v for v in verifications if v.get("pred_id") not in cal_ids
    ]

    total_pred_count = len(predictions)
    total_verify_count = len(verifications)
    post_cal_hits = sum(1 for v in post_cal_verifications if v.get("status") == "hit")
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

    # Build active predictions HTML
    if active_preds:
        active_rows = ""
        for p in active_preds:
            window_end_str = p.get("window_end", "")
            active_rows += (
                f'<tr>'
                f'<td><code>{escape_html(p.get("id", ""))}</code></td>'
                f'<td>{escape_html(p.get("data_time", "")[:16])}</td>'
                f'<td>{escape_html(p.get("b_variant", ""))}</td>'
                f'<td>{p.get("exceedance", 0):.2f}x</td>'
                f'<td>{escape_html(window_end_str[:16])}</td>'
                f'</tr>\n'
            )
        active_section = f"""
        <table class="data-table">
          <thead>
            <tr>
              <th>Prediction ID</th>
              <th>Issued</th>
              <th>Variant</th>
              <th>Exceedance</th>
              <th>Window Closes</th>
            </tr>
          </thead>
          <tbody>
            {active_rows}
          </tbody>
        </table>"""
    else:
        active_section = '<p class="empty-state">No active predictions</p>'

    # Build recent outcomes HTML
    if verified_preds:
        outcome_rows = ""
        for p, v in verified_preds:
            row_class = build_prediction_row_class(p, verifications)
            status_label = v.get("status", "unknown")
            lead_str = (
                f'{v.get("lead_hours", 0):.1f}h'
                if v.get("status") == "hit"
                else "&mdash;"
            )
            outcome_rows += (
                f'<tr class="{row_class}">'
                f'<td>{escape_html(p.get("data_time", "")[:10])}</td>'
                f'<td>{escape_html(p.get("b_variant", ""))}</td>'
                f'<td>{p.get("delta_gamma", 0):.4f}</td>'
                f'<td>{p.get("exceedance", 0):.2f}x</td>'
                f'<td class="status-{status_label}">{status_label}</td>'
                f'<td>{lead_str}</td>'
                f'</tr>\n'
            )
        outcomes_section = f"""
        <table class="data-table">
          <thead>
            <tr>
              <th>Date</th>
              <th>Variant</th>
              <th>&Delta;&Gamma;</th>
              <th>Exceedance</th>
              <th>Status</th>
              <th>Lead Time</th>
            </tr>
          </thead>
          <tbody>
            {outcome_rows}
          </tbody>
        </table>"""
    else:
        outcomes_section = (
            '<p class="empty-state">No verified predictions yet &mdash; '
            'system is accumulating data</p>'
        )

    # Performance stats section
    if has_post_cal_stats:
        stats_section = f"""
        <div class="stats-grid">
          <div class="stat-card">
            <div class="stat-value">{precision:.3f}</div>
            <div class="stat-label">Precision</div>
          </div>
          <div class="stat-card">
            <div class="stat-value">{recall:.3f}</div>
            <div class="stat-label">Recall</div>
          </div>
          <div class="stat-card">
            <div class="stat-value">{f1:.3f}</div>
            <div class="stat-label">F1</div>
          </div>
          <div class="stat-card">
            <div class="stat-value">{mean_lead:.1f}h</div>
            <div class="stat-label">Mean Lead</div>
          </div>
        </div>
        <div class="stats-detail">
          <p>Total predictions: {total_pred_count} &middot;
             Verified: {total_verify_count} &middot;
             Hits: {post_cal_hits} &middot;
             False alarms: {post_cal_fa} &middot;
             Missed: {post_cal_miss}</p>
          {f'<div class="histogram-container"><p class="chart-label">Lead time distribution</p>{histogram_svg}</div>' if histogram_svg else ''}
        </div>"""
    else:
        stats_section = (
            '<p class="empty-state">Performance statistics will appear '
            'after the calibration period ends and predictions are verified.</p>'
        )

    # Calibration notice
    calibration_notice = ""
    if status == "calibrating":
        calibration_notice = (
            '<div class="notice notice-calibration">'
            'CALIBRATION PERIOD &mdash; predictions are logged but not counted '
            'toward performance statistics. '
            f'Calibration config: k={cal_k}, B={cal_variant}, gate={cal_gate}.'
            '</div>'
        )

    # Assemble the full HTML
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="robots" content="noindex">
  <title>ABR Weather Monitor</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
                   "Helvetica Neue", Arial, sans-serif;
      font-size: 15px;
      line-height: 1.5;
      color: #333;
      background: #f5f6f7;
    }}
    .header {{
      background: #1a1a2e;
      color: #fff;
      padding: 2em 1.5em;
      text-align: center;
    }}
    .header h1 {{
      margin: 0 0 0.3em;
      font-size: 1.6em;
      font-weight: 600;
      letter-spacing: -0.02em;
    }}
    .header .subtitle {{
      margin: 0 0 1em;
      font-size: 0.95em;
      color: #a0a0c0;
      max-width: 600px;
      margin-left: auto;
      margin-right: auto;
    }}
    .header .meta {{
      font-size: 0.82em;
      color: #8888aa;
    }}
    .container {{
      max-width: 900px;
      margin: 0 auto;
      padding: 1.5em 1em;
    }}
    .section {{
      background: #fff;
      border: 1px solid #e0e0e0;
      border-radius: 6px;
      padding: 1.2em 1.5em;
      margin-bottom: 1.2em;
    }}
    .section h2 {{
      margin: 0 0 0.8em;
      font-size: 1.1em;
      font-weight: 600;
      color: #1a1a2e;
      border-bottom: 1px solid #eee;
      padding-bottom: 0.5em;
    }}
    .current-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
      gap: 1em;
    }}
    .current-item {{
      text-align: center;
    }}
    .current-value {{
      font-size: 1.3em;
      font-weight: 700;
      color: #1a1a2e;
      font-variant-numeric: tabular-nums;
    }}
    .current-label {{
      font-size: 0.8em;
      color: #888;
      margin-top: 0.2em;
    }}
    .sparkline-container {{
      padding: 0.5em 0;
    }}
    .sparkline-legend {{
      display: flex;
      gap: 1.5em;
      font-size: 0.78em;
      color: #666;
      margin-top: 0.3em;
    }}
    .legend-item {{
      display: flex;
      align-items: center;
      gap: 0.4em;
    }}
    .legend-line {{
      display: inline-block;
      width: 18px;
      height: 2px;
    }}
    .legend-dot {{
      display: inline-block;
      width: 8px;
      height: 8px;
      border-radius: 50%;
    }}
    .data-table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.88em;
    }}
    .data-table th {{
      text-align: left;
      padding: 0.5em 0.7em;
      border-bottom: 2px solid #e0e0e0;
      color: #555;
      font-weight: 600;
      font-size: 0.9em;
    }}
    .data-table td {{
      padding: 0.45em 0.7em;
      border-bottom: 1px solid #f0f0f0;
      font-variant-numeric: tabular-nums;
    }}
    .data-table code {{
      font-size: 0.85em;
      background: #f5f5f5;
      padding: 0.15em 0.4em;
      border-radius: 3px;
    }}
    .row-hit {{ background: #eafaf1; }}
    .row-false-alarm {{ background: #fdedec; }}
    .row-calibration {{ background: #f8f9fa; color: #999; }}
    .status-hit {{ color: #27ae60; font-weight: 600; }}
    .status-false_alarm {{ color: #e74c3c; font-weight: 600; }}
    .status-miss {{ color: #f39c12; font-weight: 600; }}
    .stats-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(100px, 1fr));
      gap: 0.8em;
      margin-bottom: 1em;
    }}
    .stat-card {{
      text-align: center;
      padding: 0.8em;
      background: #f8f9fa;
      border-radius: 6px;
      border: 1px solid #eee;
    }}
    .stat-value {{
      font-size: 1.5em;
      font-weight: 700;
      color: #1a1a2e;
      font-variant-numeric: tabular-nums;
    }}
    .stat-label {{
      font-size: 0.78em;
      color: #888;
      margin-top: 0.2em;
    }}
    .stats-detail {{
      font-size: 0.85em;
      color: #666;
    }}
    .histogram-container {{
      margin-top: 0.8em;
    }}
    .chart-label {{
      font-size: 0.82em;
      color: #888;
      margin-bottom: 0.3em;
    }}
    .notice {{
      padding: 0.8em 1em;
      border-radius: 5px;
      margin-bottom: 1em;
      font-size: 0.9em;
    }}
    .notice-calibration {{
      background: #fef9e7;
      border: 1px solid #f9e79f;
      color: #7d6608;
    }}
    .empty-state {{
      color: #888;
      font-style: italic;
      padding: 0.5em 0;
    }}
    details {{
      border: 1px solid #e0e0e0;
      border-radius: 6px;
      background: #fff;
      margin-bottom: 1.2em;
    }}
    details summary {{
      padding: 0.8em 1.2em;
      cursor: pointer;
      font-weight: 600;
      color: #1a1a2e;
      font-size: 0.95em;
    }}
    details summary:hover {{
      background: #f8f9fa;
    }}
    details .details-content {{
      padding: 0 1.2em 1.2em;
      font-size: 0.9em;
      color: #555;
      line-height: 1.6;
    }}
    .footer {{
      text-align: center;
      padding: 1.5em;
      font-size: 0.78em;
      color: #999;
      border-top: 1px solid #e0e0e0;
      margin-top: 1em;
    }}
    @media (max-width: 600px) {{
      .header {{ padding: 1.5em 1em; }}
      .header h1 {{ font-size: 1.3em; }}
      .container {{ padding: 1em 0.5em; }}
      .section {{ padding: 1em; }}
      .current-grid {{ grid-template-columns: repeat(2, 1fr); }}
      .stats-grid {{ grid-template-columns: repeat(2, 1fr); }}
      .data-table {{ font-size: 0.8em; }}
      .data-table th, .data-table td {{ padding: 0.35em 0.4em; }}
    }}
  </style>
</head>
<body>

<header class="header">
  <h1>ABR Weather Monitor &mdash; Live Predictions</h1>
  <p class="subtitle">Relational operators detect structural weather transitions
    before conventional indices</p>
  <p class="meta">Last updated: {now_str} &middot; {status_badge}</p>
</header>

<div class="container">

  {calibration_notice}

  <div class="section">
    <h2>Current State</h2>
    <div class="current-grid">
      <div class="current-item">
        <div class="current-value">{latest_dg_norm:+.4f}</div>
        <div class="current-label">&Delta;&Gamma; (normalized)</div>
      </div>
      <div class="current-item">
        <div class="current-value">{latest_dg_raw:+.0f}</div>
        <div class="current-label">&Delta;&Gamma; (raw)</div>
      </div>
      <div class="current-item">
        <div class="current-value">{latest_stations}</div>
        <div class="current-label">Stations</div>
      </div>
      <div class="current-item">
        <div class="current-value" id="freshness">{data_freshness}</div>
        <div class="current-label">Data age</div>
      </div>
    </div>
  </div>

  <div class="section">
    <h2>&Delta;&Gamma; Trend (Last 48 Hours)</h2>
    <div class="sparkline-container">
      {sparkline_svg}
    </div>
    <div class="sparkline-legend">
      <span class="legend-item">
        <span class="legend-line" style="background:#2980b9;"></span>
        &Delta;&Gamma; normalized
      </span>
      <span class="legend-item">
        <span class="legend-line" style="background:#e74c3c;border-top:1px dashed #e74c3c;height:0;"></span>
        Threshold
      </span>
      <span class="legend-item">
        <span class="legend-dot" style="background:#e67e22;"></span>
        Prediction
      </span>
    </div>
  </div>

  <div class="section">
    <h2>Active Predictions</h2>
    {active_section}
  </div>

  <div class="section">
    <h2>Recent Outcomes</h2>
    {outcomes_section}
  </div>

  <div class="section">
    <h2>Performance</h2>
    {stats_section}
  </div>

  <details>
    <summary>Methodology</summary>
    <div class="details-content">
      <p><strong>ABR relational operators</strong> extract structural transitions
      from weather station networks. The operator chain A&rarr;B&rarr;R computes
      a circulation measure &Gamma; (Gamma) from pairwise temperature and pressure
      differences across stations. &Delta;&Gamma; is the hourly change in &Gamma;.</p>

      <p>When &Delta;&Gamma; exceeds a calibrated threshold (k&sigma; above the
      rolling baseline), the system emits a <strong>prediction</strong> that a
      measurable weather transition (pressure swing, temperature shift, wind
      change) will occur within a 4&ndash;10 hour window.</p>

      <p>Predictions are verified against conventional scalar weather indices.
      Each prediction is committed to git with a timestamp, creating a tamper-evident
      record. Verify: <code>git log --oneline data/predictions.jsonl</code></p>

      <p>Built on V4 ABR operators by Robin Macomber / Metatron Dynamics.</p>
    </div>
  </details>

  <div class="footer">
    <p>Data source: Iowa Environmental Mesonet (NOAA ASOS/METAR). Public domain.</p>
    <p>Last run: {now_str}</p>
  </div>

</div>

<script>
// Compute live data freshness
(function() {{
  var el = document.getElementById('freshness');
  if (!el) return;
  var dataTime = '{latest_data_time}';
  if (!dataTime) return;
  function update() {{
    var t = new Date(dataTime);
    var now = new Date();
    var diffMs = now - t;
    var diffMin = Math.floor(diffMs / 60000);
    if (diffMin < 60) {{
      el.textContent = diffMin + 'm ago';
    }} else if (diffMin < 1440) {{
      el.textContent = (diffMin / 60).toFixed(1) + 'h ago';
    }} else {{
      el.textContent = (diffMin / 1440).toFixed(1) + 'd ago';
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
