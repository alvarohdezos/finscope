from http.server import BaseHTTPRequestHandler
import json, os, urllib.parse, urllib.request, time
from concurrent.futures import ThreadPoolExecutor

FINNHUB = os.environ.get('FINNHUB_KEY', '')
OPENAI  = os.environ.get('OPENAI_KEY', '')
AV_KEY  = os.environ.get('AV_KEY', '')  # Alpha Vantage — add to Vercel env vars

PEERS_MAP = {
    'AAPL':['MSFT','GOOGL','META','AMZN'],   'MSFT':['AAPL','GOOGL','CRM','ORCL'],
    'GOOGL':['META','MSFT','AMZN','SNAP'],   'GOOG':['META','MSFT','AMZN','SNAP'],
    'META':['GOOGL','SNAP','PINS','AMZN'],   'AMZN':['MSFT','GOOGL','WMT','SHOP'],
    'NVDA':['AMD','INTC','AVGO','QCOM'],     'AMD':['NVDA','INTC','AVGO','QCOM'],
    'TSLA':['GM','F','RIVN','NIO'],          'JPM':['BAC','WFC','GS','C'],
    'BAC':['JPM','WFC','GS','C'],            'GS':['MS','JPM','BAC','C'],
    'MS':['GS','JPM','BAC','C'],             'V':['MA','PYPL','SQ','AXP'],
    'MA':['V','PYPL','SQ','AXP'],            'XOM':['CVX','COP','BP','SHEL'],
    'CVX':['XOM','COP','BP','SHEL'],         'JNJ':['PFE','MRK','ABBV','LLY'],
    'LLY':['JNJ','PFE','MRK','ABBV'],        'PLTR':['CRM','NOW','SNOW','DDOG'],
    'INTC':['NVDA','AMD','AVGO','QCOM'],     'AVGO':['NVDA','AMD','INTC','QCOM'],
    'ORCL':['MSFT','CRM','SAP','NOW'],       'CRM':['ORCL','NOW','MSFT','SAP'],
    'NFLX':['DIS','PARA','WBD','AMZN'],      'DIS':['NFLX','PARA','WBD','CMCSA'],
}

# ── Finnhub ──────────────────────────────────────────────────────────────────
def fh(path, params, timeout=12):
    params['token'] = FINNHUB
    url = 'https://finnhub.io/api/v1/' + path + '?' + urllib.parse.urlencode(params)
    try:
        req = urllib.request.Request(url, headers={'Accept':'application/json','User-Agent':'FINscope/2.0'})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except:
        return {}

# ── FRED ─────────────────────────────────────────────────────────────────────
def fred(series_id):
    try:
        url = f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}'
        req = urllib.request.Request(url, headers={'User-Agent':'FINscope/2.0'})
        with urllib.request.urlopen(req, timeout=8) as r:
            lines = r.read().decode().strip().split('\n')
            for line in reversed(lines):
                parts = line.split(',')
                if len(parts) == 2 and parts[1].strip() not in ('', '.'):
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
            'cpi_yoy':          3.2, 'pmi_composite': 51.0,
            'credit_spread_hy': 320,
            'vix':              res.get('vix') or 18.0,
        }
    except:
        return {'risk_free_rate':4.42,'policy_rate':5.33,'cpi_yoy':3.2,
                'pmi_composite':51.0,'credit_spread_hy':320,'vix':18.0}

# ── Alpha Vantage — proper REST API, not web scraping, works from Vercel ──────
def _av(function, extra_params, timeout=12):
    params = {'function': function, 'apikey': AV_KEY, 'datatype': 'json'}
    params.update(extra_params)
    url = 'https://www.alphavantage.co/query?' + urllib.parse.urlencode(params)
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'FINscope/2.0'})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
            # Detect rate-limit message
            if isinstance(data, dict) and ('Information' in data or 'Note' in data):
                return {}
            return data
    except:
        return {}

def _sf(v):
    """Safe float from Alpha Vantage string values."""
    if v in (None, 'None', '-', '', 'N/A'): return None
    try: return float(str(v).replace(',', ''))
    except: return None

def _sfpct(v):
    """Safe float as percentage (AV returns 0.553, we want 55.3)."""
    raw = _sf(v)
    if raw is None: return None
    return round(raw * 100, 1)

def _av_overview(ticker):
    return _av('OVERVIEW', {'symbol': ticker}, timeout=10)

def _av_income(ticker):
    data = _av('INCOME_STATEMENT', {'symbol': ticker}, timeout=12)
    return (data.get('annualReports') or [])[:4]

def _av_cashflow(ticker):
    data = _av('CASH_FLOW', {'symbol': ticker}, timeout=12)
    return (data.get('annualReports') or [])[:4]

def _av_timeseries(ticker):
    """Get last ~100 daily adjusted closes for technical calculations."""
    data = _av('TIME_SERIES_DAILY_ADJUSTED', {'symbol': ticker, 'outputsize': 'compact'}, timeout=12)
    ts = data.get('Time Series (Daily)') or {}
    dates = sorted(ts.keys())  # ascending (oldest first for chronological order)
    closes = []
    for d in dates:
        v = (ts[d] or {}).get('5. adjusted close')
        if v:
            try: closes.append(float(v))
            except: pass
    return closes  # ~100 points, chronological

