# =====================================================================
# PART 1: LOAD THE TOOLS THE PROGRAM NEEDS
# =====================================================================
import hmac
import json
import os
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from urllib.parse import quote

import altair as alt
import gspread
import pandas as pd
import requests
import streamlit as st
import yfinance as yf
from gspread.utils import ValueRenderOption

# =====================================================================
# PART 2: BASIC SETTINGS
# =====================================================================
st.set_page_config(page_title="My Thai Stock Portfolio", page_icon="📈", layout="centered")

APP_FOLDER = os.path.dirname(os.path.abspath(__file__))
SYMBOL_CACHE_FILE = os.path.join(APP_FOLDER, "set_symbols.json")  # saved list of Thai stocks
THAI_TIME = timezone(timedelta(hours=7))                          # Thailand time (UTC+7)
REFRESH_SECONDS = 60                                              # how often prices refresh
WITHHOLDING_TAX = 0.10                                            # Thai dividend tax (10%)
LARGE_HOLDING_PCT = 40                                            # warn if one stock is above this %

PERIOD_OPTIONS = {
    "1 month": "1mo",
    "3 months": "3mo",
    "6 months": "6mo",
    "1 year": "1y",
    "5 years": "5y",
}

# Column names used in the Google Sheet tabs
HEADERS = {
    "purchases": ["symbol", "shares", "price", "time"],
    "dividends": ["symbol", "date", "per_share", "shares", "gross", "tax", "net", "time"],
}

# =====================================================================
# PART 3: BACKUP LIST OF THAI STOCKS (used if the online list can't load)
# =====================================================================
BACKUP_STOCKS = {
    "AAV": "Asia Aviation", "ADVANC": "Advanced Info Service", "AEONTS": "AEON Thana Sinsap",
    "AMATA": "Amata Corporation", "AOT": "Airports of Thailand", "AP": "AP (Thailand)",
    "AWC": "Asset World Corp", "BA": "Bangkok Airways", "BAM": "Bangkok Commercial Asset Mgmt",
    "BANPU": "Banpu", "BBL": "Bangkok Bank", "BCH": "Bangkok Chain Hospital",
    "BCP": "Bangchak Corporation", "BCPG": "BCPG", "BDMS": "Bangkok Dusit Medical Services",
    "BEM": "Bangkok Expressway and Metro", "BGRIM": "B.Grimm Power", "BH": "Bumrungrad Hospital",
    "BJC": "Berli Jucker", "BLA": "Bangkok Life Assurance", "BSRC": "Bangchak Sriracha",
    "BTG": "Betagro", "BTS": "BTS Group Holdings", "CBG": "Carabao Group",
    "CENTEL": "Central Plaza Hotel", "CHG": "Chularat Hospital", "CK": "CH. Karnchang",
    "CKP": "CK Power", "COM7": "Com7", "CPALL": "CP ALL", "CPAXT": "CP Axtra",
    "CPF": "Charoen Pokphand Foods", "CPN": "Central Pattana", "CRC": "Central Retail Corporation",
    "DELTA": "Delta Electronics (Thailand)", "DIF": "Digital Telecom Infrastructure Fund",
    "DOHOME": "Dohome", "EA": "Energy Absolute", "EGCO": "Electricity Generating",
    "ERW": "The Erawan Group", "GFPT": "GFPT", "GLOBAL": "Siam Global House",
    "GPSC": "Global Power Synergy", "GULF": "Gulf Development", "GUNKUL": "Gunkul Engineering",
    "HANA": "Hana Microelectronics", "HMPRO": "Home Product Center", "ICHI": "Ichitan Group",
    "IRPC": "IRPC", "ITC": "i-Tail Corporation", "IVL": "Indorama Ventures", "JMART": "Jaymart Group",
    "JMT": "JMT Network Services", "KBANK": "Kasikornbank", "KCE": "KCE Electronics",
    "KKP": "Kiatnakin Phatra Bank", "KTB": "Krung Thai Bank", "KTC": "Krungthai Card",
    "LH": "Land and Houses", "M": "MK Restaurant Group", "MAJOR": "Major Cineplex Group",
    "MEGA": "Mega Lifesciences", "MINT": "Minor International", "MTC": "Muangthai Capital",
    "NER": "North East Rubber", "OR": "PTT Oil and Retail Business", "OSP": "Osotspa",
    "PLANB": "Plan B Media", "PR9": "Praram 9 Hospital", "PTT": "PTT",
    "PTTEP": "PTT Exploration and Production", "PTTGC": "PTT Global Chemical",
    "QH": "Quality Houses", "RATCH": "Ratch Group", "RCL": "Regional Container Lines",
    "SAPPE": "Sappe", "SAWAD": "Srisawad Corporation", "SCB": "SCB X", "SCC": "Siam Cement",
    "SCGP": "SCG Packaging", "SIRI": "Sansiri", "SISB": "SISB", "SJWD": "SCGJWD Logistics",
    "SPALI": "Supalai", "SPRC": "Star Petroleum Refining", "STA": "Sri Trang Agro-Industry",
    "STGT": "Sri Trang Gloves", "TASCO": "Tipco Asphalt", "TCAP": "Thanachart Capital",
    "TFG": "Thaifoods Group", "THAI": "Thai Airways International", "THANI": "Ratchthani Leasing",
    "THG": "Thonburi Healthcare Group", "TIDLOR": "Ngern Tid Lor", "TISCO": "Tisco Financial Group",
    "TKN": "Taokaenoi Food & Marketing", "TLI": "Thai Life Insurance", "TOA": "TOA Paint (Thailand)",
    "TOP": "Thai Oil", "TRUE": "True Corporation", "TTB": "TMBThanachart Bank",
    "TU": "Thai Union Group", "VGI": "VGI", "WHA": "WHA Corporation",
}

