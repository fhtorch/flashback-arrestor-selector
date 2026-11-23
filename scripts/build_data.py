"""Build the flashback arrestor and check valve dataset from FHtorch's public product pages.

Reads the specification tables on the FHtorch flashback arrestor pages (https://fhtorch.com), then writes:
  data/flashback-arrestors.json   one record per model, plus the series notes
  data/flashback-arrestors.csv    same records, flat
  data/flashback-arrestors.js     window.FH_FA = {...} for index.html (works from file:// too)
  README.md                       the model tables between the CHART markers

Models, gases, mounting, max flow, max inlet pressure and threads are parsed from the pages on
every run. The short series notes (SERIES below) are copied by hand from the same pages.

Usage: python scripts/build_data.py
No third-party packages needed.
"""
import csv
import html
import json
import os
import re
import sys
import time
import urllib.request
from html.parser import HTMLParser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UA = "Mozilla/5.0 (compatible; fhtorch-flashback-arrestor-selector/1.0; +https://github.com/fhtorch/flashback-arrestor-selector)"
LPH_PER_CFH = 28.316846592  # 1 cubic foot = 28.316846592 L
PSI_PER_BAR = 14.5037738
P = "https://fhtorch.com/product/"
PAGES = [
    P + "regulator-flashback-arrestors-check-valves/",
    P + "cartridge-flashback-arrestors-388-488-588/",
    P + "h188-torch-flashback-arrestors/",
]
BUILT_IN = {
    "model": "MH001-005",
    "name": "Cutting torch with built-in flashback arrestors and reverse-flow check valves",
    "nozzles": "3-GPN, 3-101",
    "source_url": P + "cutting-torch-built-in-flashback-arrestors/",
}
GUIDE_URL = "https://fhtorch.com/flashback-arrestor-vs-check-valve/"

# Series notes, as described on the product pages.
SERIES = {
    "288": {"device": "flashback arrestor", "where": "Regulator outlet",
            "note": "Fits on the regulator outlet. Flame arrestor with non-return valve; a filter protects it from dirt particles; stops a flashback from travelling upstream into the connected equipment."},
    "B288": {"device": "flashback arrestor", "where": "Regulator outlet",
             "note": "Fits on the regulator outlet, with BSP 3/8\" threads. Flame arrestor with non-return valve; a filter protects it from dirt particles."},
    "88-3": {"device": "check valve", "where": "Torch",
             "note": "Compact check valve for the torch."},
    "388": {"device": "flashback arrestor", "where": "Hose line",
            "note": "Inline cartridge type for Φ8 mm hose."},
    "488": {"device": "flashback arrestor", "where": "Hose line",
            "note": "Inline cartridge type for Φ8 mm hose."},
    "588": {"device": "flashback arrestor", "where": "Torch or regulator",
            "note": "Cartridge type for torch or regulator mounting, 9/16\"×18 inlet."},
    "H188": {"device": "flashback arrestor", "where": "Between torch handle and hoses",
             "note": "Fits between the torch handle and the hoses. A filter protects it from dirt particles; non-return valve."},
}
MOUNT_KEYS = {"regulator": ["regulator"], "torch": ["torch"], "hose": ["hose"], "torch / regulator": ["torch", "regulator"]}