def get_av_data(ticker):
    """Parallel fetch of all Alpha Vantage data for a ticker."""
    with ThreadPoolExecutor(max_workers=4) as ex:
        f_ov  = ex.submit(_av_overview,    ticker)
        f_inc = ex.submit(_av_income,      ticker)
        f_cf  = ex.submit(_av_cashflow,    ticker)
        f_ts  = ex.submit(_av_timeseries,  ticker)
        try:    ov      = f_ov.result(timeout=13)  or {}
        except: ov      = {}
        try:    inc_rep = f_inc.result(timeout=14) or []
        except: inc_rep = []
        try:    cf_rep  = f_cf.result(timeout=14)  or []
        except: cf_rep  = []
        try:    closes  = f_ts.result(timeout=13)  or []
        except: closes  = []

    # ── Overview metrics ──────────────────────────────────────────────────────
    ev_ebitda    = _sf(ov.get('EVToEBITDA'))
    pe_ttm       = _sf(ov.get('TrailingPE'))
    pe_forward   = _sf(ov.get('ForwardPE'))
    pb           = _sf(ov.get('PriceToBookRatio'))
    net_margin   = _sfpct(ov.get('ProfitMargin'))
    op_margin    = _sfpct(ov.get('OperatingMarginTTM'))
    roe          = _sfpct(ov.get('ReturnOnEquityTTM'))
    roa          = _sfpct(ov.get('ReturnOnAssetsTTM'))
    rev_growth   = _sfpct(ov.get('QuarterlyRevenueGrowthYOY'))
    eps_growth   = _sfpct(ov.get('QuarterlyEarningsGrowthYOY'))
    eps_ttm      = _sf(ov.get('EPS')) or _sf(ov.get('DilutedEPSTTM'))
    beta         = _sf(ov.get('Beta'))
    week52_high  = _sf(ov.get('52WeekHigh'))
    week52_low   = _sf(ov.get('52WeekLow'))
    target_price = _sf(ov.get('AnalystTargetPrice'))
    div_yield_raw= _sf(ov.get('DividendYield'))
    div_yield    = round(div_yield_raw * 100, 2) if div_yield_raw else None
    rev_ttm      = _sf(ov.get('RevenueTTM'))
    gp_ttm       = _sf(ov.get('GrossProfitTTM'))
    market_cap_m = round(_sf(ov.get('MarketCapitalization')) / 1e6) if _sf(ov.get('MarketCapitalization')) else None

    gross_margin = round(gp_ttm / rev_ttm * 100, 1) if gp_ttm and rev_ttm else None

    # ── FCF from cash flow statement ─────────────────────────────────────────
    cf_latest = cf_rep[0] if cf_rep else {}
    op_cf  = _sf(cf_latest.get('operatingCashflow'))
    capex  = _sf(cf_latest.get('capitalExpenditures'))
    # AV returns capex as negative, handle both signs
    if op_cf is not None and capex is not None:
        fcf_raw = op_cf - abs(capex)
    else:
        fcf_raw = None
    fcf_str = None
    fcf_margin = None
    if fcf_raw is not None:
        fcf_str = f"${fcf_raw/1e9:.1f}B" if abs(fcf_raw) >= 1e9 else f"${fcf_raw/1e6:.0f}M"
        if rev_ttm and rev_ttm > 0:
            fcf_margin = round(fcf_raw / rev_ttm * 100, 1)

    # ── Debt/Equity from AV overview ─────────────────────────────────────────
    # AV doesn't provide D/E directly in OVERVIEW — use book value proxy
    de = None  # Will fall back to Finnhub

    # ── Upside ───────────────────────────────────────────────────────────────
    upside = None  # computed in analyse() using live price

    # ── Historical financials (4 annual periods) ─────────────────────────────
    hist_fin = []
    for i in range(min(4, len(inc_rep))):
        inc = inc_rep[i] or {}
        cf  = cf_rep[i]  if i < len(cf_rep) else {}
        year = (inc.get('fiscalDateEnding') or '')[:4]
        r   = _sf(inc.get('totalRevenue'))
        ni  = _sf(inc.get('netIncome'))
        gp  = _sf(inc.get('grossProfit'))
        op_cf_h = _sf(cf.get('operatingCashflow'))
        capex_h = _sf(cf.get('capitalExpenditures'))
        fcf_h   = (op_cf_h - abs(capex_h)) if (op_cf_h is not None and capex_h is not None) else None
        if r and r > 0:
            hist_fin.append({
                'year':             year,
                'revenue_m':        round(r   / 1e6),
                'net_income_m':     round(ni  / 1e6) if ni  is not None else None,
                'fcf_m':            round(fcf_h / 1e6) if fcf_h is not None else None,
                'gross_margin_pct': round(gp / r * 100, 1) if gp else None,
                'net_margin_pct':   round(ni / r * 100, 1) if ni else None,
            })

    # ── Technical indicators ─────────────────────────────────────────────────
    rsi_val    = calc_rsi(closes)  if len(closes) >= 15 else None
    macd_val   = calc_macd(closes) if len(closes) >= 35 else None
    sma50_val  = calc_sma(closes,  50)
    sma200_val = calc_sma(closes, 200)  # None if < 200 points (compact = ~100)

    return {
        'ev_ebitda': ev_ebitda, 'pe_ttm': pe_ttm, 'pe_forward': pe_forward, 'pb': pb,
        'net_margin': net_margin, 'op_margin': op_margin, 'gross_margin': gross_margin,
        'roe': roe, 'roa': roa, 'rev_growth': rev_growth, 'eps_growth': eps_growth,
        'eps_ttm': eps_ttm, 'beta': beta,
        'week52_high': week52_high, 'week52_low': week52_low,
        'target_price': target_price, 'div_yield': div_yield,
        'fcf_raw': fcf_raw, 'fcf_str': fcf_str, 'fcf_margin': fcf_margin,
        'de': de, 'market_cap': market_cap_m, 'rev_ttm': rev_ttm,
        'upside': upside,
        'rsi': rsi_val, 'macd': macd_val, 'sma50': sma50_val, 'sma200': sma200_val,
        'historical_financials': hist_fin,
    }