# =====================================================================
# PART 4: GET THE FULL LIST OF THAI STOCKS
# =====================================================================
@st.cache_data(ttl=86400, show_spinner=False)
def load_set_symbols():
    stocks = dict(BACKUP_STOCKS)

    if os.path.exists(SYMBOL_CACHE_FILE):
        try:
            with open(SYMBOL_CACHE_FILE, "r", encoding="utf-8") as f:
                stocks.update(json.load(f))
        except Exception:
            pass

    try:
        response = requests.get(
            "https://www.set.or.th/api/set/stock/list",
            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
            timeout=10,
        )
        if response.ok:
            items = response.json().get("securitySymbols", [])
            common = {}
            everything = {}
            for item in items:
                sym = str(item.get("symbol", "")).strip().upper()
                if not sym:
                    continue
                name = item.get("nameEN") or item.get("nameTH") or sym
                everything[sym] = name
                if item.get("securityType") in (None, "S"):
                    common[sym] = name
            online = common if len(common) > 100 else everything
            if len(online) > 100:
                stocks.update(online)
                try:
                    with open(SYMBOL_CACHE_FILE, "w", encoding="utf-8") as f:
                        json.dump(online, f, ensure_ascii=False)
                except Exception:
                    pass
    except Exception:
        pass

    return stocks

# =====================================================================
# PART 5: GET PRICES, PRICE HISTORY AND DIVIDEND INFO FROM YAHOO
# =====================================================================
@st.cache_data(ttl=30, show_spinner=False)
def get_price(symbol):
    ticker = yf.Ticker(f"{symbol}.BK")
    try:
        price = ticker.fast_info.last_price
        if price and price > 0:
            return float(price)
    except Exception:
        pass
    try:
        history = ticker.history(period="5d")
        if not history.empty:
            return float(history["Close"].dropna().iloc[-1])
    except Exception:
        pass
    return None


@st.cache_data(ttl=600, show_spinner=False)
def get_price_history(symbol, period):
    try:
        history = yf.Ticker(f"{symbol}.BK").history(period=period)
        if history is None or history.empty:
            return None
        closes = history["Close"].dropna()
        if closes.empty:
            return None
        if closes.index.tz is not None:
            closes.index = closes.index.tz_localize(None)
        return closes
    except Exception:
        return None


@st.cache_data(ttl=3600, show_spinner=False)
def get_market_dividend_12m(symbol):
    try:
        divs = yf.Ticker(f"{symbol}.BK").dividends
        if divs is None or divs.empty:
            return None
        cutoff = pd.Timestamp.now(tz=divs.index.tz) - pd.Timedelta(days=365)
        total = float(divs[divs.index >= cutoff].sum())
        return total if total > 0 else None
    except Exception:
        return None

# =====================================================================
# PART 5b: MULTI-SOURCE FILTERED NEWS
# =====================================================================
IGNORE_KEYWORDS = [
    "ประชุมผู้ถือหุ้น", "กำหนดการประชุม", "วันปิดสมุดทะเบียน", "agm", "egm",
    "annual general meeting", "extraordinary general meeting", "notice of meeting",
    "book closing", "record date", "มติที่ประชุม", "แจ้งการเผยแพร่หนังสือ",
    "แต่งตั้งกรรมการ", "ลาออกจากตำแหน่ง", "warrant expiration"
]

BUSINESS_KEYWORDS = [
    "กำไร", "ขาดทุน", "รายได้", "ผลการดำเนินงาน", "งบการเงิน", "ยอดขาย", "เป้าหมาย",
    "แนวโน้ม", "โบรก", "เคาะเป้า", "ราคาเป้าหมาย", "โต", "ไตรมาส", "q1", "q2", "q3", "q4",
    "profit", "loss", "revenue", "earnings", "growth", "performance", "outlook",
    "target price", "forecast", "margin", "sales", "expansion", "ebitda"
]

