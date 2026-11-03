#!/usr/bin/env python3
"""The Stock Desk scanner.

Fetches daily price history (Yahoo Finance chart API, no key), per-ticker
headlines (Yahoo Finance RSS) and company blurbs (Wikipedia), computes
behavior statistics, and writes:
  data/stocks.json  - everything the page renders
  index.html        - baked SEO block + ItemList JSON-LD (between markers)
  feed.xml, sitemap.xml
Per-ticker failures keep the previous entry (flagged stale) so one bad
symbol never blanks a market. Run from the repo root.
"""
import json, math, os, re, subprocess, sys, time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

# ---------------------------------------------------------------- watchlists
# symbol (Yahoo), display name, Wikipedia title for the blurb
MARKETS = {
    "US": {"label": "United States", "flag": "\U0001F1FA\U0001F1F8", "index": ("^GSPC", "S&P 500"),
           "stocks": [("AAPL", "Apple", "Apple Inc."), ("MSFT", "Microsoft", "Microsoft"),
                      ("NVDA", "NVIDIA", "Nvidia"), ("AMZN", "Amazon", "Amazon (company)"),
                      ("GOOGL", "Alphabet (Google)", "Alphabet Inc."), ("META", "Meta Platforms", "Meta Platforms"),
                      ("TSLA", "Tesla", "Tesla, Inc."), ("JPM", "JPMorgan Chase", "JPMorgan Chase"),
                      ("V", "Visa", "Visa Inc."), ("NFLX", "Netflix", "Netflix")]},
    "GB": {"label": "United Kingdom", "flag": "\U0001F1EC\U0001F1E7", "index": ("^FTSE", "FTSE 100"),
           "stocks": [("SHEL.L", "Shell", "Shell plc"), ("HSBA.L", "HSBC", "HSBC"),
                      ("AZN.L", "AstraZeneca", "AstraZeneca"), ("BP.L", "BP", "BP"),
                      ("ULVR.L", "Unilever", "Unilever"), ("VOD.L", "Vodafone", "Vodafone"),
                      ("RR.L", "Rolls-Royce", "Rolls-Royce Holdings"), ("BARC.L", "Barclays", "Barclays"),
                      ("LLOY.L", "Lloyds Banking", "Lloyds Banking Group"), ("RIO.L", "Rio Tinto", "Rio Tinto (corporation)")]},
    "DE": {"label": "Germany", "flag": "\U0001F1E9\U0001F1EA", "index": ("^GDAXI", "DAX"),
           "stocks": [("SAP.DE", "SAP", "SAP"), ("SIE.DE", "Siemens", "Siemens"),
                      ("ALV.DE", "Allianz", "Allianz"), ("DTE.DE", "Deutsche Telekom", "Deutsche Telekom"),
                      ("BAS.DE", "BASF", "BASF"), ("BMW.DE", "BMW", "BMW"),
                      ("ADS.DE", "Adidas", "Adidas"), ("IFX.DE", "Infineon", "Infineon Technologies"),
                      ("MBG.DE", "Mercedes-Benz", "Mercedes-Benz Group"), ("VOW3.DE", "Volkswagen", "Volkswagen")]},
    "JP": {"label": "Japan", "flag": "\U0001F1EF\U0001F1F5", "index": ("^N225", "Nikkei 225"),
           "stocks": [("7203.T", "Toyota", "Toyota"), ("6758.T", "Sony", "Sony"),
                      ("9984.T", "SoftBank Group", "SoftBank Group"), ("8306.T", "Mitsubishi UFJ", "Mitsubishi UFJ Financial Group"),
                      ("6861.T", "Keyence", "Keyence"), ("9432.T", "NTT", "Nippon Telegraph and Telephone"),
                      ("7974.T", "Nintendo", "Nintendo"), ("6098.T", "Recruit", "Recruit (company)"),
                      ("4502.T", "Takeda Pharmaceutical", "Takeda Pharmaceutical Company"), ("7741.T", "Hoya", "Hoya Corporation")]},
    "IN": {"label": "India", "flag": "\U0001F1EE\U0001F1F3", "index": ("^NSEI", "Nifty 50"),
           "stocks": [("RELIANCE.NS", "Reliance Industries", "Reliance Industries"), ("TCS.NS", "Tata Consultancy", "Tata Consultancy Services"),
                      ("INFY.NS", "Infosys", "Infosys"), ("HDFCBANK.NS", "HDFC Bank", "HDFC Bank"),
                      ("ICICIBANK.NS", "ICICI Bank", "ICICI Bank"), ("SBIN.NS", "State Bank of India", "State Bank of India"),
                      ("BHARTIARTL.NS", "Bharti Airtel", "Bharti Airtel"), ("ITC.NS", "ITC", "ITC Limited"),
                      ("LT.NS", "Larsen & Toubro", "Larsen & Toubro"), ("HINDUNILVR.NS", "Hindustan Unilever", "Hindustan Unilever")]},
    "CA": {"label": "Canada", "flag": "\U0001F1E8\U0001F1E6", "index": ("^GSPTSE", "S&P/TSX Composite"),
           "stocks": [("SHOP.TO", "Shopify", "Shopify"), ("RY.TO", "Royal Bank of Canada", "Royal Bank of Canada"),
                      ("TD.TO", "TD Bank", "Toronto-Dominion Bank"), ("ENB.TO", "Enbridge", "Enbridge"),
                      ("CNR.TO", "Canadian National Railway", "Canadian National Railway"), ("BNS.TO", "Scotiabank", "Scotiabank"),
                      ("BMO.TO", "Bank of Montreal", "Bank of Montreal"), ("ATD.TO", "Alimentation Couche-Tard", "Alimentation Couche-Tard"),
                      ("CSU.TO", "Constellation Software", "Constellation Software"), ("MFC.TO", "Manulife", "Manulife")]},
}

