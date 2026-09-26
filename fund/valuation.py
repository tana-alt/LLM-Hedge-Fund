"""Deterministic financial math; model outputs are proposals, never arithmetic authority."""
import math
import re


def release_facts(release):
    if not release or "text" not in release:
        return {}
    text = release["text"]
    fiscal_match=re.search(r"FISCAL YEAR (20\d{2}) OPERATING RESULTS",text,re.I)
    fiscal_year=int(fiscal_match.group(1)) if fiscal_match else None
    patterns = {
        "revenue": r"Total revenue\s+[\d,]+\s+[\d,]+\s+([\d,]+)",
        "operating_income": r"Operating income\s+[\d,]+\s+[\d,]+\s+([\d,]+)",
        "net_income": r"NET INCOME\s+\$\s+[\d,]+\s+\$\s+[\d,]+\s+\$\s+([\d,]+)",
        "cfo": r"Net cash provided by operating activities\s+([\d,]+)",
        "capex": r"Additions to property and equipment\s+\(([\d,]+)\)",
        "da": r"Depreciation and amortization\s+([\d,]+)",
        "interest": r"Interest expense\s+\([\d,]+\)\s+\([\d,]+\)\s+\(([\d,]+)\)",
        "tax": r"Provision for income taxes\s+[\d,]+\s+[\d,]+\s+([\d,]+)",
        "cash": r"Cash and cash equivalents\s+\$\s+([\d,]+)\s+\$\s+[\d,]+",
        "debt_current": r"Current portion of long-term debt\s+([\d,]+)",
        "debt_long": r"Long-term debt, excluding current portion\s+([\d,]+)",
        "shares": r"Shares used in calculation \(000's\): Basic\s+[\d,]+\s+[\d,]+\s+[\d,]+\s+[\d,]+\s+Diluted\s+[\d,]+\s+[\d,]+\s+([\d,]+)"
    }
    found = {}
    for key, pattern in patterns.items():
        m = re.search(pattern, text, re.I)
        if m:
            scale = 1_000 if key == "shares" else 1_000_000
            found[key] = {"value": int(m.group(1).replace(",", "")) * scale, "unit": "shares" if key == "shares" else "USD", "source": release["source_url"], "source_id": release["sha256"], "filed": release["filing"]["filed"], "fiscal_year":fiscal_year, "period": f"FY{fiscal_year} unaudited" if fiscal_year else "unaudited fiscal release", "quote_context": text[max(0, m.start()-40):m.end()+50]}
    return found


def historical_bridge(ledger, preliminary=None):
    rows = {}
    for fy, raw in ledger["fiscal_years"].items():
        vals = {k: (v["value"] if v else None) for k, v in raw.items()}
        rows[fy] = _bridge(vals)
    release_fy=preliminary.get("revenue",{}).get("fiscal_year") if preliminary else None
    if release_fy and str(release_fy) not in rows and all(k in preliminary for k in ("revenue", "operating_income", "cfo", "capex", "interest", "tax", "net_income", "cash", "debt_current", "debt_long", "shares")):
        rows[f"{release_fy}_preliminary"] = _bridge({k: v["value"] for k, v in preliminary.items()})
    return rows


def _bridge(x):
    result = dict(x)
    needed = ("cfo", "capex", "interest", "tax", "net_income")
    if all(x.get(k) is not None for k in needed):
        tax_rate = x["tax"] / (x["tax"] + x["net_income"])
        result["tax_rate_proxy"] = tax_rate
        result["fcf_equity_proxy"] = x["cfo"] - x["capex"]
        result["fcff_cfo_bridge"] = x["cfo"] - x["capex"] + x["interest"] * (1-tax_rate)
    return result


def validate_assumptions(a):
    for key in ("sales_growth", "ebit_margin", "tax_rate", "da_sales", "capex_sales", "nwc_investment_sales", "wacc", "terminal_growth"):
        if key not in a or not isinstance(a[key], (int,float)) or not math.isfinite(a[key]):
            raise ValueError(f"missing/non-numeric assumption {key}")
    bounds = {"sales_growth": (-.10,.30), "ebit_margin": (0,.20), "tax_rate": (0,.50), "da_sales": (0,.10), "capex_sales": (0,.15), "nwc_investment_sales": (-.05,.10), "wacc": (.04,.20), "terminal_growth": (-.02,.05)}
    for key,(lo,hi) in bounds.items():
        if not lo <= a[key] <= hi:
            raise ValueError(f"out-of-range assumption {key}={a[key]}")
    if a["terminal_growth"] >= a["wacc"] - .01:
        raise ValueError("terminal growth too near WACC")


