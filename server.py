from pathlib import Path
import json
import os
import re

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from playwright.async_api import async_playwright


# --------------------------------------------------
# App and file paths
# --------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="NIFTY Range Live")


# --------------------------------------------------
# Request model
# --------------------------------------------------

class Query(BaseModel):
    url: str
    support_mode: str = "Mirrored downside"


# --------------------------------------------------
# Utility functions
# --------------------------------------------------

def number(value):
    if value is None:
        return None

    try:
        return float(
            str(value)
            .replace(",", "")
            .replace("%", "")
            .strip()
        )
    except Exception:
        match = re.search(r"-?\d+(?:\.\d+)?", str(value))
        return float(match.group()) if match else None


def flatten(data):
    rows = []

    if isinstance(data, list):
        for item in data:
            rows.extend(flatten(item))

    elif isinstance(data, dict):
        keys = {
            str(key).lower().replace(" ", "_")
            for key in data
        }

        if any(
            key in keys
            for key in ("strike", "strikeprice", "strike_price")
        ):
            rows.append(data)

        for value in data.values():
            if isinstance(value, (list, dict)):
                rows.extend(flatten(value))

    return rows


def normalize(rows):
    output = []

    for row in rows:
        normalized_row = {
            str(key).lower().replace(" ", "_"): value
            for key, value in row.items()
        }

        # Flatten nested CE/PE data
        for side in ("ce", "pe", "call", "put"):
            if isinstance(normalized_row.get(side), dict):
                for key, value in normalized_row[side].items():
                    normalized_row[
                        f"{side}_{str(key).lower().replace(' ', '_')}"
                    ] = value

        def pick(*names):
            for name in names:
                if name in normalized_row:
                    return normalized_row[name]
            return None

        output.append({
            "strike": number(
                pick("strike", "strikeprice", "strike_price")
            ),
            "ce_ltp": number(
                pick(
                    "ce_ltp",
                    "ce_last_price",
                    "call_ltp",
                    "call_last_price"
                )
            ),
            "pe_ltp": number(
                pick(
                    "pe_ltp",
                    "pe_last_price",
                    "put_ltp",
                    "put_last_price"
                )
            ),
            "ce_delta": number(
                pick("ce_delta", "ce_greeks_delta", "call_delta")
            ),
            "pe_delta": number(
                pick("pe_delta", "pe_greeks_delta", "put_delta")
            ),
            "ce_volume": number(
                pick("ce_volume", "call_volume", "ce_vol", "call_vol")
            ),
            "pe_volume": number(
                pick("pe_volume", "put_volume", "pe_vol", "put_vol")
            ),
        })

    return [
        row for row in output
        if row["strike"] is not None
    ]


# --------------------------------------------------
# NIFTY option-chain scraper
# --------------------------------------------------

async def scrape(url):
    captured_data = []

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)

        page = await browser.new_page(
            viewport={"width": 1440, "height": 1000},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/140 Safari/537.36"
            )
        )

        async def on_response(response):
            content_type = response.headers.get(
                "content-type", ""
            ).lower()

            response_url = response.url.lower()

            if response.status == 200 and (
                "json" in content_type
                or any(
                    keyword in response_url
                    for keyword in (
                        "option",
                        "chain",
                        "greek",
                        "niftytrader"
                    )
                )
            ):
                try:
                    response_text = await response.text()

                    if len(response_text) < 10_000_000:
                        captured_data.append(response_text)

                except Exception:
                    pass

        page.on("response", on_response)

        try:
            await page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=40000
            )

            await page.wait_for_timeout(5000)
            await page.mouse.wheel(0, 6000)
            await page.wait_for_timeout(1500)

        finally:
            await browser.close()

    rows = []

    for response_text in captured_data:
        try:
            rows.extend(flatten(json.loads(response_text)))
        except Exception:
            pass

    return normalize(rows)


# --------------------------------------------------
# Website homepage
# --------------------------------------------------

