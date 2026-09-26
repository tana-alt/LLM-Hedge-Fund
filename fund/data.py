"""Allowlisted retrieval. Raw snapshots stay outside the public repository."""
import json
import os
import ssl
import urllib.request
import re
from datetime import date, datetime, timezone
from pathlib import Path

import yfinance as yf
import certifi
from bs4 import BeautifulSoup

from .common import PRIVATE, config, digest, save, utc_now


def sec_user_agent():
    value = os.environ.get("SEC_USER_AGENT")
    if not value:
        env = Path(__file__).resolve().parents[1] / ".env"
        if env.exists():
            for line in env.read_text().splitlines():
                if line.startswith("SEC_USER_AGENT="):
                    value = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not value or "@" not in value or "example.com" in value:
        raise RuntimeError("SEC_USER_AGENT must identify a real contact address in local .env")
    return value


def fetch_sec(url):
    cfg = config()
    if url not in cfg["sec_api"]:
        raise ValueError("URL outside frozen SEC allowlist")
    req = urllib.request.Request(url, headers={"User-Agent": sec_user_agent(), "Accept-Encoding": "identity"})
    with urllib.request.urlopen(req, timeout=30, context=ssl.create_default_context(cafile=certifi.where())) as response:
        if response.geturl() != url:
            raise RuntimeError("SEC redirect outside exact URL allowlist")
        body = response.read(25_000_000)
    return json.loads(body)


def sec_snapshot(decision_date, snapshot_id=None):
    cfg = config()
    folder = PRIVATE / "sources" / (snapshot_id or decision_date)
    folder.mkdir(parents=True, exist_ok=True)
    out = {}
    for url, name in zip(cfg["sec_api"], ("submissions", "companyfacts")):
        payload = fetch_sec(url)
        obj = {"source_url": url, "retrieved_at": utc_now(), "sha256": digest(payload), "data": payload}
        save(folder / f"{name}.json", obj)
        out[name] = obj
    return out


def price_snapshot(decision_date, symbol="COST", snapshot_id=None):
    if symbol not in ("COST", "SPY"):
        raise ValueError("symbol outside price allowlist")
    cfg = config()["price"]
    frame = yf.Ticker(symbol).history(period="3mo", interval=cfg["interval"], auto_adjust=cfg["auto_adjust"], actions=cfg["actions"], repair=cfg["repair"])
    if frame.empty:
        raise RuntimeError("empty yfinance response")
    rows = []
    for idx, row in frame.iterrows():
        d = idx.date().isoformat()
        if d >= decision_date:
            continue
        x = {"date": d}
        for key in ("Open", "High", "Low", "Close", "Adj Close", "Volume", "Dividends", "Stock Splits"):
            x[key] = float(row.get(key, 0))
        if not (x["Low"] <= min(x["Open"], x["Close"]) <= max(x["Open"], x["Close"]) <= x["High"] and x["Volume"] >= 0):
            raise RuntimeError(f"invalid OHLCV {symbol} {d}")
        rows.append(x)
    if not rows:
        raise RuntimeError("no prior trading session")
    obj = {"source": "yfinance", "library_version": yf.__version__, "symbol": symbol, "retrieved_at": utc_now(), "parameters": cfg, "rows": rows, "sha256": digest(rows)}
    save(PRIVATE / "sources" / (snapshot_id or decision_date) / f"{symbol.lower()}_prices.json", obj)
    return obj


def recent_filings(submissions, cutoff_date):
    recent = submissions["data"]["filings"]["recent"]
    wanted = set(config()["alerts"]["new_forms"])
    records = []
    for i, form in enumerate(recent["form"]):
        if form not in wanted:
            continue
        filed = recent["filingDate"][i]
        # Date-only conservative guard; same-day filings are excluded before 09:00 ET.
        if filed >= cutoff_date:
            continue
        accession = recent["accessionNumber"][i]
        records.append({"form": form, "filed": filed, "accession": accession, "primary_document": recent["primaryDocument"][i], "url": config()["sec_archive_prefix"] + accession.replace("-", "") + "/" + recent["primaryDocument"][i]})
    return records[:30]


