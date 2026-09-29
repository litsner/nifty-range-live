const $ = id => document.getElementById(id);

const API_URL = "/api/range";
const OPTION_CHAIN_URL =
  "https://www.niftytrader.in/nse-option-chain/nifty";

function num(value) {
  if (value === null || value === undefined || value === "") return null;

  const result = Number(String(value).replace(/,/g, ""));
  return Number.isFinite(result) ? result : null;
}

function pick(object, keys) {
  for (const key of keys) {
    if (object && object[key] !== undefined && object[key] !== null) {
      return object[key];
    }
  }
  return null;
}

function format(value) {
  const result = num(value);
  return result === null ? "—" : result.toFixed(2);
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

function extract(data) {
  const root = data?.data ?? data?.result ?? data;
  const result = root?.range ?? root;

  return {
    support: pick(result, [
      "support",
      "Support",
      "support_price",
      "supportPrice"
    ]),
    resistance: pick(result, [
      "resistance",
      "Resistance",
      "resistance_price",
      "resistancePrice"
    ]),
    highest: pick(result, [
      "highest_volume_strike",
      "highestStrike",
      "highest_strike",
      "max_volume_strike"
    ]),
    second: pick(result, [
      "second_volume_strike",
      "second_highest_volume_strike",
      "secondStrike",
      "second_strike"
    ]),
    updated: pick(result, ["updated", "timestamp", "time"])
  };
}

async function load() {
  const status = $("status");
  const refreshButton = $("refreshBtn");

  status.textContent = "Fetching live NIFTY data…";
  refreshButton.disabled = true;

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

    const responseText = await response.text();

    let data;
    try {
      data = JSON.parse(responseText);
    } catch {
      throw new Error(
        responseText || `Server returned HTTP ${response.status}`
      );
    }

    if (!response.ok) {
      throw new Error(
        showError(data.detail || data.error || data)
      );
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
    status.textContent =
      "Unable to load NIFTY data: " + showError(error);

  } finally {
    refreshButton.disabled = false;
  }
}

$("refreshBtn").addEventListener("click", load);

load();
setInterval(load, 60000);