# ── Technical indicators ─────────────────────────────────────────────────────
def calc_rsi(c, p=14):
    if len(c) < p + 1: return None
    ag = al = 0.0
    for i in range(1, p + 1):
        d = c[i] - c[i-1]; ag += max(d, 0); al += max(-d, 0)
    ag /= p; al /= p
    for i in range(p + 1, len(c)):
        d = c[i] - c[i-1]
        ag = (ag*(p-1) + max(d, 0)) / p
        al = (al*(p-1) + max(-d, 0)) / p
    return round(100 - 100/(1 + ag/al), 1) if al else 100.0

def calc_ema(c, p):
    if len(c) < p: return None
    k = 2/(p+1); e = sum(c[:p])/p
    for x in c[p:]: e = x*k + e*(1-k)
    return e

def calc_macd(c):
    if len(c) < 35: return None
    e12 = calc_ema(c, 12); e26 = calc_ema(c, 26)
    return round(e12 - e26, 3) if e12 and e26 else None

def calc_sma(c, p):
    return round(sum(c[-p:])/p, 2) if len(c) >= p else None

# ── Metric helpers ────────────────────────────────────────────────────────────
def resolve(fh_val, av_val):
    for v in (fh_val, av_val):
        if v is not None:
            try: return float(v)
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
    raw = gm(m,'totalDebt/totalEquityAnnual','totalDebt/totalEquityQuarterly',
              'debtToEquityAnnual','longTermDebt/equityAnnual')
    if raw is None: return None
    return float(raw)/100 if float(raw) > 10 else float(raw)

def get_rev_growth_fh(m):
    v = gm(m,'revenueGrowthTTMYoy','revenueGrowthQuarterlyYoy','revenueGrowth3Y')
    if v is None: return None
    return float(v)*100 if abs(float(v)) < 3 else float(v)

def get_eps_growth_fh(m):
    v = gm(m,'epsGrowthTTMYoy','epsGrowthQuarterlyYoy','epsGrowth3Y')
    if v is None: return None
    return float(v)*100 if abs(float(v)) < 3 else float(v)

# ── Composite score ───────────────────────────────────────────────────────────
def compute_score(pm, om, roe, roa, rg, de, cr, fcf_raw,
                  rsi, s50, s200, macd, sb, b, h, se, ss, tp, price):
    f = 17.5
    if pm  is not None: f += 7 if pm>25  else 5 if pm>15  else 2 if pm>8   else (-5 if pm<0  else 0)
    if om  is not None: f += 6 if om>30  else 4 if om>20  else 2 if om>10  else (-4 if om<0  else 0)
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

    return {
        'total': max(5, min(98, round(f+t+a+acc))),
        'fundamental': round(f), 'technical': round(t),
        'analyst': round(a), 'accounting': round(acc),
    }

def calc_altman(m, av):
    try:
        roa = resolve(gm(m,'roaAnnual','roaTTM'), av.get('roa')) or 0
        at  = gm(m,'assetTurnoverAnnual','assetTurnoverTTM') or 0.8
        cr  = resolve(gm(m,'currentRatioAnnual','currentRatioQuarterly'), av.get('current_ratio')) or 1
        de  = resolve(get_de_fh(m), av.get('de')) or 1.0
        roa = roa/100 if roa > 1 else roa
        x1 = max(0,(cr-1)*0.25); x2 = max(0,roa*0.4)
        x3 = max(0,roa*1.3);     x4 = min(5.0,1/de) if de > 0 else 3.0
        return round(1.2*x1 + 1.4*x2 + 3.3*x3 + 0.6*x4 + at, 2)
    except: return None

