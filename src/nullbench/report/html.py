"""Single-file static HTML report — no SPA, no external CDN required."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from nullbench.core.models import ExperimentSpec, ReportSummary


def write_html_report(
    path: Path,
    *,
    spec: ExperimentSpec,
    summary: ReportSummary,
    settles: list[dict[str, Any]],
    formal: dict[str, Any] | None = None,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        render_html(spec=spec, summary=summary, settles=settles, formal=formal),
        encoding="utf-8",
    )
    return path


def render_html(
    *,
    spec: ExperimentSpec,
    summary: ReportSummary,
    settles: list[dict[str, Any]],
    formal: dict[str, Any] | None = None,
) -> str:
    esc = html.escape
    claim = summary.claim_status.value
    claim_class = "formal" if claim == "formal_endpoint" else "desc"

    rows = []
    for sid, pnl in sorted(summary.strategy_cum_pnl.items()):
        pct = summary.strategy_percentiles.get(sid, float("nan"))
        ev = summary.sequential_evidence.get(sid, {})
        lcb = ev.get("lcb")
        ucb = ev.get("ucb")
        epq = ev.get("e_pq", ev.get("e_value"))
        rows.append(
            "<tr>"
            f"<td><code>{esc(sid)}</code></td>"
            f"<td class='num'>{pnl:.2f}</td>"
            f"<td class='num'>{pct:.1f}</td>"
            f"<td class='num'>{_fmt(epq)}</td>"
            f"<td class='num'>{_fmt(lcb)}</td>"
            f"<td class='num'>{_fmt(ucb)}</td>"
            f"<td><code>{esc(str(ev.get('backend', '—')))}</code></td>"
            "</tr>"
        )

    warn_lis = "".join(f"<li>{esc(w)}</li>" for w in summary.warnings)
    formal_block = _formal_section(formal)

    recent = []
    for s in settles[-8:]:
        draw = s.get("draw") or {}
        nums = draw.get("numbers", [])
        lines = [
            f"<h3>{esc(str(s.get('period')))} "
            f"<span class='muted'>{esc(str(draw.get('date') or ''))}</span></h3>",
            f"<p>Draw: <code>{esc(str(nums))}</code>",
        ]
        if draw.get("special") is not None:
            lines[-1] += f" special=<code>{esc(str(draw['special']))}</code>"
        lines[-1] += "</p><ul>"
        for r in s.get("strategy_results", []):
            pnl = r["payout"] - r["cost"]
            lines.append(
                f"<li><code>{esc(r['portfolio_id'])}</code>: "
                f"cost={r['cost']:.0f} payout={r['payout']:.0f} "
                f"pnl=<strong>{pnl:.0f}</strong></li>"
            )
        lines.append("</ul>")
        recent.append("\n".join(lines))

    # Chart data (sparkline-friendly cumulative series)
    chart = _cum_series(settles)
    chart_json = json.dumps(chart)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>nullbench — {esc(summary.experiment_id)}</title>
<style>
:root {{
  --bg: #0f1419; --card: #1a2332; --text: #e7ecf3; --muted: #8b9bb4;
  --accent: #3d9cf0; --good: #3ecf8e; --warn: #f0b429; --bad: #f07178;
  --border: #2a3548; --mono: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  --sans: "Segoe UI", system-ui, -apple-system, sans-serif;
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0; padding: 2rem 1.25rem 4rem;
  font-family: var(--sans); background: var(--bg); color: var(--text);
  line-height: 1.55; max-width: 920px; margin-inline: auto;
}}
h1 {{ font-size: 1.6rem; margin: 0 0 .25rem; letter-spacing: -0.02em; }}
h2 {{ font-size: 1.15rem; margin: 2rem 0 .75rem; color: var(--accent); }}
h3 {{ font-size: 1rem; margin: 1.25rem 0 .4rem; }}
.muted {{ color: var(--muted); font-weight: 400; }}
.badge {{
  display: inline-block; padding: .2rem .55rem; border-radius: 999px;
  font-size: .75rem; font-weight: 600; letter-spacing: .03em; text-transform: uppercase;
}}
.badge.desc {{ background: #2a3548; color: var(--muted); }}
.badge.formal {{ background: #1e3d2f; color: var(--good); }}
.card {{
  background: var(--card); border: 1px solid var(--border);
  border-radius: 12px; padding: 1rem 1.15rem; margin: 1rem 0;
}}
table {{ width: 100%; border-collapse: collapse; font-size: .92rem; }}
th, td {{ padding: .45rem .5rem; border-bottom: 1px solid var(--border); text-align: left; }}
th {{ color: var(--muted); font-weight: 600; font-size: .78rem; text-transform: uppercase; }}
td.num {{ text-align: right; font-variant-numeric: tabular-nums; font-family: var(--mono); }}
code {{ font-family: var(--mono); font-size: .88em; color: #9cdcfe; }}
ul.warn {{ color: var(--warn); padding-left: 1.2rem; }}
.disclaimer {{
  border-left: 3px solid var(--accent); padding: .5rem 0 .5rem 1rem;
  color: var(--muted); margin: 1rem 0;
}}
footer {{ margin-top: 3rem; color: var(--muted); font-size: .85rem; }}
svg.spark {{ width: 100%; height: 160px; background: #121a24; border-radius: 8px; }}
.meta {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: .75rem; }}
.meta div {{ background: #121a24; border-radius: 8px; padding: .65rem .75rem; }}
.meta .k {{ font-size: .72rem; color: var(--muted); text-transform: uppercase; }}
.meta .v {{ font-size: 1.05rem; font-weight: 600; margin-top: .15rem; }}
</style>
</head>
<body>
<header>
  <p class="muted">nullbench report</p>
  <h1>{esc(summary.experiment_id)}</h1>
  <p><span class="badge {claim_class}">{esc(claim)}</span></p>
  <p class="disclaimer">{esc(summary.disclaimer)}</p>
</header>

<section class="card meta">
  <div><div class="k">Domain</div><div class="v">{esc(spec.domain)}</div></div>
  <div><div class="k">Game</div><div class="v">{esc(spec.game.name)}</div></div>
  <div><div class="k">Periods settled</div><div class="v">{summary.periods_settled}</div></div>
  <div><div class="k">Null portfolios</div><div class="v">{spec.null_portfolios}</div></div>
  <div><div class="k">Null mean cum P&amp;L</div><div class="v">{summary.null_mean_cum_pnl:.2f}</div></div>
</section>

<h2>Strategy vs equal-cost chance</h2>
<div class="card">
<table>
  <thead>
    <tr>
      <th>Strategy</th><th>Cum P&amp;L</th><th>%ile vs null</th>
      <th>e_pq</th><th>CS LCB</th><th>CS UCB</th><th>Backend</th>
    </tr>
  </thead>
  <tbody>
    {"".join(rows)}
  </tbody>
</table>
</div>

<h2>Cumulative P&amp;L (sparkline)</h2>
<div class="card">
  <svg class="spark" id="spark" viewBox="0 0 800 160" preserveAspectRatio="none"></svg>
  <p class="muted" id="spark-legend"></p>
</div>

{formal_block}

<h2>Warnings</h2>
<ul class="warn">{warn_lis or "<li>None</li>"}</ul>

<h2>Recent periods</h2>
<div class="card">
{"".join(recent) or "<p class='muted'>No settlements</p>"}
</div>

<footer>
  <p>Generated {esc(str(summary.generated_at))} · single-file static HTML · no network required to view</p>
  <p>Pre-register before outcomes. Never backfill. Not a prediction product.</p>
</footer>

<script>
const CHART = {chart_json};
(function() {{
  const svg = document.getElementById('spark');
  const legend = document.getElementById('spark-legend');
  if (!svg || !CHART.series || !CHART.series.length) return;
  const W = 800, H = 160, pad = 12;
  let all = [];
  CHART.series.forEach(s => {{ all = all.concat(s.values); }});
  const min = Math.min(...all, 0), max = Math.max(...all, 0);
  const span = (max - min) || 1;
  const colors = ['#3d9cf0', '#3ecf8e', '#f0b429', '#f07178', '#c3a6ff'];
  const names = [];
  CHART.series.forEach((s, i) => {{
    names.push(s.id);
    const n = s.values.length;
    if (n < 1) return;
    let d = '';
    s.values.forEach((v, j) => {{
      const x = pad + (n === 1 ? 0 : (j / (n - 1)) * (W - 2 * pad));
      const y = H - pad - ((v - min) / span) * (H - 2 * pad);
      d += (j === 0 ? 'M' : 'L') + x.toFixed(1) + ' ' + y.toFixed(1) + ' ';
    }});
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', d.trim());
    path.setAttribute('fill', 'none');
    path.setAttribute('stroke', colors[i % colors.length]);
    path.setAttribute('stroke-width', '2');
    svg.appendChild(path);
  }});
  // zero line
  const z = H - pad - ((0 - min) / span) * (H - 2 * pad);
  const zero = document.createElementNS('http://www.w3.org/2000/svg', 'line');
  zero.setAttribute('x1', pad); zero.setAttribute('x2', W - pad);
  zero.setAttribute('y1', z); zero.setAttribute('y2', z);
  zero.setAttribute('stroke', '#2a3548'); zero.setAttribute('stroke-dasharray', '4 4');
  svg.appendChild(zero);
  legend.textContent = 'Series: ' + names.join(', ') + ' (cumulative virtual P&L)';
}})();
</script>
</body>
</html>
"""