@st.cache_data(ttl=1800, show_spinner=False)
def get_filtered_news(symbol, company_name=""):
    raw_articles = []
    seen_titles = set()

    # Source 1: Yahoo Finance News (old and new yfinance formats)
    try:
        ticker = yf.Ticker(f"{symbol}.BK")
        yf_news = ticker.news or []
        for item in yf_news:
            if not isinstance(item, dict):
                continue
            content = item.get("content") if isinstance(item.get("content"), dict) else item
            title = str(content.get("title") or "").strip()
            link_info = (content.get("clickThroughUrl") or content.get("canonicalUrl")
                         or content.get("link") or "#")
            link = link_info.get("url", "#") if isinstance(link_info, dict) else str(link_info)
            provider = content.get("provider")
            if isinstance(provider, dict):
                publisher = provider.get("displayName", "Yahoo Finance")
            else:
                publisher = content.get("publisher", "Yahoo Finance")
            if title and title not in seen_titles:
                seen_titles.add(title)
                raw_articles.append({"title": title, "link": link, "source": publisher})
    except Exception:
        pass

    # Source 2: Google News Thailand
    search_queries = [
        f"{symbol} หุ้น กำไร OR รายได้ OR แนวโน้ม",
        f"{symbol} {company_name.split()[0] if company_name else ''} stock business performance"
    ]
    for q in search_queries:
        rss_url = f"https://news.google.com/rss/search?q={quote(q)}&hl=th&gl=TH&ceid=TH:th"
        try:
            resp = requests.get(rss_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=6)
            if resp.ok:
                root = ET.fromstring(resp.content)
                for item in root.findall(".//item")[:10]:
                    title = item.find("title").text if item.find("title") is not None else ""
                    link = item.find("link").text if item.find("link") is not None else "#"
                    source_elem = item.find("source")
                    source = source_elem.text if source_elem is not None else "Google News"
                    if title and title not in seen_titles:
                        seen_titles.add(title)
                        raw_articles.append({"title": title, "link": link, "source": source})
        except Exception:
            pass

    filtered_articles = []
    for art in raw_articles:
        title_lower = art["title"].lower()
        if any(unwanted in title_lower for unwanted in IGNORE_KEYWORDS):
            continue
        art["highlight"] = any(term in title_lower for term in BUSINESS_KEYWORDS)
        filtered_articles.append(art)

    filtered_articles.sort(key=lambda x: x["highlight"], reverse=True)
    return filtered_articles[:8]

# =====================================================================
# PART 6: GOOGLE SHEETS STORAGE (replaces the portfolio.json files)
# =====================================================================
@st.cache_resource(show_spinner=False)
def get_spreadsheet():
    info = json.loads(st.secrets["gcp_json"])
    client = gspread.service_account_from_dict(info)
    return client.open_by_url(st.secrets["sheet_url"])


@st.cache_resource(show_spinner=False)
def get_worksheet(name):
    spreadsheet = get_spreadsheet()
    headers = HEADERS[name]
    try:
        return spreadsheet.worksheet(name)
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=name, rows=1000, cols=len(headers))
        ws.update(values=[headers], range_name="A1")
        return ws


@st.cache_data(ttl=20, show_spinner=False)
def read_rows(name):
    rows = get_worksheet(name).get_values(value_render_option=ValueRenderOption.unformatted)
    return [list(r) for r in rows[1:] if r and str(r[0]).strip()]


def write_rows(name, rows):
    ws = get_worksheet(name)
    headers = HEADERS[name]
    values = [headers] + rows
    if len(values) >= ws.row_count:
        ws.add_rows(len(values) - ws.row_count + 100)
    ws.update(values=values, range_name="A1")          # write new data first (safe)
    last_col = chr(ord("A") + len(headers) - 1)
    if len(values) < ws.row_count:
        ws.batch_clear([f"A{len(values) + 1}:{last_col}"])  # then clear leftover old rows
    read_rows.clear()


def to_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default

# =====================================================================
# PART 6a: LOAD / SAVE PURCHASES AND DO THE MATH
# =====================================================================
def load_portfolio():
    portfolio = {}
    for r in read_rows("purchases"):
        r = r + [""] * 4
        symbol = str(r[0]).strip().upper()
        shares = int(to_float(r[1]))
        if not symbol or shares <= 0:
            continue
        portfolio.setdefault(symbol, []).append({
            "shares": shares, "price": to_float(r[2]), "time": str(r[3]),
        })
    return portfolio


def save_portfolio(portfolio):
    rows = []
    for symbol in portfolio:
        for e in portfolio[symbol]:
            rows.append([symbol, int(e["shares"]), float(e["price"]), str(e.get("time", ""))])
    write_rows("purchases", rows)


def summarize(entries):
    total_shares = sum(e["shares"] for e in entries)
    total_cost = sum(e["shares"] * e["price"] for e in entries)
    avg_price = total_cost / total_shares if total_shares > 0 else 0.0
    return total_shares, avg_price, total_cost


def add_purchase(symbol, shares, price):
    portfolio = load_portfolio()
    portfolio.setdefault(symbol, []).append({
        "shares": int(shares),
        "price": float(price),
        "time": datetime.now(THAI_TIME).strftime("%Y-%m-%d %H:%M:%S"),
    })
    save_portfolio(portfolio)
    return summarize(portfolio[symbol])


def delete_entry(symbol, index):
    portfolio = load_portfolio()
    entries = portfolio.get(symbol, [])
    if 0 <= index < len(entries):
        entries.pop(index)
    if entries:
        portfolio[symbol] = entries
    else:
        portfolio.pop(symbol, None)
    save_portfolio(portfolio)
    return bool(entries)


def money(x):
    return f"฿{x:,.2f}"


def money_precise(x):
    text = f"{x:,.4f}".rstrip("0")
    if text.endswith("."):
        text += "00"
    elif len(text.split(".")[1]) < 2:
        text += "0"
    return "฿" + text