def dcf(base, assumptions):
    validate_assumptions(assumptions)
    revenue = base["revenue"]
    cashflows = []
    for year in range(1, 6):
        revenue *= 1 + assumptions["sales_growth"]
        ebit = revenue * assumptions["ebit_margin"]
        da = revenue * assumptions["da_sales"]
        capex = revenue * assumptions["capex_sales"]
        delta_nwc = revenue * assumptions["nwc_investment_sales"]
        fcff = ebit*(1-assumptions["tax_rate"]) + da - capex - delta_nwc
        cashflows.append({"year": year, "revenue": revenue, "ebit": ebit, "da": da, "capex": capex, "delta_nwc": delta_nwc, "fcff": fcff, "pv_fcff": fcff/(1+assumptions["wacc"])**year})
    w, g = assumptions["wacc"], assumptions["terminal_growth"]
    terminal = cashflows[-1]["fcff"]*(1+g)/(w-g)
    pv_terminal = terminal/(1+w)**5
    ev = sum(x["pv_fcff"] for x in cashflows)+pv_terminal
    net_debt = base["debt_current"]+base["debt_long"]-base["cash"]
    equity = ev-net_debt
    return {"forecast": cashflows, "terminal_value": terminal, "pv_terminal": pv_terminal, "terminal_share_of_ev": pv_terminal/ev if ev else None, "enterprise_value": ev, "net_debt": net_debt, "equity_value": equity, "per_share": equity/base["shares"]}


def reverse_growth(base, a, market_price):
    fcff_sales=a["ebit_margin"]*(1-a["tax_rate"])+a["da_sales"]-a["capex_sales"]-a["nwc_investment_sales"]
    low_value=dcf(base,{**a,"sales_growth":-.10})["per_share"]
    high_value=dcf(base,{**a,"sales_growth":.30})["per_share"]
    if fcff_sales<=0:
        return {"sales_growth_implied":None,"model_price_at_bound_low":low_value,"model_price_at_bound_high":high_value,"within_bounds":False,"undefined_reason":"nonpositive forecast FCFF margin; growth inverse lacks economic meaning"}
    lo, hi = -.10, .30
    for _ in range(60):
        mid=(lo+hi)/2
        value=dcf(base, {**a,"sales_growth":mid})["per_share"]
        if value < market_price: lo=mid
        else: hi=mid
    return {"sales_growth_implied":(lo+hi)/2, "model_price_at_bound_low":low_value, "model_price_at_bound_high":high_value, "within_bounds":low_value <= market_price <= high_value}


def build_valuation(bridge, assumptions, close):
    base_key=max(bridge,key=lambda key:(int(key[:4]),0 if "preliminary" in key else 1))
    base = bridge[base_key]
    if not all(base.get(k) and base[k]>0 for k in ("revenue","cash","shares")) or base.get("debt_long") is None or base.get("debt_current") is None:
        raise ValueError("missing balance-sheet valuation inputs")
    cases={case:dcf(base, a) for case,a in assumptions.items()}
    base_a=assumptions["base"]
    sensitivity={f"wacc_{w:.3f}_g_{g:.3f}":dcf(base,{**base_a,"wacc":w,"terminal_growth":g})["per_share"] for w in (base_a["wacc"]-.01,base_a["wacc"],base_a["wacc"]+.01) for g in (base_a["terminal_growth"]-.005,base_a["terminal_growth"],base_a["terminal_growth"]+.005) if .04<=w<=.20 and -.02<=g<=.05 and g < w-.01}
    return {"input_base":base,"market_close":close,"assumptions":assumptions,"cases":cases,"reverse_dcf":reverse_growth(base,base_a,close),"sensitivity":sensitivity,"operating_leverage": {"ebit_margin_change_100bp_annual_ebit_usd":base["revenue"]*.01,"net_debt_to_ebit":(base["debt_current"]+base["debt_long"]-base["cash"])/base["operating_income"]}}