def fetch_8k_exhibit(filing, snapshot_id, name):
    """Read only the EX-99.1 attachment of a discovered 8-K accession."""
    prefix = config()["sec_archive_prefix"] + filing["accession"].replace("-", "") + "/"
    def get(url):
        if not url.startswith(prefix) or not re.fullmatch(r"[a-zA-Z0-9_.-]+", url[len(prefix):]):
            raise ValueError("archive URL outside accession attachment allowlist")
        req = urllib.request.Request(url, headers={"User-Agent": sec_user_agent()})
        with urllib.request.urlopen(req, timeout=30, context=ssl.create_default_context(cafile=certifi.where())) as response:
            if response.geturl() != url:
                raise RuntimeError("archive redirect")
            return response.read(5_000_000)
    index = json.loads(get(prefix + "index.json"))
    names = [x["name"] for x in index["directory"]["item"]]
    exhibits = [n for n in names if re.match(r"costex991.*\.htm$", n, re.I)]
    if not exhibits:
        return {"filing": filing, "error": "EX-99.1 not found"}
    url = prefix + exhibits[0]
    html = get(url)
    body = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    obj = {"filing": filing, "source_url": url, "retrieved_at": utc_now(), "sha256": __import__("hashlib").sha256(html).hexdigest(), "text": body}
    save(PRIVATE / "sources" / snapshot_id / name, obj)
    return obj


def latest_exhibits(submissions, cutoff_date, snapshot_id):
    filings=[f for f in recent_filings(submissions,cutoff_date) if f["form"]=="8-K"]
    latest=None
    earnings=None
    for i,filing in enumerate(filings[:12]):
        exhibit=fetch_8k_exhibit(filing,snapshot_id,f"exhibit_{i}.json")
        if i==0: latest=exhibit
        if exhibit and "text" in exhibit:
            body=exhibit["text"]
            if re.search(r"FISCAL YEAR 20\d{2} OPERATING RESULTS",body,re.I) and "52 Weeks Ended" in body and "Net cash provided by operating activities" in body:
                earnings=exhibit
                break
    return latest,earnings


TAGS = {
    "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet", "Revenues"],
    "operating_income": ["OperatingIncomeLoss"],
    "net_income": ["NetIncomeLoss"],
    "cfo": ["NetCashProvidedByUsedInOperatingActivities"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment"],
    "da": ["DepreciationDepletionAndAmortization", "DepreciationDepletionAndAmortizationPropertyPlantAndEquipment"],
    "interest": ["InterestExpenseNonOperating", "InterestExpense"],
    "tax": ["IncomeTaxExpenseBenefit"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue"],
    "debt_current": ["LongTermDebtCurrent"],
    "debt_long": ["LongTermDebtNoncurrent", "LongTermDebt"],
    "shares": ["CommonStockSharesOutstanding", "WeightedAverageNumberOfDilutedSharesOutstanding"]
}
INSTANT = {"cash", "debt_current", "debt_long", "shares"}


def extract_fact(facts, names, fy, cutoff, instant=False):
    matches = []
    for tag in names:
        node = facts.get("us-gaap", {}).get(tag, {})
        units = node.get("units", {})
        unit = "shares" if tag.endswith("SharesOutstanding") else "USD"
        for item in units.get(unit, []):
            if item.get("form") not in ("10-K", "10-K/A") or item.get("filed", "9999") >= cutoff:
                continue
            if item.get("fy") != fy or item.get("fp") != "FY":
                continue
            if not instant:
                start, end = item.get("start"), item.get("end")
                if not start or not end or (date.fromisoformat(end) - date.fromisoformat(start)).days < 330:
                    continue
            matches.append((item.get("filed"), item.get("end"), -names.index(tag), item, tag, unit))
    if not matches:
        return None
    _, _, _, item, tag, unit = max(matches, key=lambda t: t[:3])
    return {"value": item["val"], "unit": unit, "tag": tag, "start": item.get("start"), "end": item.get("end"), "filed": item["filed"], "accession": item.get("accn"), "form": item["form"], "source": "SEC companyfacts"}


def fact_ledger(companyfacts, cutoff):
    facts = companyfacts["data"]["facts"]
    years = set()
    for node in facts.get("us-gaap", {}).values():
        for unitrows in node.get("units", {}).values():
            for item in unitrows:
                if item.get("form") == "10-K" and item.get("filed", "9999") < cutoff and item.get("fp") == "FY":
                    years.add(item.get("fy"))
    years = sorted(y for y in years if isinstance(y, int))[-6:]
    ledger = {}
    for fy in years:
        ledger[str(fy)] = {key: extract_fact(facts, tags, fy, cutoff, key in INSTANT) for key, tags in TAGS.items()}
    return {"source_id": companyfacts["sha256"], "source_url": companyfacts["source_url"], "cutoff_date_exclusive": cutoff, "fiscal_years": ledger}