# =====================================================================
# PART 6b: LOAD / SAVE DIVIDENDS AND DO THE DIVIDEND MATH
# =====================================================================
def load_dividends():
    dividends = {}
    for r in read_rows("dividends"):
        r = r + [""] * 8
        symbol = str(r[0]).strip().upper()
        if not symbol:
            continue
        dividends.setdefault(symbol, []).append({
            "date": str(r[1]),
            "per_share": to_float(r[2]),
            "shares": int(to_float(r[3])),
            "gross": to_float(r[4]),
            "tax": to_float(r[5]),
            "net": to_float(r[6]),
            "time": str(r[7]),
        })
    return dividends


def save_dividends(dividends):
    rows = []
    for symbol in dividends:
        for d in dividends[symbol]:
            rows.append([symbol, str(d.get("date", "")), float(d.get("per_share", 0)),
                         int(d.get("shares", 0)), float(d.get("gross", 0)),
                         float(d.get("tax", 0)), float(d.get("net", 0)), str(d.get("time", ""))])
    write_rows("dividends", rows)


def add_dividend(symbol, per_share, shares, pay_date, subtract_tax):
    gross = float(per_share) * int(shares)
    tax = gross * WITHHOLDING_TAX if subtract_tax else 0.0
    net = gross - tax
    dividends = load_dividends()
    dividends.setdefault(symbol, []).append({
        "date": pay_date.strftime("%Y-%m-%d"),
        "per_share": float(per_share),
        "shares": int(shares),
        "gross": round(gross, 2),
        "tax": round(tax, 2),
        "net": round(net, 2),
        "time": datetime.now(THAI_TIME).strftime("%Y-%m-%d %H:%M:%S"),
    })
    dividends[symbol].sort(key=lambda d: d.get("date", ""))
    save_dividends(dividends)
    return net


def delete_dividend(symbol, index):
    dividends = load_dividends()
    entries = dividends.get(symbol, [])
    if 0 <= index < len(entries):
        entries.pop(index)
    if entries:
        dividends[symbol] = entries
    else:
        dividends.pop(symbol, None)
    save_dividends(dividends)


def dividend_totals(entries):
    cutoff = (datetime.now(THAI_TIME) - timedelta(days=365)).strftime("%Y-%m-%d")
    total = sum(float(d.get("net", 0)) for d in entries)
    last_12m = sum(float(d.get("net", 0)) for d in entries if str(d.get("date", "")) >= cutoff)
    return total, last_12m

# =====================================================================
# PART 6c: IMPORT DATA FROM THE COMPUTER VERSION (one-time)
# =====================================================================
def clean_imported_portfolio(data):
    if not isinstance(data, dict):
        raise ValueError("This doesn't look like a portfolio.json file.")
    result = {}
    for symbol, entries in data.items():
        for e in entries or []:
            shares = int(to_float(e.get("shares")))
            if shares <= 0:
                continue
            result.setdefault(str(symbol).strip().upper(), []).append({
                "shares": shares, "price": to_float(e.get("price")), "time": str(e.get("time", "")),
            })
    return result


def clean_imported_dividends(data):
    if not isinstance(data, dict):
        raise ValueError("This doesn't look like a dividends.json file.")
    result = {}
    for symbol, entries in data.items():
        for d in entries or []:
            shares = int(to_float(d.get("shares")))
            per_share = to_float(d.get("per_share"))
            if shares <= 0 or per_share <= 0:
                continue
            gross = to_float(d.get("gross"), per_share * shares)
            tax = to_float(d.get("tax"))
            result.setdefault(str(symbol).strip().upper(), []).append({
                "date": str(d.get("date", "")), "per_share": per_share, "shares": shares,
                "gross": gross, "tax": tax, "net": to_float(d.get("net"), gross - tax),
                "time": str(d.get("time", "")),
            })
    return result


def import_section():
    with st.expander("📥 Import data from the computer version (one time only)"):
        st.write("Upload **portfolio.json** and **dividends.json** from your StockApp folder.")
        st.warning("This replaces any stocks / dividends already saved in the online app.")
        pf_file = st.file_uploader("portfolio.json", type=["json"], key="import_pf")
        dv_file = st.file_uploader("dividends.json (optional)", type=["json"], key="import_dv")
        if st.button("Import now", disabled=(pf_file is None and dv_file is None)):
            done = False
            try:
                n_stocks = n_divs = 0
                if pf_file is not None:
                    pf = clean_imported_portfolio(json.load(pf_file))
                    save_portfolio(pf)
                    n_stocks = len(pf)
                if dv_file is not None:
                    dv = clean_imported_dividends(json.load(dv_file))
                    save_dividends(dv)
                    n_divs = sum(len(v) for v in dv.values())
                st.session_state.flash = (f"Imported {n_stocks} stocks and "
                                          f"{n_divs} dividend records.")
                done = True
            except Exception as e:
                st.error(f"Couldn't import that file. Make sure it's the right one. ({e})")
            if done:
                st.rerun()