def altman_zone(z):
    if z is None: return 'N/A'
    return 'Safe (Z>3)' if z > 2.99 else 'Grey zone' if z > 1.81 else 'Distress (Z<1.8)'

def calc_piotroski(m, av):
    s = 0
    roa  = resolve(gm(m,'roaAnnual','roaTTM'), av.get('roa')) or 0
    fcf  = av.get('fcf_raw') or gm(m,'freeCashFlowAnnual','freeCashFlowTTM') or 0
    pm   = resolve(gm(m,'netMarginAnnual','netMarginTTM'), av.get('net_margin')) or 0
    fcfm = av.get('fcf_margin') or 0
    gma  = gm(m,'grossMarginAnnual') or 0
    gmt  = resolve(gm(m,'grossMarginTTM'), av.get('gross_margin')) or 0
    ata  = gm(m,'assetTurnoverAnnual') or 0
    att  = gm(m,'assetTurnoverTTM') or 0
    cra  = gm(m,'currentRatioAnnual') or 0
    crq  = gm(m,'currentRatioQuarterly') or 0
    de   = resolve(get_de_fh(m), av.get('de')) or 0
    rg   = resolve(get_rev_growth_fh(m), av.get('rev_growth')) or 0
    eg   = get_eps_growth_fh(m) or 0
    if roa > 0:             s += 1
    if float(fcf) > 0:      s += 1
    if gm(m,'roaTTM') and (gm(m,'roaTTM') or 0) >= roa*0.9: s += 1
    if fcfm > pm:           s += 1
    if de < 1.0:            s += 1
    if crq >= cra:          s += 1
    if eg >= rg*0.9:        s += 1
    if gmt >= gma:          s += 1
    if att >= ata*0.95:     s += 1
    return min(9, s)

def piotroski_label(f):
    return 'Strong quality' if f>=7 else 'Moderate quality' if f>=4 else 'Weak signals'