def _fmt(v: Any) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        if abs(v) >= 1000 or (abs(v) < 0.001 and v != 0):
            return f"{v:.4g}"
        return f"{v:.4f}"
    return html.escape(str(v))


def _formal_section(formal: dict[str, Any] | None) -> str:
    if not formal:
        return (
            "<h2>Formal endpoint</h2>"
            "<div class='card'><p class='muted'>No formal alpha-spending evaluation "
            "(descriptive only, or not at a checkpoint).</p></div>"
        )
    esc = html.escape
    open_ = formal.get("endpoint_open", False)
    badge = "formal" if open_ and formal.get("reject_h0") else "desc"
    rows = []
    for sid, r in (formal.get("strategies") or {}).items():
        rows.append(
            "<tr>"
            f"<td><code>{esc(sid)}</code></td>"
            f"<td class='num'>{r.get('cum_pnl', float('nan')):.2f}</td>"
            f"<td class='num'>{r.get('empirical_p', float('nan')):.4g}</td>"
            f"<td class='num'>{r.get('alpha_spent', float('nan')):.4g}</td>"
            f"<td>{'yes' if r.get('reject_h0') else 'no'}</td>"
            "</tr>"
        )
    return f"""
<h2>Formal endpoint (alpha-spending)</h2>
<div class="card">
  <p>
    <span class="badge {badge}">{'OPEN' if open_ else 'CLOSED'}</span>
    checkpoint n={formal.get('n_settled', '—')}
    · α spent = {formal.get('alpha_spent', '—')}
    · primary = <code>{esc(str(formal.get('primary_strategy') or '—'))}</code>
  </p>
  <p class="muted">{esc(formal.get('note', ''))}</p>
  <table>
    <thead><tr><th>Strategy</th><th>Cum P&amp;L</th><th>Empirical p</th><th>α</th><th>Reject H0</th></tr></thead>
    <tbody>{"".join(rows)}</tbody>
  </table>
</div>
"""


def _cum_series(settles: list[dict[str, Any]]) -> dict[str, Any]:
    cum: dict[str, float] = {}
    series: dict[str, list[float]] = {}
    for s in settles:
        for r in s.get("strategy_results", []):
            sid = r["portfolio_id"]
            cum[sid] = cum.get(sid, 0.0) + (r["payout"] - r["cost"])
            series.setdefault(sid, []).append(cum[sid])
    return {"series": [{"id": k, "values": v} for k, v in sorted(series.items())]}