# =====================================================================
# PART 7: LOOK OF THE STOCK BOXES AND FLOATING BUTTON
# =====================================================================
CARD_CSS = """
<style>
.card { background: #ffffff; color: #1f2937; border: 1px solid #d1d5db; border-radius: 12px; padding: 14px 16px; margin-bottom: 6px; box-shadow: 0 1px 4px rgba(0,0,0,0.08); }
.card-top { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 8px; border-bottom: 1px solid #e5e7eb; padding-bottom: 6px; }
.card-symbol { font-size: 1.3rem; font-weight: 700; }
.card-price { font-size: 1.05rem; font-weight: 600; }
.card-row { display: flex; justify-content: space-between; font-size: 0.92rem; padding: 2px 0; }
.up { color: #16a34a; font-weight: 600; }
.down { color: #dc2626; font-weight: 600; }
.flat { color: #6b7280; font-weight: 600; }

div[data-testid="stElementContainer"]:has(#floating-add-marker) + div[data-testid="stElementContainer"] {
    position: fixed !important;
    bottom: 28px !important;
    right: 28px !important;
    z-index: 999999 !important;
    width: auto !important;
}
div[data-testid="stElementContainer"]:has(#floating-add-marker) + div[data-testid="stElementContainer"] button {
    border-radius: 28px !important;
    padding: 12px 24px !important;
    font-size: 1rem !important;
    font-weight: 700 !important;
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.28) !important;
    border: none !important;
}
</style>
"""


def color_class(value):
    if value > 0:
        return "up"
    if value < 0:
        return "down"
    return "flat"


def build_card_html(symbol, shares, avg_price, current_price, div_total):
    if current_price is None:
        price_text = "Price N/A"
        diff_html = '<span class="flat">Waiting for price...</span>'
        pl_html = '<span class="flat">-</span>'
    else:
        diff = current_price - avg_price
        pct = (diff / avg_price * 100) if avg_price > 0 else 0
        cls = color_class(diff)
        price_text = money(current_price)
        diff_html = f'<span class="{cls}">{diff:+,.2f} ({pct:+.2f}%)</span>'
        pl_html = f'<span class="{cls}">{diff * shares:+,.2f} ฿</span>'

    return (
        f'<div class="card">'
        f'<div class="card-top"><span class="card-symbol">{symbol}</span>'
        f'<span class="card-price">{price_text}</span></div>'
        f'<div class="card-row"><span>Shares owned</span><b>{shares:,}</b></div>'
        f'<div class="card-row"><span>Average buy price</span><b>{money(avg_price)}</b></div>'
        f'<div class="card-row"><span>Difference / share</span>{diff_html}</div>'
        f'<div class="card-row"><span>Total profit / loss</span>{pl_html}</div>'
        f'<div class="card-row"><span>Dividends received</span><b>{money(div_total)}</b></div>'
        f'</div>'
    )

# =====================================================================
# PART 8: FIRST PAGE - YOUR STOCK LIST + ALLOCATION PIE CHART
# =====================================================================
def show_allocation_chart(allocation, total_value):
    if not allocation or total_value <= 0:
        return
    st.subheader("🥧 Portfolio allocation")
    df = pd.DataFrame(allocation).sort_values("Value", ascending=False).reset_index(drop=True)
    df["Percent"] = df["Value"] / total_value * 100
    df["Label"] = [f"{s} ({p:.1f}%)" for s, p in zip(df["Stock"], df["Percent"])]

    chart = alt.Chart(df).mark_arc(innerRadius=60).encode(
        theta=alt.Theta("Value:Q"),
        color=alt.Color("Label:N", sort=df["Label"].tolist(),
                        legend=alt.Legend(title="Stock (% of portfolio)")),
        order=alt.Order("Value:Q", sort="descending"),
        tooltip=[
            alt.Tooltip("Stock:N", title="Stock"),
            alt.Tooltip("Value:Q", title="Market value (฿)", format=",.2f"),
            alt.Tooltip("Percent:Q", title="Share of portfolio (%)", format=".1f"),
        ],
    ).properties(height=340)
    st.altair_chart(chart)

    top = df.iloc[0]
    if len(df) > 1 and top["Percent"] > LARGE_HOLDING_PCT:
        st.warning(f"⚠️ {top['Stock']} is {top['Percent']:.1f}% of your portfolio. "
                   f"More than {LARGE_HOLDING_PCT}% in one company is a lot of risk in one place.")