@app.get("/")
async def index():
    index_file = STATIC_DIR / "index.html"

    if not index_file.is_file():
        return JSONResponse(
            {
                "error": "Frontend file not found",
                "expected_path": str(index_file)
            },
            status_code=500
        )

    return FileResponse(index_file)


# --------------------------------------------------
# Health check
# --------------------------------------------------

@app.get("/api/health")
async def health():
    return {"ok": True}


# --------------------------------------------------
# Support and resistance calculation
# --------------------------------------------------

@app.post("/api/range")
async def calculate(query: Query):
    try:
        data = await scrape(query.url)

        # Remove duplicate strikes
        unique_data = {
            row["strike"]: row
            for row in data
        }

        data = list(unique_data.values())

        if len(data) < 2:
            raise RuntimeError(
                "NiftyTrader data was not extracted. "
                "The site may have changed its API or blocked automated access."
            )

        # Calculate total volume for each strike
        for row in data:
            row["total_volume"] = (
                (row["ce_volume"] or 0)
                + (row["pe_volume"] or 0)
            )

        # Rank strikes by total volume
        ranked = sorted(
            data,
            key=lambda row: (
                row["total_volume"],
                row["strike"]
            ),
            reverse=True
        )

        resistance_row = ranked[0]
        support_row = ranked[1]

        # Find adjacent strikes
        higher_strike = min(
            (
                row for row in data
                if row["strike"] > resistance_row["strike"]
            ),
            key=lambda row: row["strike"],
            default=None
        )

        lower_strike = max(
            (
                row for row in data
                if row["strike"] < support_row["strike"]
            ),
            key=lambda row: row["strike"],
            default=None
        )

        if higher_strike is None or lower_strike is None:
            raise RuntimeError(
                "Required adjacent strike was not found."
            )

        # Resistance calculation
        resistance = (
            resistance_row["strike"]
            + (resistance_row["ce_ltp"] or 0)
            * (resistance_row["ce_delta"] or 0)
            + (higher_strike["pe_ltp"] or 0)
            * (higher_strike["pe_delta"] or 0)
        )

        # Support calculation
        if query.support_mode == "Literal plus":
            support = (
                support_row["strike"]
                + (support_row["pe_ltp"] or 0)
                * (support_row["pe_delta"] or 0)
                + (lower_strike["ce_ltp"] or 0)
                * (lower_strike["ce_delta"] or 0)
            )

            support_formula = (
                f"{support_row['strike']:,.0f} + "
                f"({support_row['pe_ltp']} × "
                f"{support_row['pe_delta']}) + "
                f"({lower_strike['ce_ltp']} × "
                f"{lower_strike['ce_delta']})"
            )

        else:
            support = (
                support_row["strike"]
                - (support_row["pe_ltp"] or 0)
                * abs(support_row["pe_delta"] or 0)
                - (lower_strike["ce_ltp"] or 0)
                * abs(lower_strike["ce_delta"] or 0)
            )

            support_formula = (
                f"{support_row['strike']:,.0f} − "
                f"({support_row['pe_ltp']} × "
                f"|{support_row['pe_delta']}|) − "
                f"({lower_strike['ce_ltp']} × "
                f"|{lower_strike['ce_delta']}|)"
            )

        formula = (
            f"Resistance = {resistance_row['strike']:,.0f} + "
            f"({resistance_row['ce_ltp']} × "
            f"{resistance_row['ce_delta']}) + "
            f"({higher_strike['pe_ltp']} × "
            f"{higher_strike['pe_delta']}) = "
            f"<b>{resistance:,.2f}</b><br>"
            f"Support = {support_formula} = "
            f"<b>{support:,.2f}</b>"
        )

        return {
            "support": support,
            "resistance": resistance,
            "highest_volume_strike": resistance_row["strike"],
            "second_volume_strike": support_row["strike"],
            "top": ranked[:12],
            "formula_html": formula,
            "source": "NiftyTrader browser capture"
        }

    except Exception as error:
        return JSONResponse(
            {"error": str(error)},
            status_code=502
        )


# --------------------------------------------------
# Run server
# --------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.getenv("PORT", "10000"))
    )
