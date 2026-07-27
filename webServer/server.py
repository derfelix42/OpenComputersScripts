"""Basic FastAPI server that stores item counts posted from OpenComputers.

Run with:
    uvicorn server:app --reload --port 8000
"""

from typing import List, Optional

import datetime

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel


class Item(BaseModel):
    name: str
    label: str
    size: int


class ItemReport(BaseModel):
    total: int
    items: List[Item]


app = FastAPI(title="OpenComputers Item Dashboard")

# In-memory storage. Replaced on every POST. Not persisted across restarts.
_current_report: Optional[ItemReport] = None
_report_received_at: Optional[datetime.datetime] = None


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

<script>
async function refresh() {
  try {
    const res = await fetch('/api/rs');
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const data = await res.json();
    render(data);
  } catch (e) {
    document.getElementById('fetched').textContent = 'Fetch error: ' + e.message;
  }
}

function render(data) {
  const total = data.total || 0;
  const items = data.items || [];
  document.getElementById('total').textContent = total.toLocaleString();
  document.getElementById('types').textContent = items.length.toLocaleString();
  document.getElementById('updated').textContent = data.updated || '-';

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

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({
    '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
  }[c]));
}

refresh();
setInterval(refresh, 5000);
</script>
</body>
</html>
"""


@app.post("/api/rs")
def receive_report(report: ItemReport) -> dict:
    """Store the latest item report. Overwrites any previous data."""
    global _current_report, _report_received_at
    _current_report = report
    _report_received_at = datetime.datetime.now(datetime.timezone.utc)
    return {"status": "ok", "items": len(report.items), "total": report.total}


@app.get("/api/rs")
def get_report() -> dict:
    """Return the currently stored item report, or 404 if none yet."""
    if _current_report is None:
        raise HTTPException(status_code=404, detail="No report has been posted yet.")
    return {
        "total": _current_report.total,
        "items": [item.model_dump() for item in _current_report.items],
        "updated": _current_report_updated_iso(),
    }


@app.get("/")
def dashboard() -> str:
    """Serve the simple HTML dashboard."""
    return DASHBOARD_HTML


def _current_report_updated_iso() -> str:
    if _report_received_at is None:
        return ""
    return _report_received_at.isoformat()