@st.fragment(run_every=REFRESH_SECONDS)
def live_portfolio_cards():
    portfolio = load_portfolio()
    dividends = load_dividends()
    if not portfolio:
        st.info("You don't have any stocks yet. Press **➕ Add Stock** to add one, "
                "or use **📥 Import** below to bring in your data from the computer version.")
        return

    total_value = 0.0
    total_cost = 0.0
    held_div_12m = 0.0
    cards = []
    allocation = []
    for symbol in sorted(portfolio):
        shares, avg, cost = summarize(portfolio[symbol])
        if shares <= 0:
            continue
        price = get_price(symbol)
        value = price * shares if price is not None else cost
        total_cost += cost
        total_value += value
        div_total, div_12m = dividend_totals(dividends.get(symbol, []))
        held_div_12m += div_12m
        cards.append((symbol, build_card_html(symbol, shares, avg, price, div_total)))
        allocation.append({"Stock": symbol, "Value": value})

    all_div_total = sum(dividend_totals(entries)[0] for entries in dividends.values())

    profit = total_value - total_cost
    pct = profit / total_cost * 100 if total_cost else 0
    total_return = profit + all_div_total
    total_return_pct = total_return / total_cost * 100 if total_cost else 0
    yield_pct = held_div_12m / total_cost * 100 if total_cost else 0

    c1, c2, c3 = st.columns(3)
    c1.metric("Total cost", money(total_cost))
    c2.metric("Market value", money(total_value))
    c3.metric("Price gain / loss", f"{profit:+,.2f} ฿", delta=f"{pct:+.2f}%")
    c4, c5, c6 = st.columns(3)
    c4.metric("Dividends received", money(all_div_total),
              help="All dividends you have recorded (after tax).")
    c5.metric("Dividend yield (12 mo)", f"{yield_pct:.2f}%",
              help="Dividends received in the last 12 months ÷ the money you paid for your stocks.")
    c6.metric("Total return", f"{total_return:+,.2f} ฿", delta=f"{total_return_pct:+.2f}%",
              help="Price gain/loss + all dividends received.")

    cols = st.columns(2)
    for i, (symbol, html) in enumerate(cards):
        with cols[i % 2]:
            st.markdown(html, unsafe_allow_html=True)
            if st.button(f"Open {symbol} ›", key=f"open_{symbol}"):
                st.session_state.selected = symbol
                st.session_state.show_add = False
                st.session_state.show_add_div = False
                st.rerun()
            st.write("")

    show_allocation_chart(allocation, total_value)

    now = datetime.now(THAI_TIME).strftime("%H:%M:%S")
    st.caption(f"Last updated {now} (Thai time). Refreshes every {REFRESH_SECONDS} seconds. "
               "Prices from Yahoo Finance (may be delayed ~15 minutes).")


def add_new_stock_form():
    stocks = load_set_symbols()
    symbols = sorted(stocks)
    with st.form("add_new_stock"):
        st.subheader("➕ Add a stock")
        choice = st.selectbox(
            "Stock name (start typing to search)",
            options=symbols,
            index=None,
            placeholder="e.g. PTT, KBANK, CPALL",
            format_func=lambda s: f"{s} — {stocks.get(s, '')}",
        )
        custom = st.text_input("Not in the list? Type the stock symbol here instead (optional)")
        shares = st.number_input("How many shares did you buy?", min_value=1, value=100, step=100)
        price = st.number_input("Price per share when you bought (฿)", min_value=0.01,
                                value=10.00, step=0.25, format="%.2f")
        col_a, col_b = st.columns(2)
        save = col_a.form_submit_button("Save", type="primary")
        cancel = col_b.form_submit_button("Cancel")

    if cancel:
        st.session_state.show_add = False
        st.rerun()

    if save:
        symbol = custom.strip().upper() if custom.strip() else choice
        if not symbol:
            st.error("Please choose a stock from the list or type its symbol.")
            return
        if symbol not in stocks and get_price(symbol) is None:
            st.error(f"Couldn't find '{symbol}' on the Thai stock exchange. Please check the symbol.")
            return
        total_shares, avg, _ = add_purchase(symbol, shares, price)
        st.session_state.flash = (f"Added {int(shares):,} shares of {symbol}. You now own "
                                  f"{total_shares:,} shares at an average price of {money(avg)}.")
        st.session_state.show_add = False
        st.rerun()


def home_page():
    st.title("📈 My Thai Stock Portfolio")
    live_portfolio_cards()
    st.write("")
    import_section()
    if not st.session_state.show_add:
        st.markdown('<div id="floating-add-marker"></div>', unsafe_allow_html=True)
        if st.button("➕ Add Stock", type="primary", key="home_add_btn"):
            st.session_state.show_add = True
            st.rerun()
    else:
        add_new_stock_form()

# =====================================================================
# PART 9: SECOND PAGE - DETAILS, CHART, HISTORY, DIVIDENDS & NEWS
# =====================================================================
@st.fragment(run_every=REFRESH_SECONDS)
def live_stock_summary(symbol):
    entries = load_portfolio().get(symbol, [])
    if not entries:
        return
    shares, avg, cost = summarize(entries)
    price = get_price(symbol)
    div_total, _ = dividend_totals(load_dividends().get(symbol, []))

    c1, c2 = st.columns(2)
    c1.metric("Shares owned", f"{shares:,}")
    c2.metric("Average buy price", money(avg))
    c3, c4 = st.columns(2)
    c5, c6 = st.columns(2)
    c5.metric("Dividends received", money(div_total))
    if price is None:
        c3.metric("Current price", "N/A")
        c4.metric("Price gain / loss", "N/A")
        c6.metric("Total return", "N/A")
    else:
        diff = price - avg
        pct = diff / avg * 100 if avg else 0
        total_return = diff * shares + div_total
        tr_pct = total_return / cost * 100 if cost else 0
        c3.metric("Current price", money(price), delta=f"{diff:+,.2f} ({pct:+.2f}%) vs your avg")
        c4.metric("Price gain / loss", f"{diff * shares:+,.2f} ฿", delta=f"{pct:+.2f}%")
        c6.metric("Total return (price + dividends)", f"{total_return:+,.2f} ฿",
                  delta=f"{tr_pct:+.2f}%")
    now = datetime.now(THAI_TIME).strftime("%H:%M:%S")
    st.caption(f"Last updated {now} (Thai time). Prices may be delayed ~15 minutes.")


