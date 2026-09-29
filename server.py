from pathlib import Path
import json
import os
import re

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from playwright.async_api import async_playwright


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
INDEX_FILE = STATIC_DIR / "index.html"

app = FastAPI(title="NIFTY Range Live")

# Serve CSS and JavaScript from the static folder.
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


class Query(BaseModel):
    url: str
    support_mode: str = "Mirrored downside"


def number(value):
    if value is None:
        return None

    try:
        return float(str(value).replace(",", "").replace("%", "").strip())
    except (ValueError, TypeError):
        match = re.search(r"-?\d+(?:\.\d+)?", str(value))
        return float(match.group()) if match else None


def flatten(value):
    rows = []

    if isinstance(value, list):
        for item in value:
            rows.extend(flatten(item))

    elif isinstance(value, dict):
        keys = {
            str(key).lower().replace(" ", "_")
            for key in value
        }

        if any(
            key in keys
            for key in ("strike", "strikeprice", "strike_price")
        ):
            rows.append(value)

        for item in value.values():
            if isinstance(item, (list, dict)):
                rows.extend(flatten(item))

    return rows


def normalize(rows):
    output = []

    for row in rows:
        normalized = {
            str(key).lower().replace(" ", "_"): value
            for key, value in row.items()
        }

        for side in ("ce", "pe", "call", "put"):
            side_data = normalized.get(side)

            if isinstance(side_data, dict):
                for key, value in side_data.items():
                    normalized[
                        f"{side}_{str(key).lower().replace(' ', '_')}"
                    ] = value

        def pick_value(*names):
            for name in names:
                if name in normalized:
                    return normalized[name]
            return None

        output.append({
            "strike": number(pick_value(
                "strike",
                "strikeprice",
                "strike_price"
            )),
            "ce_ltp": number(pick_value(
                "ce_ltp",
                "ce_last_price",
                "call_ltp",
                "call_last_price"
            )),
            "pe_ltp": number(pick_value(
                "pe_ltp",
                "pe_last_price",
                "put_ltp",
                "put_last_price"
            )),
            "ce_delta": number(pick_value(
                "ce_delta",
                "ce_greeks_delta",
                "call_delta"
            )),
            "pe_delta": number(pick_value(
                "pe_delta",
                "pe_greeks_delta",
                "put_delta"
            )),
            "ce_volume": number(pick_value(
                "ce_volume",
                "call_volume",
                "ce_vol",
                "call_vol"
            )),
            "pe_volume": number(pick_value(
                "pe_volume",
                "put_volume",
                "pe_vol",
                "put_vol"
            ))
        })

    return [
        row for row in output
        if row["strike"] is not None
    ]


async def scrape(url):
    captured = []

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)

        page = await browser.new_page(
            viewport={"width": 1440, "height": 1000},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/140 Safari/537.36"
            )
        )

        async def capture_response(response):
            content_type = response.headers.get(
                "content-type", ""
            ).lower()
            response_url = response.url.lower()

            relevant = (
                "json" in content_type
                or any(
                    word in response_url
                    for word in ("option", "chain", "greek", "niftytrader")
                )
            )

            if response.status == 200 and relevant:
                try:
                    text = await response.text()
                    if len(text) < 10_000_000:
                        captured.append(text)
                except Exception:
                    pass

        page.on("response", capture_response)

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

    for text in captured:
        try:
            rows.extend(flatten(json.loads(text)))
        except (json.JSONDecodeError, TypeError):
            pass

    return normalize(rows)


@app.get("/")
async def index():
    if not INDEX_FILE.is_file():
        return JSONResponse(
            {
                "error": "static/index.html was not found",
                "expected_path": str(INDEX_FILE)
            },
            status_code=500
        )

    return FileResponse(str(INDEX_FILE))


@app.get("/api/health")
async def health():
    return {
        "ok": True,
        "static_folder_exists": STATIC_DIR.is_dir(),
        "index_file_exists": INDEX_FILE.is_file()
    }


@app.post("/api/range")
async def calculate(query: Query):
    try:
        data = await scrape(query.url)

        unique_rows = {
            row["strike"]: row
            for row in data
        }
        data = list(unique_rows.values())

        if len(data) < 2:
            raise RuntimeError(
                "NIFTY option-chain data could not be extracted. "
                "The source website may have changed or blocked access."
            )

        for row in data:
            row["total_volume"] = (
                (row["ce_volume"] or 0)
                + (row["pe_volume"] or 0)
            )

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

        higher = min(
            (
                row for row in data
                if row["strike"] > resistance_row["strike"]
            ),
            key=lambda row: row["strike"],
            default=None
        )

        lower = max(
            (
                row for row in data
                if row["strike"] < support_row["strike"]
            ),
            key=lambda row: row["strike"],
            default=None
        )

        if higher is None or lower is None:
            raise RuntimeError(
                "The adjacent strike data required for the calculation "
                "was not found."
            )

        resistance = (
            resistance_row["strike"]
            + (resistance_row["ce_ltp"] or 0)
            * (resistance_row["ce_delta"] or 0)
            + (higher["pe_ltp"] or 0)
            * (higher["pe_delta"] or 0)
        )

        if query.support_mode == "Literal plus":
            support = (
                support_row["strike"]
                + (support_row["pe_ltp"] or 0)
                * (support_row["pe_delta"] or 0)
                + (lower["ce_ltp"] or 0)
                * (lower["ce_delta"] or 0)
            )
        else:
            support = (
                support_row["strike"]
                - (support_row["pe_ltp"] or 0)
                * abs(support_row["pe_delta"] or 0)
                - (lower["ce_ltp"] or 0)
                * abs(lower["ce_delta"] or 0)
            )

        return {
            "support": support,
            "resistance": resistance,
            "highest_volume_strike": resistance_row["strike"],
            "second_volume_strike": support_row["strike"],
            "top": ranked[:12],
            "updated": None,
            "source": "NiftyTrader browser capture"
        }

    except Exception as error:
        return JSONResponse(
            {"error": str(error)},
            status_code=502
        )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.getenv("PORT", "10000"))
    )