def fetch(url, timeout=30):
    """urllib first; curl fallback (egress proxies sometimes drop urllib TLS)."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", "replace")
    except Exception:
        out = subprocess.run(["curl", "-s", "--max-time", str(timeout), "-A", UA, url],
                             capture_output=True, text=True)
        if out.returncode == 0 and out.stdout:
            return out.stdout
        raise

def chart(symbol):
    url = "https://query2.finance.yahoo.com/v8/finance/chart/" + symbol + "?range=5y&interval=1d"
    data = json.loads(fetch(url))
    res = data["chart"]["result"][0]
    meta = res["meta"]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    rows = []
    for i, t in enumerate(ts):
        c = q["close"][i]
        if c is None:
            continue
        rows.append({"d": datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d"),
                     "c": c, "h": q["high"][i] or c, "l": q["low"][i] or c,
                     "v": q["volume"][i] or 0})
    cur = meta.get("currency", "")
    if cur == "GBp":  # London prices come in pence; normalize to pounds
        for r in rows:
            r["c"] /= 100.0; r["h"] /= 100.0; r["l"] /= 100.0
        cur = "GBP"
    return cur, rows

def pct(a, b):
    return (a / b - 1.0) * 100.0 if b else None

def stats(rows):
    closes = [r["c"] for r in rows]
    last, prev = closes[-1], closes[-2] if len(closes) > 1 else closes[-1]
    def ret(days):
        return pct(last, closes[-1 - days]) if len(closes) > days else None
    win = rows[-252:]
    hi = max(r["h"] for r in win); lo = min(r["l"] for r in win)
    sma50 = sum(closes[-50:]) / 50 if len(closes) >= 50 else None
    sma200 = sum(closes[-200:]) / 200 if len(closes) >= 200 else None
    rets = [pct(closes[i], closes[i - 1]) for i in range(1, len(closes))]
    r30 = rets[-30:]
    vol = None
    if len(r30) >= 10:
        m = sum(r30) / len(r30)
        vol = math.sqrt(sum((x - m) ** 2 for x in r30) / (len(r30) - 1)) * math.sqrt(252)
    peak, maxdd = closes[0], 0.0
    for c in closes[-252:]:
        peak = max(peak, c); maxdd = min(maxdd, pct(c, peak))
    s = {"price": round(last, 2), "day_pct": round(pct(last, prev), 2),
         "r_1w": rnd(ret(5)), "r_1m": rnd(ret(21)), "r_3m": rnd(ret(63)),
         "r_6m": rnd(ret(126)), "r_1y": rnd(ret(252)), "r_5y": rnd(pct(last, closes[0])),
         "hi52": round(hi, 2), "lo52": round(lo, 2),
         "from_hi_pct": rnd(pct(last, hi)),
         "pos52": round((last - lo) / (hi - lo) * 100, 1) if hi > lo else None,
         "sma50": rnd(sma50), "sma200": rnd(sma200),
         "vol_pct": rnd(vol), "maxdd_1y": rnd(maxdd),
         "best_day": rnd(max(rets[-252:])) if rets else None,
         "worst_day": rnd(min(rets[-252:])) if rets else None,
         "avg_vol_30d": int(sum(r["v"] for r in rows[-30:]) / min(30, len(rows)))}
    s["trend"] = trend_label(s)
    s["behavior"] = behavior(s)
    return s

def rnd(x):
    return round(x, 2) if isinstance(x, (int, float)) else None

def trend_label(s):
    p, a, b = s["price"], s["sma50"], s["sma200"]
    if a is None or b is None:
        return "Not enough history"
    if p > a > b: return "Strong uptrend"
    if p < a < b: return "Strong downtrend"
    if p > b: return "Uptrend (mixed short term)"
    if p < b: return "Downtrend (mixed short term)"
    return "Sideways"

def behavior(s):
    out = []
    p = s["price"]
    if s["sma200"] is not None:
        side = "above" if p > s["sma200"] else "below"
        out.append(f"Trading {side} its 200-day average ({s['sma200']}), the line most long-term watchers follow — "
                   + ("long-term trend is up." if side == "above" else "long-term trend is down."))
    if s["r_1y"] is not None:
        out.append(f"Over the last year it is {'up' if s['r_1y'] >= 0 else 'down'} {abs(s['r_1y'])}%, "
                   f"sitting {abs(s['from_hi_pct'])}% {'below' if s['from_hi_pct'] <= 0 else 'above'} its 52-week high of {s['hi52']}.")
    if s["vol_pct"] is not None:
        lab = "calm" if s["vol_pct"] < 20 else ("moderate" if s["vol_pct"] < 35 else "jumpy")
        out.append(f"Volatility runs {lab} at about {s['vol_pct']}% a year; its worst single day in the past year was {s['worst_day']}% "
                   f"and its best was +{s['best_day']}%.")
    if s["maxdd_1y"] is not None and s["maxdd_1y"] < -5:
        out.append(f"The deepest slide of the past year was {s['maxdd_1y']}% from peak to trough — that's the patience this stock has demanded.")
    if s["r_5y"] is not None:
        out.append(f"Five-year view: {'+' if s['r_5y'] >= 0 else ''}{s['r_5y']}% across the full period in the chart.")
    return out

def headlines(symbol):
    url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={symbol}&region=US&lang=en-US"
    try:
        root = ET.fromstring(fetch(url, timeout=20))
        items = []
        for it in root.iter("item"):
            title = it.findtext("title"); link = it.findtext("link"); date = it.findtext("pubDate")
            if title and link:
                items.append({"title": title.strip(), "url": link.strip(), "date": date or ""})
            if len(items) >= 4:
                break
        return items
    except Exception:
        return []

def wiki_blurb(title):
    try:
        data = json.loads(fetch("https://en.wikipedia.org/api/rest_v1/page/summary/" +
                                title.replace(" ", "_"), timeout=20))
        ex = (data.get("extract") or "").strip()
        return ex[:300].rsplit(" ", 1)[0] + "…" if len(ex) > 300 else ex
    except Exception:
        return ""

def downsample(rows, step=5):
    pts = [[r["d"], round(r["c"], 2)] for r in rows[::step]]
    if rows and pts[-1][0] != rows[-1]["d"]:
        pts.append([rows[-1]["d"], round(rows[-1]["c"], 2)])
    return pts

def main():
    prev = {}
    pdata = os.path.join(ROOT, "data", "stocks.json")
    if os.path.exists(pdata):
        try:
            prev = json.load(open(pdata))
        except Exception:
            prev = {}
    prev_by = {}
    for m in (prev.get("markets") or {}).values():
        for st in m.get("stocks", []):
            prev_by[st["symbol"]] = st
    now = datetime.now(timezone.utc)
    out = {"generated_at": now.strftime("%Y-%m-%dT%H:%M:%S+00:00"), "markets": {}, "movers": []}
    all_stocks = []
    for code, m in MARKETS.items():
        entry = {"label": m["label"], "flag": m["flag"], "index": None, "stocks": []}
        isym, iname = m["index"]
        try:
            cur, rows = chart(isym)
            s = stats(rows)
            entry["index"] = {"symbol": isym, "name": iname, "currency": cur,
                              "price": s["price"], "day_pct": s["day_pct"], "r_1y": s["r_1y"]}
        except Exception as e:
            print(f"index {isym} failed: {e}", file=sys.stderr)
        for sym, name, wtitle in m["stocks"]:
            old = prev_by.get(sym)
            try:
                cur, rows = chart(sym)
                s = stats(rows)
                blurb, blurb_at = (old or {}).get("blurb", ""), (old or {}).get("blurb_at", "")
                stale_blurb = True
                if blurb_at:
                    try:
                        stale_blurb = (now - datetime.fromisoformat(blurb_at)).days >= 6
                    except Exception:
                        stale_blurb = True
                if not blurb or stale_blurb:
                    b = wiki_blurb(wtitle)
                    if b:
                        blurb, blurb_at = b, now.strftime("%Y-%m-%dT%H:%M:%S+00:00")
                item = {"symbol": sym, "name": name, "currency": cur, "stale": False,
                        **s, "history": downsample(rows), "headlines": headlines(sym),
                        "blurb": blurb, "blurb_at": blurb_at}
            except Exception as e:
                print(f"{sym} failed: {e}", file=sys.stderr)
                if old:
                    item = {**old, "stale": True}
                else:
                    continue
            entry["stocks"].append(item)
            all_stocks.append({**item, "market": code})
            time.sleep(0.25)
        out["markets"][code] = entry
        print(f"{code}: index={'ok' if entry['index'] else 'FAIL'} stocks={len(entry['stocks'])}")
    ranked = sorted([s for s in all_stocks if s.get("day_pct") is not None],
                    key=lambda s: s["day_pct"], reverse=True)
    out["movers"] = {"gainers": [lite(s) for s in ranked[:5]],
                     "losers": [lite(s) for s in ranked[-5:]][::-1]}
    with open(pdata, "w") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    changed = bake(out, prev)
    print("baked-changed:", changed)
    return 0 if not changed else 0

def lite(s):
    return {"symbol": s["symbol"], "name": s["name"], "market": s["market"],
            "price": s["price"], "day_pct": s["day_pct"], "currency": s["currency"]}

def bake(out, prev):
    ipath = os.path.join(ROOT, "index.html")
    html = open(ipath).read()
    lines = []
    for code, m in out["markets"].items():
        idx = m["index"]
        if idx:
            lines.append(f"<p><strong>{m['flag']} {m['label']} — {idx['name']}:</strong> "
                         f"{idx['price']} ({idx['day_pct']:+}% today, {idx['r_1y']:+}% in a year)</p>")
        lines.append(f"<h3>{m['flag']} {m['label']} stocks</h3><ul>")
        for s in m["stocks"]:
            lines.append(
                f"<li><strong>{s['symbol']} — {s['name']}:</strong> {s['price']} {s['currency']}, "
                f"{s['day_pct']:+}% today, {s['r_1y']:+}% over one year, {s['r_5y']:+}% over five years. "
                f"Trend: {s['trend']}. 52-week range {s['lo52']}–{s['hi52']}; volatility about {s['vol_pct']}% a year.</li>")
        lines.append("</ul>")
    block = "\n".join(lines)
    items = []
    pos = 1
    for code, m in out["markets"].items():
        for s in m["stocks"]:
            items.append({"@type": "ListItem", "position": pos,
                          "name": f"{s['name']} ({s['symbol']}) stock history and behavior",
                          "url": f"https://bishowpratap7.github.io/thestockdesk/#{s['symbol']}"})
            pos += 1
    ld = {"@context": "https://schema.org", "@type": "ItemList",
          "name": "Stocks covered by The Stock Desk", "itemListElement": items}
    ld_html = '<script type="application/ld+json">\n' + json.dumps(ld, ensure_ascii=False) + "\n</script>"
    new = re.sub(r"<!--STOCKS:START-->.*?<!--STOCKS:END-->",
                 "<!--STOCKS:START-->\n" + block + "\n<!--STOCKS:END-->", html, flags=re.S)
    new = re.sub(r"<!--ITEMLIST:START-->.*?<!--ITEMLIST:END-->",
                 "<!--ITEMLIST:START-->\n" + ld_html + "\n<!--ITEMLIST:END-->", new, flags=re.S)
    changed = new != html
    if changed:
        open(ipath, "w").write(new)
        write_feed(out); write_sitemap(out)
    return changed

def esc(t):
    return (t or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def write_feed(out):
    g = out["movers"]["gainers"]; l = out["movers"]["losers"]
    items = ""
    for s in g + l:
        items += (f"<item><title>{esc(s['name'])} ({esc(s['symbol'])}): {s['day_pct']:+}% today at {s['price']} {esc(s['currency'])}</title>"
                  f"<link>https://bishowpratap7.github.io/thestockdesk/#{esc(s['symbol'])}</link>"
                  f"<guid>https://bishowpratap7.github.io/thestockdesk/#{esc(s['symbol'])}</guid>"
                  f"<pubDate>{out['generated_at']}</pubDate></item>\n")
    feed = ('<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0"><channel>'
            "<title>The Stock Desk — Top Movers</title>"
            "<link>https://bishowpratap7.github.io/thestockdesk/</link>"
            "<description>Biggest daily movers across the US, UK, German, Japanese, Indian and Canadian stocks tracked by The Stock Desk.</description>\n"
            + items + "</channel></rss>")
    open(os.path.join(ROOT, "feed.xml"), "w").write(feed)

def write_sitemap(out):
    sm = ('<?xml version="1.0" encoding="UTF-8"?>\n'
          '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
          f"<url><loc>https://bishowpratap7.github.io/thestockdesk/</loc>"
          f"<lastmod>{out['generated_at']}</lastmod><changefreq>hourly</changefreq><priority>1.0</priority></url>"
          "</urlset>")
    open(os.path.join(ROOT, "sitemap.xml"), "w").write(sm)

if __name__ == "__main__":
    sys.exit(main())
