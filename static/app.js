const $ = id => document.getElementById(id);

function num(v) {
  if (v === null || v === undefined || v === '') return null;
  const n = Number(String(v).replace(/,/g, ''));
  return Number.isFinite(n) ? n : null;
}
function pick(obj, keys) {
  for (const k of keys) {
    if (obj && obj[k] !== undefined && obj[k] !== null) return obj[k];
  }
  return null;
}
function format(v) {
  const n = num(v);
  return n === null ? '—' : n.toFixed(2);
}
function extract(data) {
  const root = data?.data ?? data?.result ?? data;
  const r = root?.range ?? root;
  return {
    support: pick(r, ['support','Support','support_price','supportPrice']),
    resistance: pick(r, ['resistance','Resistance','resistance_price','resistancePrice']),
    highest: pick(r, ['highest_volume_strike','highestStrike','highest_strike','max_volume_strike']),
    second: pick(r, ['second_highest_volume_strike','secondStrike','second_strike']),
    updated: pick(r, ['updated','timestamp','time'])
  };
}

async function load() {
  $('status').textContent = 'Fetching live data…';
  try {
    // The deployed API is POST-only, so a normal browser GET to /api/range returns 405.
    const res = await fetch('/api/range', {method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'});
    const text = await res.text();
    let data;
    try { data = JSON.parse(text); } catch { throw new Error(text || `HTTP ${res.status}`); }
    if (!res.ok) throw new Error(data.detail || data.error || `HTTP ${res.status}`);
    const x = extract(data);
    $('support').textContent = format(x.support);
    $('resistance').textContent = format(x.resistance);
    $('highestStrike').textContent = x.highest ?? '—';
    $('secondStrike').textContent = x.second ?? '—';
    $('updated').textContent = x.updated ? String(x.updated) : new Date().toLocaleTimeString();
    $('status').textContent = 'Live data loaded successfully.';
  } catch (e) {
    console.error(e);
    $('status').textContent = 'Unable to load NIFTY data: ' + e.message;
  }
}
$('refreshBtn').addEventListener('click', load);
load();
setInterval(load, 60000);
