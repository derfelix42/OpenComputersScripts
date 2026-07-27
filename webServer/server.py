"""Basic FastAPI server that stores item counts posted from OpenComputers.

Run with:
    uvicorn server:app --reload --host 0.0.0.0 --port 8000
"""

import datetime
import json
import sqlite3
from pathlib import Path
from typing import List

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel


class Item(BaseModel):
    name: str
    label: str
    size: int


class ItemReport(BaseModel):
    total: int
    items: List[Item]


app = FastAPI(title="OpenComputers Item Dashboard")

# Storage capacity: 4 * 8 * 65536 = 2,097,152 item slots.
STORAGE_MAX = 4 * 8 * 65536

# SQLite database next to this file.
DB_PATH = Path(__file__).resolve().parent / "data.db"


def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _init_db() -> None:
    with _get_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS current_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                total INTEGER NOT NULL,
                items_json TEXT NOT NULL,
                updated TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS history (
                ts INTEGER PRIMARY KEY,
                total INTEGER NOT NULL
            )
            """
        )


_init_db()


def _compress_history(conn: sqlite3.Connection) -> None:
    """Compress history into tiers and prune old data.

    Tiers:
      - Raw data (every POST): keep for the last 1 hour.
      - 1-minute buckets: for data between 1h and 24h old.
      - 10-minute buckets: for data between 24h and 7d old.
      - Delete anything older than 7 days.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    epoch = int(now.timestamp())
    one_hour = 3600
    one_day = 86400
    seven_days = 604800

    raw_cutoff = epoch - one_hour
    min_cutoff = epoch - one_day
    day_cutoff = epoch - seven_days

    # Compress 1h..24h into 1-minute buckets (keep the last sample of each bucket).
    conn.execute(
        """
        DELETE FROM history
        WHERE ts IN (
            SELECT ts FROM history h1
            WHERE h1.ts <= ? AND h1.ts > ?
              AND EXISTS (
                  SELECT 1 FROM history h2
                  WHERE h2.ts <= ? AND h2.ts > ?
                    AND (h2.ts / 60) = (h1.ts / 60)
                    AND h2.ts > h1.ts
              )
        )
        """,
        (raw_cutoff, min_cutoff, raw_cutoff, min_cutoff),
    )

    # Compress 24h..7d into 10-minute buckets (keep the last sample of each bucket).
    conn.execute(
        """
        DELETE FROM history
        WHERE ts IN (
            SELECT ts FROM history h1
            WHERE h1.ts <= ? AND h1.ts > ?
              AND EXISTS (
                  SELECT 1 FROM history h2
                  WHERE h2.ts <= ? AND h2.ts > ?
                    AND (h2.ts / 600) = (h1.ts / 600)
                    AND h2.ts > h1.ts
              )
        )
        """,
        (min_cutoff, day_cutoff, min_cutoff, day_cutoff),
    )

    # Delete anything older than 7 days.
    conn.execute("DELETE FROM history WHERE ts <= ?", (day_cutoff,))


DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Item Dashboard</title>
<style>
  :root { color-scheme: light dark; }
  body {
    font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
    margin: 0; padding: 1.5rem; background: #f7f7f9;
  }
  h1 { margin-top: 0; }
  .summary {
    display: flex; gap: 1rem; flex-wrap: wrap; margin-bottom: 1.5rem;
  }
  .card {
    background: #fff; border: 1px solid #e3e3e8; border-radius: 8px;
    padding: 1rem 1.25rem; min-width: 160px; box-shadow: 0 1px 2px rgba(0,0,0,0.04);
  }
  .card .label { color: #6b7280; font-size: 0.8rem; text-transform: uppercase; }
  .card .value { font-size: 1.5rem; font-weight: 600; margin-top: 0.25rem; }
  table {
    width: 100%; border-collapse: collapse; background: #fff;
    border: 1px solid #e3e3e8; border-radius: 8px; overflow: hidden;
  }
  th, td { text-align: left; padding: 0.6rem 1rem; border-bottom: 1px solid #eee; }
  th { background: #fafafa; font-size: 0.85rem; text-transform: uppercase; color: #6b7280; }
  tr:last-child td { border-bottom: none; }
  .empty { color: #6b7280; }
  .updated { color: #6b7280; font-size: 0.85rem; margin-top: 1rem; }
  .bar {
    height: 6px; background: #eef; border-radius: 3px; margin-top: 4px; overflow: hidden;
  }
  .bar > span { display: block; height: 100%; background: #6366f1; }
  .fill-bar {
    height: 10px; background: #eef; border-radius: 5px; margin-top: 6px; overflow: hidden;
  }
  .fill-bar > span { display: block; height: 100%; background: #22c55e; transition: width 0.3s; }
  .chart-card {
    background: #fff; border: 1px solid #e3e3e8; border-radius: 8px;
    padding: 1rem 1.25rem; margin-bottom: 1.5rem; box-shadow: 0 1px 2px rgba(0,0,0,0.04);
  }
  .chart-card h2 { margin: 0 0 0.75rem; font-size: 1rem; text-transform: uppercase; color: #6b7280; }
  .chart-wrap { position: relative; height: 240px; }
  .range-buttons { display: flex; gap: 0.5rem; margin-bottom: 0.75rem; }
  .range-buttons button {
    border: 1px solid #d1d5db; background: #fff; border-radius: 6px;
    padding: 0.3rem 0.8rem; cursor: pointer; font-size: 0.85rem;
  }
  .range-buttons button.active {
    background: #6366f1; color: #fff; border-color: #6366f1;
  }
</style>
</head>
<body>
  <h1>Item Dashboard</h1>
  <div class="summary">
    <div class="card">
      <div class="label">Total Items</div>
      <div class="value" id="total">-</div>
    </div>
    <div class="card">
      <div class="label">Distinct Types</div>
      <div class="value" id="types">-</div>
    </div>
    <div class="card">
      <div class="label">Last Update</div>
      <div class="value" id="updated">-</div>
    </div>
    <div class="card">
      <div class="label">Storage Fill</div>
      <div class="value" id="fill">-</div>
      <div class="fill-bar"><span id="fill-bar" style="width:0%"></span></div>
    </div>
  </div>
  <div class="chart-card">
    <h2>Total Items Over Time</h2>
    <div class="range-buttons">
      <button data-range="1h">1h</button>
      <button data-range="24h" class="active">24h</button>
      <button data-range="7d">7d</button>
    </div>
    <div class="chart-wrap"><canvas id="historyChart"></canvas></div>
  </div>
  <table>
    <thead>
      <tr><th>Label</th><th>Name</th><th>Size</th><th>Share</th></tr>
    </thead>
    <tbody id="rows">
      <tr><td colspan="4" class="empty">Waiting for data...</td></tr>
    </tbody>
  </table>
  <div class="updated" id="fetched"></div>

<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<script>
let historyChart = null;
let currentRange = '24h';

function formatDateTime(iso) {
  if (!iso) return '-';
  const d = new Date(iso);
  const pad = n => String(n).padStart(2, '0');
  return pad(d.getDate()) + '.' + pad(d.getMonth() + 1) + '.' + d.getFullYear()
    + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds());
}

async function refresh() {
  try {
    const res = await fetch('/api/rs');
    if (res.status === 404) {
      document.getElementById('fetched').textContent = 'No data posted yet.';
      return;
    }
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const data = await res.json();
    render(data);
    refreshHistory();
  } catch (e) {
    document.getElementById('fetched').textContent = 'Fetch error: ' + e.message;
  }
}

function render(data) {
  const total = data.total || 0;
  const items = data.items || [];
  document.getElementById('total').textContent = total.toLocaleString();
  document.getElementById('types').textContent = items.length.toLocaleString();
  document.getElementById('updated').textContent = formatDateTime(data.updated);
  const storageMax = data.storage_max || 1;
  const fillPct = data.fill_percent != null ? data.fill_percent : (total / storageMax * 100);
  document.getElementById('fill').textContent = fillPct.toFixed(2) + '%';
  document.getElementById('fill-bar').style.width = Math.min(100, fillPct) + '%';

  const rows = document.getElementById('rows');
  if (items.length === 0) {
    rows.innerHTML = '<tr><td colspan="4" class="empty">No items reported.</td></tr>';
    return;
  }
  rows.innerHTML = items.map(it => {
    const share = total > 0 ? (it.size / total * 100).toFixed(1) : '0.0';
    const width = total > 0 ? Math.max(1, it.size / total * 100) : 0;
    return `<tr>
      <td>${escapeHtml(it.label)}</td>
      <td><code>${escapeHtml(it.name)}</code></td>
      <td>${it.size.toLocaleString()}</td>
      <td>${share}%
        <div class="bar"><span style="width:${width}%"></span></div>
      </td>
    </tr>`;
  }).join('');
  document.getElementById('fetched').textContent = 'Updated ' + new Date().toLocaleTimeString();
}

async function refreshHistory() {
  try {
    const res = await fetch('/api/history?range=' + encodeURIComponent(currentRange));
    if (!res.ok) return;
    const data = await res.json();
    renderChart(data.points || []);
  } catch (e) { /* ignore chart errors */ }
}

function renderChart(points) {
  const labels = points.map(p => formatDateTime(p.t));
  const totals = points.map(p => p.total);
  const ctx = document.getElementById('historyChart').getContext('2d');
  if (historyChart) {
    historyChart.data.labels = labels;
    historyChart.data.datasets[0].data = totals;
    historyChart.update('none');
    return;
  }
  historyChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: labels,
      datasets: [{
        label: 'Total Items',
        data: totals,
        borderColor: '#6366f1',
        backgroundColor: 'rgba(99,102,241,0.1)',
        fill: true,
        tension: 0.3,
        pointRadius: 2,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        y: { beginAtZero: true },
        x: { ticks: { maxTicksLimit: 8 } }
      },
      plugins: { legend: { display: false } }
    }
  });
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({
    '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
  }[c]));
}

document.querySelectorAll('.range-buttons button').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.range-buttons button').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    currentRange = btn.dataset.range;
    refreshHistory();
  });
});