# ── System prompt — 11 sections ───────────────────────────────────────────────
SYSTEM_PROMPT = """You are a senior equity analyst at Goldman Sachs Equity Research. Generate an institutional-grade equity research report. Return ONLY valid JSON with the exact structure below. No markdown, no preamble, no trailing commas. Every analytical sentence MUST include at least one specific number.

WACC BENCHMARKS (adjust +0.5-1.0pp if risk_free_rate >4.5%):
UTILITIES 5.0-6.5% | REITS 5.5-7.0% | CONSUMER STAPLES 6.0-7.5% | TELECOM 6.5-8.5% | HEALTHCARE 7.5-9.5% | INDUSTRIALS 7.5-9.5% | RETAIL 8.5-11.0% | TRAVEL 9.5-13.0% | BANKS (ROE vs CoE 10-13%; Z-Score invalid) | INSURANCE 8.0-10.5% | FINTECH 9.0-12.0% | ENERGY MAJORS 8.0-10.0% | ENERGY E&P 10.0-14.0% | RENEWABLES 7.5-10.0% | MATERIALS 9.0-12.0% | PHARMA 8.0-9.0% | BIOTECH 12.0-18.0% | SEMIS 10.0-12.0% | SOFTWARE/SAAS 9.0-12.0% | HARDWARE 10.0-13.0% | INTERNET 9.5-12.0%

RULES: ROIC > WACC+5pp = durable advantage. FCF yield >6% = value. Altman Z >2.99 safe (invalid for banks). Piotroski F 7-9 improving; 0-3 deteriorating. RSI >70 overbought; <30 oversold.

REQUIRED:
- revenue_segments and geographic_exposure: use your knowledge of this company's most recent 10-K. Label as "Source: Company filings / AI estimate".
- competitors.table: ALWAYS include subject company FIRST (is_subject:true), then exactly 4 peers using real publicly available data.
- scenarios.bull/base/bear: use company.price as anchor for all price targets.
- macro_context: tailor SPECIFICALLY to where this company generates its revenue by country/region. Explicitly mention which macro factors matter most for THIS specific company.
- financial_quality: use historical_financials array to discuss multi-year revenue growth trend with exact numbers.
- sec_filings: describe material findings from the most recent 10-K/10-Q using your training knowledge. Be specific with figures.

Return ONLY this JSON:
{"executive_summary":{"verdict":"3-5 word verdict with number","verdict_sub":"1 sentence with 2+ numbers","verdict_color":"green","verdict_icon":"bull","text":"5 sentences: composite score context with exact score, price vs 52W extremes with exact figures, key financial strength with number, main risk with number, investment stance with number."},"business_model":{"text":"4 sentences: primary revenue drivers with revenue figure, competitive moat with quantified metric, customer or segment concentration with percentage, strategic expansion vector with number.","revenue_segments":[{"name":"Segment","pct":56},{"name":"Segment2","pct":44}],"geographic_exposure":[{"region":"United States","pct":45},{"region":"Region2","pct":35},{"region":"Region3","pct":20}]},"performance":{"text":"5 sentences: stock return YTD vs S&P 500, 1Y total return, price vs 52W high and low with exact figures, beta and volatility context, momentum and technical trend summary."},"financial_quality":{"text":"6 sentences: gross margin level and YoY trend from historical data, operating leverage with exact operating margin, FCF absolute value and FCF margin, ROIC vs sector WACC with value-creation verdict, balance sheet strength with debt figure, Piotroski F-Score with exact number and interpretation."},"macro_context":{"text":"5 sentences: current 10Y rate and its specific valuation impact on this company, geographic revenue breakdown and country-specific macro dynamics with exact figures, currency/FX exposure for specific regions, sector-specific macro tailwind or headwind with quantified data point, VIX and credit spread context with exact numbers."},"risk_technical":{"text":"3 sentences: overall risk assessment anchored to composite score, primary operational risk with quantified data, secondary structural or competitive risk with data point.","technical_analysis":"2 sentences: RSI with exact value and signal, SMA50 vs SMA200 with exact values and cross direction. If N/A state in 1 sentence.","risks":["Valuation risk: specific concern with exact multiple vs sector median","Operational risk: specific execution risk with quantified data point","Macro risk: specific rate or FX or credit exposure with exact number","Competitive risk: specific threat with market share or revenue data"]},"ownership":{"text":"4 sentences: institutional ownership percentage and key holders, insider ownership percentage and what it signals, shareholder return policy with buyback and dividend yield figures, governance structure with a specific metric or rating."},"valuation":{"text":"5 sentences: PE vs sector median with both exact figures, EV/EBITDA vs sector peers, FCF yield as dollar return per $100 invested, DCF-implied fair value range with WACC assumption stated, margin of safety conclusion with upside or downside percentage.","fair_value_low":100,"fair_value_high":150},"competitors":{"text":"4 sentences: margin comparison vs peer median with exact figures, valuation premium or discount vs peer median with percentage, revenue growth rank in peer group with exact figure, and key differentiating metric that sets this company apart from nearest peer.","table":[{"ticker":"SUBJ","name":"Full Name","pe":35.2,"ev_ebitda":31.1,"rev_growth_pct":94.2,"net_margin_pct":55.0,"gross_margin_pct":74.6,"roe_pct":101.5,"is_subject":true},{"ticker":"P1","name":"Peer 1","pe":48.0,"ev_ebitda":28.0,"rev_growth_pct":14.0,"net_margin_pct":8.0,"gross_margin_pct":50.0,"roe_pct":15.0,"is_subject":false},{"ticker":"P2","name":"Peer 2","pe":25.0,"ev_ebitda":18.0,"rev_growth_pct":8.0,"net_margin_pct":18.0,"gross_margin_pct":55.0,"roe_pct":22.0,"is_subject":false},{"ticker":"P3","name":"Peer 3","pe":30.0,"ev_ebitda":22.0,"rev_growth_pct":12.0,"net_margin_pct":12.0,"gross_margin_pct":48.0,"roe_pct":18.0,"is_subject":false},{"ticker":"P4","name":"Peer 4","pe":20.0,"ev_ebitda":15.0,"rev_growth_pct":5.0,"net_margin_pct":15.0,"gross_margin_pct":45.0,"roe_pct":12.0,"is_subject":false}]},"scenarios":{"text":"2 sentences framing the range with current price as anchor and weighted expected return.","bull":{"label":"Bull Case","price_target":180,"upside_pct":25,"probability_pct":30,"thesis":"3 sentences: specific catalyst with timeline, revenue or margin expansion assumption with exact figures, implied forward multiple at target price."},"base":{"label":"Base Case","price_target":145,"upside_pct":5,"probability_pct":50,"thesis":"3 sentences: central growth assumption with exact number, margin assumption, and implied multiple at target."},"bear":{"label":"Bear Case","price_target":90,"downside_pct":35,"probability_pct":20,"thesis":"3 sentences: primary downside catalyst with quantified impact, valuation compression with exact multiple, and trigger threshold to watch."}},"sec_filings":{"text":"5 sentences: most recent 10-K or 10-Q revenue recognition or guidance with figures, key risk factors disclosed with specific metrics, segment performance highlights from management discussion with numbers, balance sheet or capital allocation disclosure with amount, and any material accounting changes or going-concern notes.","key_disclosures":["Finding 1: specific disclosure with exact figure from recent filing","Finding 2: specific disclosure with exact figure","Finding 3: specific disclosure with exact figure"]},"methodology_notes":["Note 1: specific metric caveat for this ticker with implication","Note 2: second data or methodology limitation","Note 3: third caveat or data quality note"]}"""

