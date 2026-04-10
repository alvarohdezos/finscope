from http.server import BaseHTTPRequestHandler
import json, os, urllib.parse, urllib.request, time
from concurrent.futures import ThreadPoolExecutor

FINNHUB = os.environ.get('FINNHUB_KEY', '')
OPENAI  = os.environ.get('OPENAI_KEY', '')

YF_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Accept': 'application/json,text/plain,*/*',
    'Accept-Language': 'en-US,en;q=0.9',
    'Referer': 'https://finance.yahoo.com/',
}

# ── Finnhub ───────────────────────────────────────────────────────────────────
def fh(path, params, timeout=12):
    params['token'] = FINNHUB
    url = 'https://finnhub.io/api/v1/' + path + '?' + urllib.parse.urlencode(params)
    try:
        req = urllib.request.Request(url, headers={'Accept':'application/json','User-Agent':'FINscope/2.0'})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except:
        return {}

# ── FRED ──────────────────────────────────────────────────────────────────────
def fred(series_id):
    try:
        url = f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}'
        req = urllib.request.Request(url, headers={'User-Agent':'FINscope/2.0'})
        with urllib.request.urlopen(req, timeout=8) as r:
            lines = r.read().decode().strip().split('\n')
            for line in reversed(lines):
                parts = line.split(',')
                if len(parts)==2 and parts[1].strip() not in ('','.','.'):
                    try: return float(parts[1].strip())
                    except: continue
    except:
        pass
    return None

def get_macro():
    try:
        with ThreadPoolExecutor(max_workers=3) as ex:
            futs = {
                'treasury_10y': ex.submit(fred, 'DGS10'),
                'fed_funds':    ex.submit(fred, 'FEDFUNDS'),
                'vix':          ex.submit(fred, 'VIXCLS'),
            }
            res = {k: v.result() for k, v in futs.items()}
        return {
            'risk_free_rate':   res.get('treasury_10y') or 4.42,
            'policy_rate':      res.get('fed_funds') or 5.33,
            'cpi_yoy':          3.2,
            'pmi_composite':    51.0,
            'credit_spread_hy': 320,
            'vix':              res.get('vix') or 18.0,
            'macro_note': 'Federal Reserve holding rates; inflation moderating toward 2% target.'
        }
    except:
        return {'risk_free_rate':4.42,'policy_rate':5.33,'cpi_yoy':3.2,
                'pmi_composite':51.0,'credit_spread_hy':320,'vix':18.0,
                'macro_note':'Macro data temporarily unavailable.'}

# ── Yahoo Finance direct (no yfinance library) ────────────────────────────────
def _yf_get(url, timeout=12):
    """Raw urllib call to Yahoo Finance with browser headers."""
    req = urllib.request.Request(url, headers=YF_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8'))

def _yv(d, key):
    """Extract raw numeric value from Yahoo Finance dict or plain number."""
    v = d.get(key)
    if v is None: return None
    if isinstance(v, dict): return v.get('raw')
    return v

def get_yahoo_data(ticker):
    """
    Direct Yahoo Finance API calls — no yfinance library.
    Two endpoints: quoteSummary (fundamentals) + chart (historical closes).
    Tries query1 then query2 as fallback for each.
    """
    summary = {}
    closes  = []

    # ── 1. Fundamentals via quoteSummary ──
    modules = 'defaultKeyStatistics,financialData,summaryDetail,recommendationTrend,price'
    for host in ['query2', 'query1']:
        try:
            url = (f'https://{host}.finance.yahoo.com/v10/finance/quoteSummary/{ticker}'
                   f'?modules={modules}&corsDomain=finance.yahoo.com&formatted=true')
            data = _yf_get(url, timeout=12)
            result = data.get('quoteSummary', {}).get('result') or []
            if result:
                summary = result[0]
                break
        except:
            continue

    # ── 2. Historical closes via chart (for RSI/MACD/SMA) ──
    for host in ['query1', 'query2']:
        try:
            url = (f'https://{host}.finance.yahoo.com/v8/finance/chart/{ticker}'
                   f'?interval=1d&range=1y&includePrePost=false')
            data = _yf_get(url, timeout=12)
            raw_closes = (data.get('chart', {})
                             .get('result', [{}])[0]
                             .get('indicators', {})
                             .get('quote', [{}])[0]
                             .get('close', []))
            closes = [c for c in raw_closes if c is not None]
            if closes:
                break
        except:
            continue

    # ── Extract from summary sections ──
    fd = summary.get('financialData',      {})
    ks = summary.get('defaultKeyStatistics',{})
    sd = summary.get('summaryDetail',      {})
    pr = summary.get('price',              {})
    rt = summary.get('recommendationTrend',{})

    ev_ebitda    = _yv(ks, 'enterpriseToEbitda')
    fcf_raw      = _yv(fd, 'freeCashflow')
    rev          = _yv(fd, 'totalRevenue')
    net_margin   = _yv(fd, 'profitMargins')
    if net_margin   is not None: net_margin   = round(net_margin   * 100, 1)
    op_margin    = _yv(fd, 'operatingMargins')
    if op_margin    is not None: op_margin    = round(op_margin    * 100, 1)
    gross_margin = _yv(fd, 'grossMargins')
    if gross_margin is not None: gross_margin = round(gross_margin * 100, 1)
    roe          = _yv(fd, 'returnOnEquity')
    if roe          is not None: roe          = round(roe          * 100, 1)
    roa          = _yv(fd, 'returnOnAssets')
    if roa          is not None: roa          = round(roa          * 100, 1)
    rev_growth   = _yv(fd, 'revenueGrowth')
    if rev_growth   is not None: rev_growth   = round(rev_growth   * 100, 1)
    current_ratio= _yv(fd, 'currentRatio')
    quick_ratio  = _yv(fd, 'quickRatio')
    target_mean  = _yv(fd, 'targetMeanPrice')
    current_price= _yv(fd, 'currentPrice') or _yv(pr, 'regularMarketPrice')

    pe_ttm    = _yv(sd, 'trailingPE')
    pe_forward= _yv(ks, 'forwardPE')
    pb        = _yv(ks, 'priceToBook')
    eps_ttm   = _yv(ks, 'trailingEps')
    beta      = _yv(sd, 'beta') or _yv(ks, 'beta')
    week52h   = _yv(sd, 'fiftyTwoWeekHigh')
    week52l   = _yv(sd, 'fiftyTwoWeekLow')

    div_yield = _yv(sd, 'dividendYield')
    if div_yield is not None: div_yield = round(div_yield * 100, 2)

    de = _yv(ks, 'debtToEquity')
    if de is not None and de > 10: de = de / 100

    market_cap = _yv(pr, 'marketCap')
    if market_cap: market_cap = market_cap / 1e6

    fcf_str    = None
    fcf_margin = None
    if fcf_raw is not None:
        fcf_str = f"${fcf_raw/1e9:.1f}B" if abs(fcf_raw) >= 1e9 else f"${fcf_raw/1e6:.0f}M"
        if rev and rev > 0:
            fcf_margin = round(fcf_raw / rev * 100, 1)

    upside = None
    if target_mean and current_price and current_price > 0:
        upside = round((target_mean - current_price) / current_price * 100, 1)

    # Analyst recs from recommendationTrend
    sb = b = h = se = ss = 0
    try:
        trend_list = rt.get('trend', [])
        if trend_list:
            latest = trend_list[0]
            sb = int(latest.get('strongBuy',   0) or 0)
            b  = int(latest.get('buy',         0) or 0)
            h  = int(latest.get('hold',        0) or 0)
            se = int(latest.get('sell',        0) or 0)
            ss = int(latest.get('strongSell',  0) or 0)
    except:
        pass

    # Technical indicators from historical closes
    rsi_val    = calc_rsi(closes)   if len(closes) >= 15 else None
    macd_val   = calc_macd(closes)  if len(closes) >= 35 else None
    sma50_val  = calc_sma(closes, 50)
    sma200_val = calc_sma(closes, 200)

    return {
        'rsi': rsi_val, 'macd': macd_val,
        'sma50': sma50_val, 'sma200': sma200_val,
        'ev_ebitda':    ev_ebitda,
        'fcf_raw':      fcf_raw,  'fcf_str':    fcf_str,  'fcf_margin': fcf_margin,
        'de':           de,       'div_yield':  div_yield,
        'pe_ttm':       pe_ttm,   'pe_forward': pe_forward, 'pb': pb,
        'net_margin':   net_margin,   'op_margin':   op_margin,
        'gross_margin': gross_margin, 'roe':         roe, 'roa': roa,
        'rev_growth':   rev_growth,   'eps_ttm':     eps_ttm,
        'current_ratio':current_ratio,'quick_ratio': quick_ratio,
        'beta':         beta,         'week52_high': week52h, 'week52_low': week52l,
        'market_cap':   market_cap,
        'target_price': target_mean,  'upside':      upside,
        'analyst_sb':   sb, 'analyst_b': b, 'analyst_h': h,
        'analyst_se':   se, 'analyst_ss': ss,
    }

# ── Technical indicators ──────────────────────────────────────────────────────
def calc_rsi(c, p=14):
    if len(c) < p + 1: return None
    ag = al = 0.0
    for i in range(1, p + 1):
        d = c[i] - c[i-1]; ag += max(d, 0); al += max(-d, 0)
    ag /= p; al /= p
    for i in range(p + 1, len(c)):
        d = c[i] - c[i-1]
        ag = (ag * (p-1) + max(d, 0)) / p
        al = (al * (p-1) + max(-d, 0)) / p
    return round(100 - 100 / (1 + ag / al), 1) if al else 100.0

def calc_ema(c, p):
    if len(c) < p: return None
    k = 2 / (p + 1); e = sum(c[:p]) / p
    for x in c[p:]: e = x * k + e * (1 - k)
    return e

def calc_macd(c):
    if len(c) < 35: return None
    e12 = calc_ema(c, 12); e26 = calc_ema(c, 26)
    return round(e12 - e26, 3) if e12 and e26 else None

def calc_sma(c, p):
    return round(sum(c[-p:]) / p, 2) if len(c) >= p else None

# ── Metric resolution ─────────────────────────────────────────────────────────
def resolve(fh_val, yf_val):
    if fh_val is not None:
        try: return float(fh_val)
        except: pass
    if yf_val is not None:
        try: return float(yf_val)
        except: pass
    return None

def gm(m, *keys):
    for k in keys:
        v = m.get(k)
        if v is not None:
            try: return float(v)
            except: pass
    return None

def get_de_fh(m):
    raw = gm(m, 'totalDebt/totalEquityAnnual', 'totalDebt/totalEquityQuarterly',
              'debtToEquityAnnual', 'longTermDebt/equityAnnual')
    if raw is None: return None
    return float(raw) / 100 if float(raw) > 10 else float(raw)

def get_rev_growth(m):
    v = gm(m, 'revenueGrowthTTMYoy', 'revenueGrowthQuarterlyYoy', 'revenueGrowth3Y')
    if v is None: return None
    return float(v) * 100 if abs(float(v)) < 3 else float(v)

def get_eps_growth(m):
    v = gm(m, 'epsGrowthTTMYoy', 'epsGrowthQuarterlyYoy', 'epsGrowth3Y')
    if v is None: return None
    return float(v) * 100 if abs(float(v)) < 3 else float(v)

# ── Composite score ───────────────────────────────────────────────────────────
def compute_score(pm, om, roe, roa, rg, de, cr, fcf_raw,
                  rsi, s50, s200, macd, sb, b, h, se, ss, tp, price):
    f = 17.5
    if pm  is not None: f += 7 if pm>25  else 5 if pm>15  else 2 if pm>8   else (-5 if pm<0   else 0)
    if om  is not None: f += 6 if om>30  else 4 if om>20  else 2 if om>10  else (-4 if om<0   else 0)
    if roe is not None: f += 6 if roe>30 else 3 if roe>15 else (-4 if roe<0 else 0)
    if roa is not None: f += 4 if roa>15 else 2 if roa>8  else (-2 if roa<0 else 0)
    if rg  is not None: f += 6 if rg>20  else 3 if rg>10  else 1 if rg>0  else -4
    f = max(0, min(35, f))

    t = 12.5
    if rsi is not None:
        t += 6 if 40<=rsi<=65 else 2 if 30<=rsi<40 else 2 if 65<rsi<=75 else (-4 if rsi>75 else -2)
    if s50 and s200: t += 6 if s50 > s200 else -4
    if macd is not None: t += 5 if macd > 0 else -3
    t = max(0, min(25, t))

    a = 12.5
    total = (sb or 0)+(b or 0)+(h or 0)+(se or 0)+(ss or 0)
    if total > 0:
        br = (sb+b)/total; sr = (se+ss)/total
        a += 10 if br>0.7 else 6 if br>0.5 else 2 if br>0.3 else 0
        a -= 8  if sr>0.5 else 4 if sr>0.3 else 0
    if tp and price and price > 0:
        up = (tp-price)/price*100
        a += 5 if up>20 else 2 if up>10 else 1 if up>0 else (-5 if up<-10 else -2)
    a = max(0, min(25, a))

    acc = 7.5
    if de  is not None: acc += 4 if de<0.3 else 2 if de<1 else (-4 if de>3 else -2 if de>2 else 0)
    if cr  is not None: acc += 3 if cr>2   else 1 if cr>1.2 else (-3 if 0<cr<1 else 0)
    if fcf_raw is not None: acc += 2 if float(fcf_raw) > 0 else -2
    acc = max(0, min(15, acc))

    total_score = max(5, min(98, round(f+t+a+acc)))
    return {'total': total_score, 'fundamental': round(f),
            'technical': round(t), 'analyst': round(a), 'accounting': round(acc)}

def calc_altman(m, yf):
    try:
        roa = resolve(gm(m,'roaAnnual','roaTTM'), yf.get('roa')) or 0
        at  = gm(m,'assetTurnoverAnnual','assetTurnoverTTM') or 0.8
        cr  = resolve(gm(m,'currentRatioAnnual','currentRatioQuarterly'), yf.get('current_ratio')) or 1
        de  = resolve(get_de_fh(m), yf.get('de')) or 1.0
        roa = roa/100 if roa > 1 else roa
        x1 = max(0, (cr-1)*0.25); x2 = max(0, roa*0.4)
        x3 = max(0, roa*1.3);     x4 = min(5.0, 1/de) if de > 0 else 3.0
        return round(1.2*x1 + 1.4*x2 + 3.3*x3 + 0.6*x4 + at, 2)
    except: return None

def altman_zone(z):
    if z is None: return 'N/A'
    return 'Safe (Z>3)' if z > 2.99 else 'Grey zone' if z > 1.81 else 'Distress (Z<1.8)'

def calc_piotroski(m, yf):
    s = 0
    roa  = resolve(gm(m,'roaAnnual','roaTTM'), yf.get('roa')) or 0
    fcf  = yf.get('fcf_raw') or gm(m,'freeCashFlowAnnual','freeCashFlowTTM') or 0
    pm   = resolve(gm(m,'netMarginAnnual','netMarginTTM','netProfitMarginAnnual'), yf.get('net_margin')) or 0
    fcfm = resolve(gm(m,'fcfMarginAnnual','fcfMarginTTM'), yf.get('fcf_margin')) or 0
    gma  = gm(m,'grossMarginAnnual') or 0
    gmt  = resolve(gm(m,'grossMarginTTM'), yf.get('gross_margin')) or 0
    ata  = gm(m,'assetTurnoverAnnual') or 0
    att  = gm(m,'assetTurnoverTTM') or 0
    cra  = gm(m,'currentRatioAnnual') or 0
    crq  = resolve(gm(m,'currentRatioQuarterly'), yf.get('current_ratio')) or 0
    de   = resolve(get_de_fh(m), yf.get('de')) or 0
    rg   = resolve(get_rev_growth(m), yf.get('rev_growth')) or 0
    eg   = get_eps_growth(m) or 0
    if roa > 0: s+=1
    if float(fcf) > 0: s+=1
    if gm(m,'roaTTM') and (gm(m,'roaTTM') or 0) >= roa*0.9: s+=1
    if fcfm > pm: s+=1
    if de < 1.0: s+=1
    if crq >= cra: s+=1
    if eg >= rg*0.9: s+=1
    if gmt >= gma: s+=1
    if att >= ata*0.95: s+=1
    return min(9, s)

def piotroski_label(f):
    return 'Strong quality' if f>=7 else 'Moderate quality' if f>=4 else 'Weak signals'

# ── OpenAI system prompt ──────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are a senior equity analyst at Goldman Sachs Equity Research with 15 years of cross-sector experience. Produce institutional-grade, decisive investment analysis. Every sentence containing analysis MUST include at least one specific number. Never hedge. Be direct and decisive.

WACC BENCHMARKS BY SECTOR (base: risk_free_rate 3.5-4.5%; adjust +0.5-1.0pp if >4.5%):
UTILITIES — 5.0-6.5% | REITS — 5.5-7.0% | CONSUMER STAPLES — 6.0-7.5% | TELECOM — 6.5-8.5% | HEALTHCARE DEVICES — 7.5-9.5% | INDUSTRIALS AERO — 7.0-9.0% | INDUSTRIALS DIV — 7.5-9.5% | TRANSPORT — 7.5-9.5% | LUXURY — 7.5-9.5% | RETAIL — 8.5-11.0% | TRAVEL/LEISURE — 9.5-13.0% | BANKS (use ROE vs CoE 10-13%, NOT WACC; Z-Score invalid) | INSURANCE — 8.0-10.5% | ASSET MGMT/FINTECH — 9.0-12.0% | ENERGY MAJORS — 8.0-10.0% | ENERGY E&P — 10.0-14.0% | RENEWABLES — 7.5-10.0% | MATERIALS — 9.0-12.0% | BIG PHARMA — 8.0-9.0% | SPECIALTY PHARMA — 9.0-10.5% | BIOTECH PRE-REV — 12.0-18.0% (ROIC N/A) | SEMIS FABLESS — 10.0-12.0% | SEMIS IDM — 9.5-10.5% | SOFTWARE/SAAS — 9.0-12.0% (Rule of 40 benchmark) | HARDWARE — 10.0-13.0% | INTERNET/PLATFORMS — 9.5-12.0%

ANALYTICAL RULES:
- ROIC vs sector WACC: below WACC = value-destructive; above WACC by 5pp+ = durable advantage
- VIX <15 low risk premium; 15-25 normal; >25 elevated — discount high-duration assets
- Rate-sensitive sectors: 1pp rate rise compresses fair value ~10-15%
- FCF yield <2% = expensive; >6% = value territory
- Altman Z: >2.99 safe; 1.81-2.99 grey; <1.81 distress (NOT valid for banks/financials)
- Piotroski F: 7-9 improving; 4-6 neutral; 0-3 deteriorating
- RSI >70 overbought; <30 oversold. SMA50 > SMA200 = uptrend. If all technical N/A: state in one sentence only
- Analyst count <5: flag as low statistical weight. Hold >50% = functionally sell signal
- PEG >2.0 expensive; <1.0 potentially undervalued
- Rule of 40 for SaaS: revenue growth% + FCF margin% >= 40 = quality benchmark

WORD COUNT REQUIREMENTS — NON-NEGOTIABLE:
- capital: exactly 5 sentences. cashflow: exactly 5 sentences. analyst_view: exactly 4 sentences.
- solvency: exactly 4 sentences. risks: exactly 5 sentences. credit_decision: exactly 2 sentences.
- Every sentence must contain at least 1 specific number. Do NOT truncate any field.

CRITICAL OUTPUT RULES:
- verdict: capitalize first letter. verdict_color: green|yellow|red|gray. verdict_icon: bull|bear|neutral|watch
- methodology_notes: exactly 3 caveats specific to THIS ticker
- Return ONLY valid JSON, no markdown, no preamble

{"verdict":"Capitalized verdict with key number","verdict_sub":"1 sentence thesis with 2+ numbers","verdict_color":"green|yellow|red|gray","verdict_icon":"bull|bear|neutral|watch","capital":"5 sentences: PE vs sector, FCF yield, ROIC vs WACC, margin trend, valuation — every sentence with a number","cashflow":"5 sentences: FCF absolute and yield, FCF vs net income, capex priorities, cash conversion, working capital — numbers in every sentence","technical":"3 sentences: RSI with value, SMA50 vs SMA200 with values, MACD signal. If all N/A: 1 sentence only","analyst_view":"4 sentences: analyst count, buy/hold/sell % with exact counts, consensus target price, upside vs fundamentals","solvency":"4 sentences: Altman Z exact value and zone, Piotroski F exact score and tier, D/E vs sector norm, refinancing risk","risks":"5 sentences: valuation risk with multiple, operational risk with data, macro risk from VIX/rates, competitive risk, structural risk — each with a number","credit_decision":"2 sentences: FCF coverage, Z-Score context, explicit lend/no-lend","retail_summary":{"what_they_do":"2 sentences plain language, main revenue source","price_story":"2 sentences: RSI trend and SMA meaning in plain terms, or N/A if unavailable","is_it_cheap":"2 sentences: PE vs sector, FCF yield as $ per $100 invested","making_money":"2 sentences: net margin as keeps $X per $100 revenue","debt_plain":"2 sentences: debt without jargon, vs peers","main_risk_plain":"2 sentences: top 2 risks with 1 data point each","analyst_take_plain":"2 sentences: exact buy/hold/sell counts, target price","verdict_plain":"1 sentence with 1 number ending in: buy, hold, or avoid."},"methodology_notes":["Caveat 1 specific to this ticker","Caveat 2","Caveat 3"]}"""

# ── OpenAI call ───────────────────────────────────────────────────────────────
def call_openai(ticker, name, industry, price, mc, macro, sc, z, fs):
    user_data = {
        "company": {
            "name": name, "ticker": ticker, "sector": industry, "price": price,
            "market_cap_m":       mc.get('market_cap'),
            "pe_ttm":             mc.get('pe_ttm'),
            "pe_forward":         mc.get('pe_forward'),
            "pb":                 mc.get('pb'),
            "beta":               mc.get('beta'),
            "gross_margin":       mc.get('gross_margin'),
            "operating_margin":   mc.get('op_margin'),
            "net_margin":         mc.get('net_margin'),
            "roe":                mc.get('roe'),
            "roa":                mc.get('roa'),
            "roic":               mc.get('roic'),
            "revenue_growth":     mc.get('rev_growth'),
            "eps_growth":         mc.get('eps_growth'),
            "eps_ttm":            mc.get('eps_ttm'),
            "fcf":                mc.get('fcf_str'),
            "fcf_margin":         mc.get('fcf_margin'),
            "debt_equity":        mc.get('de'),
            "current_ratio":      mc.get('current_ratio'),
            "quick_ratio":        mc.get('quick_ratio'),
            "div_yield":          mc.get('div_yield'),
            "ev_ebitda":          mc.get('ev_ebitda'),
            "altman_z":           z,
            "altman_zone":        altman_zone(z),
            "piotroski_f":        fs,
            "rsi":                mc.get('rsi'),
            "macd":               mc.get('macd'),
            "sma50":              mc.get('sma50'),
            "sma200":             mc.get('sma200'),
            "technical_trend":    ('BULLISH' if mc.get('sma50') and mc.get('sma200') and mc['sma50']>mc['sma200']
                                    else 'BEARISH' if mc.get('sma50') and mc.get('sma200') else 'N/A'),
            "analyst_strong_buy": mc.get('analyst_sb', 0),
            "analyst_buy":        mc.get('analyst_b',  0),
            "analyst_hold":       mc.get('analyst_h',  0),
            "analyst_sell":       mc.get('analyst_se', 0),
            "analyst_strong_sell":mc.get('analyst_ss', 0),
            "analyst_total":      sum(mc.get(k,0) for k in ['analyst_sb','analyst_b','analyst_h','analyst_se','analyst_ss']),
            "consensus_target":   mc.get('target_price'),
            "consensus_upside":   mc.get('upside'),
            "composite_score":    sc['total'],
            "score_fundamental":  sc['fundamental'],
            "score_technical":    sc['technical'],
            "score_analyst":      sc['analyst'],
            "score_accounting":   sc['accounting'],
            "week52_high":        mc.get('week52_high'),
            "week52_low":         mc.get('week52_low'),
        },
        "macro": macro
    }
    try:
        payload = json.dumps({
            'model': 'gpt-4o-mini', 'max_tokens': 2500,
            'messages': [
                {'role': 'system', 'content': SYSTEM_PROMPT},
                {'role': 'user',   'content': json.dumps(user_data)}
            ]
        }).encode()
        req = urllib.request.Request(
            'https://api.openai.com/v1/chat/completions', data=payload,
            headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {OPENAI}'}
        )
        with urllib.request.urlopen(req, timeout=55) as r:
            data   = json.loads(r.read())
            text   = data['choices'][0]['message']['content']
            result = json.loads(text.replace('```json','').replace('```','').strip())
            if result.get('verdict'):
                result['verdict'] = result['verdict'][0].upper() + result['verdict'][1:]
            return result
    except Exception as e:
        return _fallback(name, mc, sc, z, fs)

def _fallback(name, m, sc, z, fs):
    sv  = sc['total']
    col = 'green' if sv>=70 else 'red' if sv<50 else 'yellow'
    icon= 'bull'  if sv>=70 else 'bear' if sv<50 else 'neutral'
    pm  = m.get('net_margin') or 0; de = m.get('de') or 0
    roe = m.get('roe') or 0;        rg = m.get('rev_growth') or 0
    total_a = sum(m.get(k,0) for k in ['analyst_sb','analyst_b','analyst_h','analyst_se','analyst_ss'])
    v = f"Score {sv}/100 — net margin {pm:.1f}%, ROE {roe:.1f}%"
    return {
        'verdict': v[0].upper()+v[1:], 'verdict_sub': f"Composite {sv}/100 · D/E {de:.2f}x.",
        'verdict_color': col, 'verdict_icon': icon,
        'capital': f"D/E {de:.2f}x leverage. ROE {roe:.1f}%. Score {sv}/100.",
        'cashflow': f"Net margin {pm:.1f}%. Revenue growth {rg:.1f}%.",
        'technical': "Technical indicators N/A — candle data unavailable.",
        'analyst_view': f"{m.get('analyst_sb',0)+m.get('analyst_b',0)}/{total_a} Buy.",
        'solvency': f"Altman Z {z or 'N/A'} ({altman_zone(z)}). Piotroski F {fs}/9.",
        'risks': f"D/E {de:.2f}x. Revenue growth {rg:.1f}%.",
        'credit_decision': f"D/E {de:.2f}x, net margin {pm:.1f}%.",
        'retail_summary': {
            'what_they_do': f"{name}.", 'price_story': "Technical data N/A.",
            'is_it_cheap': f"Score {sv}/100.", 'making_money': f"Keeps ${pm:.1f} per $100 revenue.",
            'debt_plain': f"D/E {de:.2f}x.", 'main_risk_plain': f"Revenue growth {rg:.1f}%.",
            'analyst_take_plain': f"{m.get('analyst_sb',0)+m.get('analyst_b',0)} Buy of {total_a}.",
            'verdict_plain': f"Score {sv}/100."
        },
        'methodology_notes': [
            "Technical indicators N/A — candle data unavailable on free tier.",
            "Beta period unspecified — treat as indicative only.",
            "Fallback mode — OpenAI call failed. Retry for full report."
        ]
    }

# ── Main analysis ─────────────────────────────────────────────────────────────
def analyse(ticker):
    # 7 parallel Finnhub calls + macro
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {
            'profile': ex.submit(fh, 'stock/profile2', {'symbol': ticker}),
            'quote':   ex.submit(fh, 'quote',          {'symbol': ticker}),
            'metrics': ex.submit(fh, 'stock/metric',   {'symbol': ticker, 'metric': 'all'}),
            'recs':    ex.submit(fh, 'stock/recommendation-trends', {'symbol': ticker}),
            'target':  ex.submit(fh, 'stock/price-target', {'symbol': ticker}),
            'earnings':ex.submit(fh, 'stock/earnings', {'symbol': ticker}),
            'macro':   ex.submit(get_macro),
        }
        res = {k: v.result() for k, v in futs.items()}

    profile = res['profile']
    if not profile.get('name'):
        raise Exception(f'Ticker "{ticker}" not found. Try AAPL, NVDA, MSFT, JPM.')

    quote    = res['quote']
    m_fh     = res['metrics'].get('metric', {})
    recs     = res['recs']     if isinstance(res['recs'],     list) else []
    target   = res['target']   if isinstance(res['target'],   dict) else {}
    earnings = res['earnings'] if isinstance(res['earnings'], list) else []
    macro    = res['macro']

    # Yahoo Finance direct — sequential, 20s timeout
    import concurrent.futures as cf
    with cf.ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(get_yahoo_data, ticker)
        try:    yf = fut.result(timeout=20) or {}
        except: yf = {}

    price   = quote.get('c')
    change  = quote.get('d')
    chg_pct = quote.get('dp')

    # Technical — Yahoo primary
    rsi    = yf.get('rsi')
    macd   = yf.get('macd')
    sma50  = yf.get('sma50')
    sma200 = yf.get('sma200')

    # Analyst — Finnhub first, Yahoo fallback
    rec_fh = recs[0] if recs else {}
    sb = rec_fh.get('strongBuy',  0) or yf.get('analyst_sb', 0)
    b  = rec_fh.get('buy',        0) or yf.get('analyst_b',  0)
    h  = rec_fh.get('hold',       0) or yf.get('analyst_h',  0)
    se = rec_fh.get('sell',       0) or yf.get('analyst_se', 0)
    ss = rec_fh.get('strongSell', 0) or yf.get('analyst_ss', 0)

    tp_fh  = target.get('targetMean')
    tp     = tp_fh or yf.get('target_price')
    upside = (round((tp-price)/price*100, 1)
              if tp and price and price > 0
              else yf.get('upside'))

    # All metrics — Finnhub first, Yahoo fallback
    pe_ttm     = resolve(gm(m_fh,'peBasicExclExtraTTM','peAnnual'), yf.get('pe_ttm'))
    pe_fwd     = yf.get('pe_forward')
    pb         = resolve(gm(m_fh,'pbAnnual'), yf.get('pb'))
    ev_ebitda  = resolve(gm(m_fh,'evToEbitdaAnnual','evToEbitdaTTM'), yf.get('ev_ebitda'))
    net_margin = resolve(gm(m_fh,'netMarginAnnual','netMarginTTM','netProfitMarginAnnual','netProfitMarginTTM'), yf.get('net_margin'))
    op_margin  = resolve(gm(m_fh,'operatingMarginAnnual','operatingMarginTTM'), yf.get('op_margin'))
    gross_m    = resolve(gm(m_fh,'grossMarginAnnual','grossMarginTTM'), yf.get('gross_margin'))
    roe        = resolve(gm(m_fh,'roeAnnual','roeTTM'), yf.get('roe'))
    roa        = resolve(gm(m_fh,'roaAnnual','roaTTM'), yf.get('roa'))
    roic       = gm(m_fh,'roicAnnual','roiAnnual','roicTTM')
    rev_growth = resolve(get_rev_growth(m_fh), yf.get('rev_growth'))
    eps_growth = get_eps_growth(m_fh)
    eps_ttm    = resolve(gm(m_fh,'epsTTM','epsAnnual'), yf.get('eps_ttm'))
    de         = resolve(get_de_fh(m_fh), yf.get('de'))
    cr         = resolve(gm(m_fh,'currentRatioAnnual','currentRatioQuarterly'), yf.get('current_ratio'))
    qr         = resolve(gm(m_fh,'quickRatioAnnual'), yf.get('quick_ratio'))
    div_yield  = resolve(gm(m_fh,'dividendYieldIndicatedAnnual','currentDividendYieldTTM'), yf.get('div_yield'))
    fcf_raw    = yf.get('fcf_raw') or gm(m_fh,'freeCashFlowAnnual','freeCashFlowTTM')
    fcf_str    = yf.get('fcf_str')
    fcf_margin = resolve(gm(m_fh,'fcfMarginAnnual','fcfMarginTTM'), yf.get('fcf_margin'))
    beta       = resolve(gm(m_fh,'beta'), yf.get('beta'))
    w52h       = resolve(gm(m_fh,'52WeekHigh'), yf.get('week52_high'))
    w52l       = resolve(gm(m_fh,'52WeekLow'),  yf.get('week52_low'))
    market_cap = gm(m_fh,'marketCapitalization') or yf.get('market_cap')

    if fcf_raw and not fcf_str:
        v = float(fcf_raw)
        fcf_str = f"${v/1e9:.1f}B" if abs(v)>=1e9 else f"${v/1e6:.0f}M"

    mc = {
        'pe_ttm':pe_ttm,'pe_forward':pe_fwd,'pb':pb,'ev_ebitda':ev_ebitda,
        'net_margin':net_margin,'op_margin':op_margin,'gross_margin':gross_m,
        'roe':roe,'roa':roa,'roic':roic,'rev_growth':rev_growth,
        'eps_growth':eps_growth,'eps_ttm':eps_ttm,
        'de':de,'current_ratio':cr,'quick_ratio':qr,'div_yield':div_yield,
        'fcf_raw':fcf_raw,'fcf_str':fcf_str,'fcf_margin':fcf_margin,
        'beta':beta,'week52_high':w52h,'week52_low':w52l,'market_cap':market_cap,
        'rsi':rsi,'macd':macd,'sma50':sma50,'sma200':sma200,
        'analyst_sb':sb,'analyst_b':b,'analyst_h':h,'analyst_se':se,'analyst_ss':ss,
        'target_price':tp,'upside':upside,
    }

    sc = compute_score(net_margin,op_margin,roe,roa,rev_growth,de,cr,fcf_raw,
                       rsi,sma50,sma200,macd,sb,b,h,se,ss,tp,price)
    z  = calc_altman(m_fh, yf)
    fs = calc_piotroski(m_fh, yf)
    name     = profile.get('name', ticker)
    industry = profile.get('finnhubIndustry','N/A')
    ai = call_openai(ticker, name, industry, price, mc, macro, sc, z, fs)

    return {
        'ticker':ticker,'name':name,
        'exchange':profile.get('exchange',''),'industry':industry,
        'logo':profile.get('logo',''),
        'price':price,'change':change,'change_pct':chg_pct,
        'score':sc,'altman':z,'altman_zone':altman_zone(z),
        'piotroski':fs,'piotroski_label':piotroski_label(fs),
        'macro':macro,
        'metrics':{
            'pe':pe_ttm,'pe_forward':pe_fwd,'pb':pb,'ev_ebitda':ev_ebitda,
            'net_margin':net_margin,'op_margin':op_margin,'gross_margin':gross_m,
            'fcf_margin':fcf_margin,'roe':roe,'roa':roa,'roic':roic,
            'rev_growth':rev_growth,'eps_growth':eps_growth,'eps':eps_ttm,
            'de':de,'current_ratio':cr,'quick_ratio':qr,'div_yield':div_yield,
            'fcf':fcf_str,'week52_high':w52h,'week52_low':w52l,'beta':beta,
        },
        'technical':{'rsi':rsi,'macd':macd,'sma50':sma50,'sma200':sma200},
        'analyst':{'strong_buy':sb,'buy':b,'hold':h,'sell':se,'strong_sell':ss,
                   'total':sb+b+h+se+ss,'target_price':tp,'upside':upside},
        'earnings':[{
            'period':e.get('period'),'actual':e.get('actual'),
            'estimate':e.get('estimate'),'surprise':e.get('surprisePercent')
        } for e in earnings[:8]],
        'ai':ai,
    }

class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin','*')
        self.end_headers()
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        qs     = urllib.parse.parse_qs(parsed.query)
        ticker = (qs.get('ticker',[''])[0]).upper().strip()
        self.send_response(200)
        self.send_header('Content-type','application/json')
        self.send_header('Access-Control-Allow-Origin','*')
        self.end_headers()
        if not ticker:
            self.wfile.write(json.dumps({'error':'Provide ?ticker=AAPL'}).encode())
            return
        try:
            self.wfile.write(json.dumps(analyse(ticker)).encode())
        except Exception as e:
            self.wfile.write(json.dumps({'error':str(e)}).encode())
    def log_message(self,*a): pass
