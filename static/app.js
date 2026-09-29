const $ = id => document.getElementById(id);

const API_URL = "/api/range";
const OPTION_CHAIN_URL =
  "https://www.niftytrader.in/nse-option-chain/nifty";

function num(v) {
  if (v === null || v === undefined || v === "") return null;

  const n = Number(String(v).replace(/,/g, ""));
  return Number.isFinite(n) ? n : null;
}

function pick(obj, keys) {
  for (const k of keys) {
    if (obj && obj[k] !== undefined && obj[k] !== null) {
      return obj[k];
    }
  }
  return null;
}

function format(v) {
  const n = num(v);
  return n === null ? "—" : n.toFixed(2);
}

function extract(data) {
  const root = data?.data ?? data?.result ?? data;
  const r = root?.range ?? root;

  return {
    support: pick(r, [
      "support",
      "Support",
      "support_price",
      "supportPrice"
    ]),
    resistance: pick(r, [
      "resistance",
      "Resistance",
      "resistance_price",
      "resistancePrice"
    ]),
    highest: pick(r, [
      "highest_volume_strike",
      "highestStrike",
      "highest_strike",
      "max_volume_strike"
    ]),
    second: pick(r, [
      "second_volume_strike",
      "second_highest_volume_strike",
      "secondStrike",
      "second_strike"
    ]),
    updated: pick(r, [
      "updated",
      "timestamp",
      "time"
    ])
  };
}

function showError(error) {
  if (typeof error === "string") return error;

  if (Array.isArray(error)) {
    return error
      .map(item => item.msg || JSON.stringify(item))
      .join("; ");
  }

  if (error && typeof error === "object") {
    return error.message || error.error || JSON.stringify(error);
  }

  return String(error);
}

async function load() {
  const status = $("status");
  const refreshBtn = $("refreshBtn");

  status.textContent = "Fetching live NIFTY data…";
  refreshBtn.disabled = true;

  try {
    const response = await fetch(API_URL, {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        url: OPTION_CHAIN_URL,
        support_mode: "Mirrored downside"
      })
    });

    const text = await response.text();

    let data;
    try {
      data = JSON.parse(text);
    } catch {
      throw new Error(text || `Server returned HTTP ${response.status}`);
    }

    if (!response.ok) {
      throw new Error(showError(data.detail || data.error || data));
    }

    const result = extract(data);

    $("support").textContent = format(result.support);
    $("resistance").textContent = format(result.resistance);
    $("highestStrike").textContent = result.highest ?? "—";
    $("secondStrike").textContent = result.second ?? "—";
    $("updated").textContent = result.updated
      ? String(result.updated)
      : new Date().toLocaleTimeString();

    status.textContent = "Live data loaded successfully.";

  } catch (error) {
    console.error("NIFTY API error:", error);
    status.textContent = "Unable to load NIFTY data: " + showError(error);

  } finally {
    refreshBtn.disabled = false;
  }
}

$("refreshBtn").addEventListener("click", load);

load();

// Refresh every 60 seconds
setInterval(load, 60000);