def show_price_chart(symbol, avg_price):
    st.subheader("📉 Price history")
    choice = st.radio("Time range", list(PERIOD_OPTIONS), index=3, horizontal=True,
                      key=f"range_{symbol}")
    closes = get_price_history(symbol, PERIOD_OPTIONS[choice])
    if closes is None or len(closes) < 2:
        st.info("Price history isn't available for this stock right now.")
        return

    data = pd.DataFrame({"Date": closes.index, "Price": closes.values})
    price_line = alt.Chart(data).mark_line(color="#2563eb").encode(
        x=alt.X("Date:T", title=None),
        y=alt.Y("Price:Q", title="Price (฿)", scale=alt.Scale(zero=False)),
        tooltip=[
            alt.Tooltip("Date:T", title="Date", format="%d %b %Y"),
            alt.Tooltip("Price:Q", title="Close (฿)", format=",.2f"),
        ],
    )
    avg_line = alt.Chart(pd.DataFrame({"Average": [avg_price]})).mark_rule(
        color="#f59e0b", strokeDash=[6, 4], size=2
    ).encode(y=alt.Y("Average:Q", title="Price (฿)"))
    st.altair_chart((price_line + avg_line).properties(height=320))

    first = float(closes.iloc[0])
    last = float(closes.iloc[-1])
    change_pct = (last - first) / first * 100 if first else 0
    a, b, c = st.columns(3)
    a.metric(f"Change over {choice}", f"{change_pct:+.2f}%")
    b.metric("Highest", money(float(closes.max())))
    c.metric("Lowest", money(float(closes.min())))
    st.caption("Blue line = market closing price. Orange dashed line = your average buy price. "
               "When the blue line is above the orange line, you are in profit.")


def add_more_form(symbol):
    current = get_price(symbol)
    default_price = max(round(current, 2), 0.01) if current else 1.00
    with st.form(f"add_more_{symbol}"):
        st.subheader(f"➕ Add more {symbol}")
        shares = st.number_input("How many more shares did you buy?", min_value=1, value=100, step=100)
        price = st.number_input("Price per share (฿)", min_value=0.01,
                                value=float(default_price), step=0.25, format="%.2f")
        col_a, col_b = st.columns(2)
        save = col_a.form_submit_button("Add", type="primary")
        cancel = col_b.form_submit_button("Cancel")

    if cancel:
        st.session_state.show_add = False
        st.rerun()

    if save:
        old_shares, old_avg, _ = summarize(load_portfolio().get(symbol, []))
        new_shares, new_avg, _ = add_purchase(symbol, shares, price)
        st.session_state.flash = (
            f"Added {int(shares):,} shares at {money(price)}. "
            f"Total shares: {old_shares:,} → {new_shares:,}. "
            f"Average price: {money(old_avg)} → {money(new_avg)}."
        )
        st.session_state.show_add = False
        st.rerun()


def add_dividend_form(symbol, shares_owned):
    today = datetime.now(THAI_TIME).date()
    with st.form(f"add_div_{symbol}"):
        st.subheader(f"💰 Record a {symbol} dividend")
        per_share = st.number_input("Dividend per share (฿)", min_value=0.0001, value=0.50,
                                    step=0.05, format="%.4f")
        shares = st.number_input("How many shares received this dividend?", min_value=1,
                                 value=max(int(shares_owned), 1), step=100)
        pay_date = st.date_input("Payment date", value=today, max_value=today)
        subtract_tax = st.checkbox("Subtract 10% withholding tax (usual for Thai dividends)",
                                   value=True)
        col_a, col_b = st.columns(2)
        save = col_a.form_submit_button("Save dividend", type="primary")
        cancel = col_b.form_submit_button("Cancel")

    if cancel:
        st.session_state.show_add_div = False
        st.rerun()

    if save:
        net = add_dividend(symbol, per_share, shares, pay_date, subtract_tax)
        tax_note = " minus 10% tax" if subtract_tax else ""
        st.session_state.flash = (f"Recorded a {symbol} dividend of {money(net)} "
                                  f"({int(shares):,} shares × {money_precise(per_share)}{tax_note}).")
        st.session_state.show_add_div = False
        st.rerun()


def show_dividend_section(symbol, shares, cost):
    st.subheader("💰 Dividends")
    entries = load_dividends().get(symbol, [])
    div_total, div_12m = dividend_totals(entries)
    yield_on_cost = div_12m / cost * 100 if cost else 0

    a, b = st.columns(2)
    a.metric("Total dividends received", money(div_total))
    b.metric("Yield on your cost (12 mo)", f"{yield_on_cost:.2f}%",
             help="Dividends from the last 12 months ÷ what you paid for this stock.")

    market_dps = get_market_dividend_12m(symbol)
    price = get_price(symbol)
    if market_dps and price:
        st.caption(f"According to Yahoo Finance, {symbol} paid about {money_precise(market_dps)} per share "
                   f"in the last 12 months, about {market_dps / price * 100:.2f}% of today's price. "
                   f"If that stays the same, your {shares:,} shares would earn about "
                   f"{money(market_dps * shares)} a year before tax.")

    if entries:
        h1, h2, h3, h4, h5 = st.columns([3, 2, 2, 2, 1])
        h1.markdown("**Pay date**")
        h2.markdown("**Per share**")
        h3.markdown("**Shares**")
        h4.markdown("**Received**")
        for i in reversed(range(len(entries))):
            d = entries[i]
            c1, c2, c3, c4, c5 = st.columns([3, 2, 2, 2, 1])
            c1.write(d.get("date", "-"))
            c2.write(money_precise(float(d.get("per_share", 0))))
            c3.write(f'{int(d.get("shares", 0)):,}')
            c4.write(money(float(d.get("net", 0))))
            with c5.popover("🗑️"):
                st.write("Delete this dividend?")
                if st.button("Yes, delete", key=f"deldiv_{symbol}_{i}"):
                    delete_dividend(symbol, i)
                    st.rerun()
    else:
        st.caption("No dividends recorded yet.")

    if not st.session_state.show_add_div:
        if st.button("💰 Record a dividend", key="div_add_btn"):
            st.session_state.show_add_div = True
            st.session_state.show_add = False
            st.rerun()
    else:
        add_dividend_form(symbol, shares)