# ── OpenAI call ───────────────────────────────────────────────────────────────
def call_openai(ticker, name, industry, price, mc, macro, sc, z, fs, hist_fin, news, peers):
    user_data = {
        "company": {
            "ticker": ticker, "name": name, "sector": industry, "price": price,
            "composite_score": sc['total'],
            "score_fundamental": sc['fundamental'], "score_technical": sc['technical'],
            "score_analyst": sc['analyst'],          "score_accounting": sc['accounting'],
            "altman_z": z, "altman_zone": altman_zone(z), "piotroski_f": fs,
            "market_cap_m":     mc.get('market_cap'),
            "pe_ttm":           mc.get('pe_ttm'),    "pe_forward":    mc.get('pe_forward'),
            "pb":               mc.get('pb'),          "ev_ebitda":     mc.get('ev_ebitda'),
            "gross_margin":     mc.get('gross_margin'),"op_margin":     mc.get('op_margin'),
            "net_margin":       mc.get('net_margin'),  "roe":           mc.get('roe'),
            "roa":              mc.get('roa'),          "roic":          mc.get('roic'),
            "rev_growth":       mc.get('rev_growth'),  "eps_growth":    mc.get('eps_growth'),
            "eps_ttm":          mc.get('eps_ttm'),      "fcf":           mc.get('fcf_str'),
            "fcf_margin":       mc.get('fcf_margin'),  "de":            mc.get('de'),
            "current_ratio":    mc.get('current_ratio'),"quick_ratio":  mc.get('quick_ratio'),
            "div_yield":        mc.get('div_yield'),    "beta":          mc.get('beta'),
            "week52_high":      mc.get('week52_high'),  "week52_low":   mc.get('week52_low'),
            "rsi":              mc.get('rsi'),           "macd":          mc.get('macd'),
            "sma50":            mc.get('sma50'),         "sma200":        mc.get('sma200'),
            "technical_trend":  ('BULLISH' if mc.get('sma50') and mc.get('sma200') and mc['sma50']>mc['sma200']
                                  else 'BEARISH' if mc.get('sma50') and mc.get('sma200') else 'N/A'),
            "analyst_strong_buy":  mc.get('analyst_sb', 0), "analyst_buy":        mc.get('analyst_b',  0),
            "analyst_hold":        mc.get('analyst_h',  0), "analyst_sell":       mc.get('analyst_se', 0),
            "analyst_strong_sell": mc.get('analyst_ss', 0),
            "analyst_total":       sum(mc.get(k,0) for k in ['analyst_sb','analyst_b','analyst_h','analyst_se','analyst_ss']),
            "consensus_target": mc.get('target_price'), "consensus_upside": mc.get('upside'),
            "historical_financials": hist_fin,
            "suggested_peers":  peers,
        },
        "macro": macro,
        "recent_news": news,
    }
    try:
        payload = json.dumps({
            'model': 'gpt-4o-mini', 'max_tokens': 3000,
            'messages': [
                {'role': 'system', 'content': SYSTEM_PROMPT},
                {'role': 'user',   'content': json.dumps(user_data)},
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
            es = result.get('executive_summary') or {}
            if es.get('verdict'):
                es['verdict'] = es['verdict'][0].upper() + es['verdict'][1:]
            return result
    except Exception:
        return _fallback(name, mc, sc, z, fs)

def _fallback(name, m, sc, z, fs):
    sv  = sc['total']
    col = 'green' if sv>=70 else 'red' if sv<50 else 'yellow'
    icon= 'bull'  if sv>=70 else 'bear' if sv<50 else 'neutral'
    pm  = m.get('net_margin') or 0; de = m.get('de') or 0
    roe = m.get('roe') or 0;       rg = m.get('rev_growth') or 0
    total_a = sum(m.get(k,0) for k in ['analyst_sb','analyst_b','analyst_h','analyst_se','analyst_ss'])
    txt = f"Score {sv}/100 — net margin {pm:.1f}%, ROE {roe:.1f}%"
    return {
        'executive_summary':{'verdict': txt[0].upper()+txt[1:],'verdict_sub':f"Composite {sv}/100. D/E {de:.2f}x.","verdict_color":col,"verdict_icon":icon,"text":f"Composite score {sv}/100. Net margin {pm:.1f}%. D/E {de:.2f}x. ROE {roe:.1f}%. Revenue growth {rg:.1f}%."},
        'business_model':   {'text':f"{name} — AI synthesis unavailable. Retry for full report.","revenue_segments":[],"geographic_exposure":[]},
        'performance':      {'text':f"Score {sv}/100. Performance synthesis unavailable."},
        'financial_quality':{'text':f"Net margin {pm:.1f}%. ROE {roe:.1f}%. D/E {de:.2f}x. Piotroski F {fs}/9. Altman Z {z or 'N/A'}."},
        'macro_context':    {'text':"Macro synthesis unavailable in fallback mode. Retry for full analysis."},
        'risk_technical':   {'text':f"D/E {de:.2f}x. Score {sv}/100.",'technical_analysis':"Technical N/A.",'risks':[f"D/E {de:.2f}x leverage.",f"Revenue growth {rg:.1f}%.","Market risk — beta unavailable.","Competitive risk — analysis unavailable."]},
        'ownership':        {'text':"Ownership synthesis unavailable in fallback mode."},
        'valuation':        {'text':f"Composite score {sv}/100. D/E {de:.2f}x.",'fair_value_low':0,'fair_value_high':0},
        'competitors':      {'text':"Competitor analysis unavailable in fallback mode.",'table':[]},
        'scenarios':        {'text':f"Score {sv}/100 from current price.",'bull':{'label':'Bull','price_target':0,'upside_pct':20,'probability_pct':30,'thesis':'Fallback — retry for full report.'},'base':{'label':'Base','price_target':0,'upside_pct':0,'probability_pct':50,'thesis':'Fallback — retry for full report.'},'bear':{'label':'Bear','price_target':0,'downside_pct':20,'probability_pct':20,'thesis':'Fallback — retry for full report.'}},
        'sec_filings':      {'text':"SEC filing analysis unavailable in fallback mode. Retry for full report.",'key_disclosures':[]},
        'methodology_notes':["AI synthesis failed — retry for full 11-section report.","Quantitative metrics computed server-side are accurate.","Check OPENAI_KEY environment variable if fallback persists."]
    }

# ── Main analysis ─────────────────────────────────────────────────────────────
def analyse(ticker):
    now_ts    = int(time.time())
    from_date = time.strftime('%Y-%m-%d', time.gmtime(now_ts - 30*24*3600))
    to_date   = time.strftime('%Y-%m-%d', time.gmtime(now_ts))

    # Step 1: Finnhub + FRED parallel
    with ThreadPoolExecutor(max_workers=9) as ex:
        futs = {
            'profile': ex.submit(fh, 'stock/profile2', {'symbol': ticker}),
            'quote':   ex.submit(fh, 'quote',           {'symbol': ticker}),
            'metrics': ex.submit(fh, 'stock/metric',    {'symbol': ticker, 'metric': 'all'}),
            'recs':    ex.submit(fh, 'stock/recommendation-trends', {'symbol': ticker}),
            'target':  ex.submit(fh, 'stock/price-target',   {'symbol': ticker}),
            'earnings':ex.submit(fh, 'stock/earnings',        {'symbol': ticker}),
            'news':    ex.submit(fh, 'company-news', {'symbol': ticker, 'from': from_date, 'to': to_date}),
            'macro':   ex.submit(get_macro),
        }
        res = {k: v.result() for k, v in futs.items()}

    profile = res['profile']
    if not profile.get('name'):
        raise Exception(f'Ticker "{ticker}" not found. Try AAPL, NVDA, MSFT, JPM.')

    quote    = res['quote']
    m_fh     = (res['metrics'].get('metric') or {})
    recs     = res['recs']     if isinstance(res['recs'],     list) else []
    target   = res['target']   if isinstance(res['target'],   dict) else {}
    earnings = res['earnings'] if isinstance(res['earnings'], list) else []
    news_raw = res['news']     if isinstance(res['news'],     list) else []
    macro    = res['macro']

    news = [{'headline': a.get('headline',''), 'source': a.get('source','')}
            for a in news_raw[:5] if a.get('headline')]

    # Step 2: Alpha Vantage (sequential wrapper for safety)
    import concurrent.futures as cf
    with cf.ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(get_av_data, ticker)
        try:    av = fut.result(timeout=22) or {}
        except: av = {}

    price   = quote.get('c')
    change  = quote.get('d')
    chg_pct = quote.get('dp')

    # Technical from AV
    rsi    = av.get('rsi');    macd   = av.get('macd')
    sma50  = av.get('sma50'); sma200 = av.get('sma200')

    # Analyst — Finnhub first, AV fallback for target
    rec_fh = recs[0] if recs else {}
    sb = rec_fh.get('strongBuy',  0) or 0
    b  = rec_fh.get('buy',        0) or 0
    h  = rec_fh.get('hold',       0) or 0
    se = rec_fh.get('sell',       0) or 0
    ss = rec_fh.get('strongSell', 0) or 0
    tp_fh = target.get('targetMean')
    tp    = tp_fh or av.get('target_price')
    upside = (round((tp-price)/price*100, 1) if tp and price and price > 0 else None)

    # Metrics — Finnhub first, AV fallback
    pe_ttm     = resolve(gm(m_fh,'peBasicExclExtraTTM','peAnnual'),      av.get('pe_ttm'))
    pe_fwd     = av.get('pe_forward')
    pb         = resolve(gm(m_fh,'pbAnnual'),                              av.get('pb'))
    ev_ebitda  = resolve(gm(m_fh,'evToEbitdaAnnual','evToEbitdaTTM'),     av.get('ev_ebitda'))
    net_margin = resolve(gm(m_fh,'netMarginAnnual','netMarginTTM','netProfitMarginAnnual'), av.get('net_margin'))
    op_margin  = resolve(gm(m_fh,'operatingMarginAnnual','operatingMarginTTM'), av.get('op_margin'))
    gross_m    = resolve(gm(m_fh,'grossMarginAnnual','grossMarginTTM'),    av.get('gross_margin'))
    roe        = resolve(gm(m_fh,'roeAnnual','roeTTM'),                    av.get('roe'))
    roa        = resolve(gm(m_fh,'roaAnnual','roaTTM'),                    av.get('roa'))
    roic       = gm(m_fh,'roicAnnual','roiAnnual','roicTTM')
    rev_growth = resolve(get_rev_growth_fh(m_fh),                          av.get('rev_growth'))
    eps_growth = resolve(get_eps_growth_fh(m_fh),                          av.get('eps_growth'))
    eps_ttm    = resolve(gm(m_fh,'epsTTM','epsAnnual'),                    av.get('eps_ttm'))
    de         = resolve(get_de_fh(m_fh),                                  av.get('de'))
    cr         = gm(m_fh,'currentRatioAnnual','currentRatioQuarterly')
    qr         = gm(m_fh,'quickRatioAnnual')
    div_yield  = resolve(gm(m_fh,'dividendYieldIndicatedAnnual','currentDividendYieldTTM'), av.get('div_yield'))
    fcf_raw    = av.get('fcf_raw') or gm(m_fh,'freeCashFlowAnnual','freeCashFlowTTM')
    fcf_str    = av.get('fcf_str')
    fcf_margin = av.get('fcf_margin')
    beta       = resolve(gm(m_fh,'beta'),         av.get('beta'))
    w52h       = resolve(gm(m_fh,'52WeekHigh'),   av.get('week52_high'))
    w52l       = resolve(gm(m_fh,'52WeekLow'),    av.get('week52_low'))
    market_cap = gm(m_fh,'marketCapitalization') or av.get('market_cap')

    if fcf_raw and not fcf_str:
        v = float(fcf_raw)
        fcf_str = f"${v/1e9:.1f}B" if abs(v) >= 1e9 else f"${v/1e6:.0f}M"

    mc = {
        'pe_ttm':pe_ttm, 'pe_forward':pe_fwd, 'pb':pb, 'ev_ebitda':ev_ebitda,
        'net_margin':net_margin, 'op_margin':op_margin, 'gross_margin':gross_m,
        'roe':roe, 'roa':roa, 'roic':roic, 'rev_growth':rev_growth,
        'eps_growth':eps_growth, 'eps_ttm':eps_ttm,
        'de':de, 'current_ratio':cr, 'quick_ratio':qr, 'div_yield':div_yield,
        'fcf_raw':fcf_raw, 'fcf_str':fcf_str, 'fcf_margin':fcf_margin,
        'beta':beta, 'week52_high':w52h, 'week52_low':w52l, 'market_cap':market_cap,
        'rsi':rsi, 'macd':macd, 'sma50':sma50, 'sma200':sma200,
        'analyst_sb':sb, 'analyst_b':b, 'analyst_h':h, 'analyst_se':se, 'analyst_ss':ss,
        'target_price':tp, 'upside':upside,
    }

    sc   = compute_score(net_margin,op_margin,roe,roa,rev_growth,de,cr,fcf_raw,
                         rsi,sma50,sma200,macd,sb,b,h,se,ss,tp,price)
    z    = calc_altman(m_fh, av)
    fs   = calc_piotroski(m_fh, av)
    name = profile.get('name', ticker)
    industry = profile.get('finnhubIndustry', 'N/A')
    peers    = PEERS_MAP.get(ticker, ['SPY','QQQ','IWM','GLD'])
    hist_fin = av.get('historical_financials', [])

    ai = call_openai(ticker, name, industry, price, mc, macro, sc, z, fs, hist_fin, news, peers)

    return {
        'ticker': ticker, 'name': name, 'news': news,
        'exchange': profile.get('exchange',''), 'industry': industry,
        'logo': profile.get('logo',''),
        'price': price, 'change': change, 'change_pct': chg_pct,
        'score': sc, 'altman': z, 'altman_zone': altman_zone(z),
        'piotroski': fs, 'piotroski_label': piotroski_label(fs),
        'macro': macro,
        'historical_financials': hist_fin,
        'metrics': {
            'pe':pe_ttm, 'pe_forward':pe_fwd, 'pb':pb, 'ev_ebitda':ev_ebitda,
            'net_margin':net_margin, 'op_margin':op_margin, 'gross_margin':gross_m,
            'fcf_margin':fcf_margin, 'roe':roe, 'roa':roa, 'roic':roic,
            'rev_growth':rev_growth, 'eps_growth':eps_growth, 'eps':eps_ttm,
            'de':de, 'current_ratio':cr, 'quick_ratio':qr, 'div_yield':div_yield,
            'fcf':fcf_str, 'week52_high':w52h, 'week52_low':w52l, 'beta':beta,
        },
        'technical': {'rsi':rsi,'macd':macd,'sma50':sma50,'sma200':sma200},
        'analyst': {
            'strong_buy':sb,'buy':b,'hold':h,'sell':se,'strong_sell':ss,
            'total':sb+b+h+se+ss,'target_price':tp,'upside':upside,
        },
        'earnings': [{'period':e.get('period'),'actual':e.get('actual'),
                      'estimate':e.get('estimate'),'surprise':e.get('surprisePercent')}
                     for e in earnings[:8]],
        'ai': ai,
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
            self.wfile.write(json.dumps({'error': str(e)}).encode())
    def log_message(self, *a): pass