class Tables(HTMLParser):
    """Collects the tables of a page."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables, self._cell, self._row, self._tab = [], None, None, None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._tab = {"head": [], "rows": []}
        elif tag == "tr" and self._tab is not None:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = ""

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None:
            self._row.append(re.sub(r"\s+", " ", self._cell).strip())
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                if not self._tab["head"]:
                    self._tab["head"] = self._row
                else:
                    self._tab["rows"].append(self._row)
            self._row = None
        elif tag == "table" and self._tab is not None:
            self.tables.append(self._tab)
            self._tab = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell += data


def fetch_tables(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en"})
    page = urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "replace")
    m = re.search(r'id="tab-description"(.*?)</div>\s*</div>', page, re.S) or re.search(r"(<h2>Specifications</h2>.*)", page, re.S)
    parser = Tables()
    parser.feed(m.group(1) if m else page)
    return parser.tables


def col(head, *names):
    """Index of the first header equal to one of names, else the first header containing one."""
    low = [h.lower().strip() for h in head]
    for i, h in enumerate(low):
        if h in names:
            return i
    for i, h in enumerate(low):
        if any(n in h for n in names):
            return i
    return None


def num(s):
    m = re.search(r"\d+(?:[.,]\d+)?", html.unescape(s))
    return float(m.group(0).replace(",", ".")) if m else None


def conn(s):
    """'9/16"×18 R.H.' -> ('9/16"×18', 'R.H.'); 'Φ8 mm hose' -> ('Φ8 mm hose', '')."""
    m = re.search(r"\b([RL])\.H\.", s)
    hand = m.group(0) if m else ""
    return s.replace(hand, "").strip(), hand


def main():
    models = []
    for i, url in enumerate(PAGES):
        if i:
            time.sleep(1.0)  # be gentle with the site
        tabs = [t for t in fetch_tables(url) if col(t["head"], "model") is not None and col(t["head"], "gas") is not None]
        if not tabs:
            raise SystemExit(f"No model table on {url}")
        t = tabs[0]
        h = t["head"]
        i_m, i_g, i_for = col(h, "model"), col(h, "gas"), col(h, "for")
        i_f, i_p, i_in, i_out = col(h, "flow"), col(h, "pressure"), col(h, "inlet"), col(h, "outlet")
        for r in t["rows"]:
            model = r[i_m]
            series = model.rsplit("-", 1)[0]
            info = SERIES[series]
            mounting = r[i_for] if i_for is not None else info["where"]
            inlet, outlet = r[i_in], r[i_out]
            c, hand = conn(inlet if inlet not in ("–", "-", "") else outlet)
            flow, pres = num(r[i_f]), num(r[i_p])
            models.append({
                "model": model, "series": series, "device": info["device"],
                "gas": r[i_g], "mounting": mounting,
                "mount_keys": MOUNT_KEYS.get(mounting.lower(), ["torch"]),
                "max_flow_lph": int(flow) if flow is not None else None,
                "max_flow_cfh": round(flow / LPH_PER_CFH) if flow is not None else None,
                "max_inlet_bar": pres,
                "max_inlet_psi": round(pres * PSI_PER_BAR, 1) if pres is not None else None,
                "inlet": inlet, "outlet": outlet, "connection": c, "hand": hand,
                "source_url": url,
            })
        print(f"  {len(t['rows'])} models  {url}")

    # matching model for the other gas line: same series and connection, other gas
    for m in models:
        mates = [x["model"] for x in models if x["series"] == m["series"] and x["connection"] == m["connection"] and x["gas"] != m["gas"]]
        m["other_gas_model"] = mates[0] if mates else ""

    series = [{"series": s, **v, "source_url": next(m["source_url"] for m in models if m["series"] == s)}
              for s, v in SERIES.items() if any(m["series"] == s for m in models)]
    data = {
        "name": "FHtorch flashback arrestors and check valves",
        "source": "https://fhtorch.com",
        "license": "CC BY 4.0 (attribution: FHtorch, https://fhtorch.com)",
        "units": {"max flow": "L/h (cfh = L/h / 28.317)", "max inlet pressure": "bar (psi = bar x 14.504)"},
        "guide_url": GUIDE_URL, "built_in_torch": BUILT_IN,
        "series": series, "models": models,
    }
    out = os.path.join(ROOT, "data")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "flashback-arrestors.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    with open(os.path.join(out, "flashback-arrestors.js"), "w", encoding="utf-8") as f:
        f.write("// Generated by scripts/build_data.py from https://fhtorch.com product pages. CC BY 4.0, FHtorch.\n")
        f.write("window.FH_FA = " + json.dumps({k: data[k] for k in ("guide_url", "built_in_torch", "series", "models")}, ensure_ascii=False) + ";\n")
    fields = ["model", "series", "device", "gas", "mounting", "max_flow_lph", "max_flow_cfh", "max_inlet_bar", "max_inlet_psi",
              "inlet", "outlet", "connection", "hand", "other_gas_model", "source_url"]
    with open(os.path.join(out, "flashback-arrestors.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for m in models:
            w.writerow(m)

    # README chart section
    def g(x):
        return "–" if x is None else f"{x:g}"

    lines = []
    for s in series:
        rows = [m for m in models if m["series"] == s["series"]]
        lines.append(f"### {s['series']} ({s['device']}, {s['where'].lower()})\n")
        lines.append(f"{s['note']} Source: [{s['source_url'].replace('https://', '')}]({s['source_url']}?utm_source=github&utm_medium=readme)\n")
        lines.append("| Model | Gas | Mounting | Max flow (L/h) | Max inlet pressure (bar) | Inlet | Outlet |")
        lines.append("|---|---|---|---|---|---|---|")
        for m in rows:
            lines.append(f"| {m['model']} | {m['gas']} | {m['mounting']} | {g(m['max_flow_lph'])} | {g(m['max_inlet_bar'])} | {m['inlet']} | {m['outlet']} |")
        lines.append("")
    readme = os.path.join(ROOT, "README.md")
    if os.path.exists(readme):
        txt = open(readme, encoding="utf-8").read()
        new = re.sub(r"(<!-- CHART:START -->).*?(<!-- CHART:END -->)",
                     lambda m: m.group(1) + "\n\n" + "\n".join(lines) + "\n" + m.group(2), txt, flags=re.S)
        open(readme, "w", encoding="utf-8").write(new)
    print(f"{len(models)} models in {len(series)} series written")


if __name__ == "__main__":
    sys.exit(main())