def go_home():
    st.session_state.selected = None
    st.session_state.show_add = False
    st.session_state.show_add_div = False


def detail_page(symbol):
    if st.button("⬅ Back to my portfolio"):
        go_home()
        st.rerun()

    entries = load_portfolio().get(symbol, [])
    if not entries:
        st.warning(f"You don't own any {symbol} yet.")
        return

    stocks = load_set_symbols()
    st.title(f"📊 {symbol}")
    if symbol in stocks:
        st.caption(stocks[symbol])

    shares, avg, cost = summarize(entries)

    live_stock_summary(symbol)
    st.divider()

    show_price_chart(symbol, avg)
    st.divider()

    st.subheader("🕒 Purchase history")
    h1, h2, h3, h4, h5 = st.columns([3, 2, 2, 2, 1])
    h1.markdown("**Date & time**")
    h2.markdown("**Shares**")
    h3.markdown("**Price**")
    h4.markdown("**Cost**")
    for i in reversed(range(len(entries))):
        e = entries[i]
        c1, c2, c3, c4, c5 = st.columns([3, 2, 2, 2, 1])
        c1.write(e["time"])
        c2.write(f'{e["shares"]:,}')
        c3.write(money(e["price"]))
        c4.write(money(e["shares"] * e["price"]))
        with c5.popover("🗑️"):
            st.write("Delete this entry?")
            if st.button("Yes, delete", key=f"del_{symbol}_{i}"):
                still_has = delete_entry(symbol, i)
                if not still_has:
                    go_home()
                    st.session_state.flash = f"All {symbol} entries removed."
                st.rerun()

    st.divider()
    show_dividend_section(symbol, shares, cost)
    st.divider()

    st.subheader(f"📰 Business & Performance News for {symbol}")
    news_items = get_filtered_news(symbol, stocks.get(symbol, ""))
    if not news_items:
        st.info("No market performance or business trend news found recently.")
    else:
        for item in news_items:
            badge = "🔥 **[Market Focus]** " if item["highlight"] else ""
            st.markdown(f"- {badge}[{item['title']}]({item['link']}) — *({item['source']})*")

    st.divider()
    if not st.session_state.show_add:
        st.markdown('<div id="floating-add-marker"></div>', unsafe_allow_html=True)
        if st.button("➕ Add more", type="primary", key="detail_add_btn"):
            st.session_state.show_add = True
            st.session_state.show_add_div = False
            st.rerun()
    else:
        add_more_form(symbol)

# =====================================================================
# PART 10: PASSWORD SCREEN AND GOOGLE SHEET CONNECTION CHECK
# =====================================================================
def check_password():
    if st.session_state.get("logged_in"):
        return True
    try:
        correct = str(st.secrets["app_password"])
    except Exception:
        correct = ""
    if not correct:
        st.error("No password has been set. Add app_password in the app's Secrets settings.")
        st.stop()

    st.title("🔒 My Thai Stock Portfolio")
    with st.form("login_form"):
        typed = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Log in", type="primary")
    if submitted:
        if hmac.compare_digest(typed.encode("utf-8"), correct.encode("utf-8")):
            st.session_state.logged_in = True
            st.rerun()
        st.error("Wrong password. Please try again.")
    return False


def check_google_sheet():
    try:
        get_worksheet("purchases")
        get_worksheet("dividends")
    except Exception as e:
        st.error("Couldn't open your Google Sheet. Check that: (1) the Secrets are pasted correctly, "
                 "(2) the sheet is shared with the robot email as Editor, "
                 "(3) Google Sheets API is enabled.")
        st.caption(f"Technical details: {type(e).__name__}: {e}")
        st.stop()

# =====================================================================
# PART 11: START THE APP AND DECIDE WHICH PAGE TO SHOW
# =====================================================================
for key, default in [("show_add", False), ("show_add_div", False), ("selected", None)]:
    if key not in st.session_state:
        st.session_state[key] = default

st.markdown(CARD_CSS, unsafe_allow_html=True)

if not check_password():
    st.stop()

check_google_sheet()

if "flash" in st.session_state:
    st.success(st.session_state.pop("flash"))

if st.session_state.selected:
    detail_page(st.session_state.selected)
else:
    home_page()