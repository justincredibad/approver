"""Local scraper API — run this on a machine with real network access and
a real Chrome/Chromium browser, then expose it via a tunnel (ngrok,
Cloudflare Tunnel, etc.) so a GUI hosted elsewhere (e.g. Streamlit
Community Cloud, which has neither) can call out to it for live valuations.

Run with:
    pip install -e ".[server]"
    python -m credit_approver.scraper_server

Then expose it, e.g.:
    ngrok http 8800

And point the deployed app at the resulting public URL — see README.md.
"""
from __future__ import annotations

from dataclasses import asdict

from flask import Flask, jsonify, request

from credit_approver.valuation import estimate_vehicle_value, estimate_vehicle_value_by_engine_cc

app = Flask(__name__)


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.get("/valuation")
def valuation():
    make = request.args.get("make", "")
    model = request.args.get("model", "")
    year = request.args.get("year", type=int)
    if not make or not model or year is None:
        return jsonify({"error": "make, model, and year are required"}), 400

    result = estimate_vehicle_value(make, model, year, use_live_scraping=True)
    return jsonify(asdict(result))


@app.get("/valuation/by-cc")
def valuation_by_cc():
    engine_cc = request.args.get("engine_cc", type=float)
    year = request.args.get("year", type=int)
    if engine_cc is None or year is None:
        return jsonify({"error": "engine_cc and year are required"}), 400

    result = estimate_vehicle_value_by_engine_cc(engine_cc, year)
    return jsonify(asdict(result))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8800)