refresh();
setInterval(refresh, 5000);
</script>
</body>
</html>
"""


@app.post("/api/rs")
def receive_report(report: ItemReport) -> dict:
    """Store the latest item report. Overwrites any previous data."""
    now = datetime.datetime.now(datetime.timezone.utc)
    now_iso = now.isoformat()
    now_epoch = int(now.timestamp())
    items_json = json.dumps([item.model_dump() for item in report.items])

    with _get_db() as conn:
        conn.execute(
            """
            INSERT INTO current_state (id, total, items_json, updated)
            VALUES (1, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                total = excluded.total,
                items_json = excluded.items_json,
                updated = excluded.updated
            """,
            (report.total, items_json, now_iso),
        )
        conn.execute(
            "INSERT OR REPLACE INTO history (ts, total) VALUES (?, ?)",
            (now_epoch, report.total),
        )
        _compress_history(conn)

    return {"status": "ok", "items": len(report.items), "total": report.total}


@app.get("/api/rs")
def get_report() -> dict:
    """Return the currently stored item report, or 404 if none yet."""
    with _get_db() as conn:
        row = conn.execute("SELECT total, items_json, updated FROM current_state WHERE id = 1").fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="No report has been posted yet.")
    items = json.loads(row["items_json"])
    return {
        "total": row["total"],
        "items": items,
        "updated": row["updated"],
        "fill_percent": round(row["total"] / STORAGE_MAX * 100, 2),
        "storage_max": STORAGE_MAX,
    }


@app.get("/api/history")
def get_history(range: str = Query("24h", pattern="^(1h|24h|7d)$")) -> dict:
    """Return history points for the requested time range."""
    now = datetime.datetime.now(datetime.timezone.utc)
    epoch = int(now.timestamp())
    cutoffs = {"1h": 3600, "24h": 86400, "7d": 604800}
    cutoff = epoch - cutoffs[range]

    with _get_db() as conn:
        rows = conn.execute(
            "SELECT ts, total FROM history WHERE ts > ? ORDER BY ts ASC",
            (cutoff,),
        ).fetchall()

    points = [{"t": datetime.datetime.fromtimestamp(r["ts"], tz=datetime.timezone.utc).isoformat(), "total": r["total"]} for r in rows]
    return {"points": points, "storage_max": STORAGE_MAX}


@app.get("/")
def dashboard() -> HTMLResponse:
    """Serve the simple HTML dashboard."""
    return HTMLResponse(content=DASHBOARD_HTML)
