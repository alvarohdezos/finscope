from http.server import BaseHTTPRequestHandler
import json, os, urllib.parse, urllib.request, time
from concurrent.futures import ThreadPoolExecutor

FINNHUB = os.environ.get('FINNHUB_KEY', '')
OPENAI  = os.environ.get('OPENAI_KEY', '')

def fh(path, params, timeout=12):
    params['token'] = FINNHUB
    url = 'https://finnhub.io/api/v1/' + path + '?' + urllib.parse.urlencode(params)
    try:
        req = urllib.request.Request(url, headers={'Accept':'application/json','User-Agent':'FINscope/2.0'})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except:
        return {}

def fred(series_id):
    """Fetch latest value from FRED (Federal Reserve Economic Data) - free, no key needed"""
    try:
        url = f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}'
        req = urllib.request.Request(url, headers={'User-Agent':'FINscope/2.0'})
        with urllib.request.urlopen(req, timeout=8) as r:
            lines = r.read().decode().strip().split('\n')
            # Last non-empty line has the latest value
            for line in reversed(lines):
                parts = line.split(',')
                if len(parts)==2 and parts[1].strip() not in ('','.','.'):
                    try: return float(parts[1].strip())
                    except: continue
    except:
        pass
    return None

def get_macro():
    """Fetch live macro data from FRED - all free endpoints"""
    try:
        with ThreadPoolExecutor(max_workers=4) as ex:
            futs = {
                'treasury_10y': ex.submit(fred, 'DGS10'),
                'fed_funds':    ex.submit(fred, 'FEDFUNDS'),
                'cpi_yoy':      ex.submit(fred, 'CPIAUCSL'),
                'vix':          ex.submit(fred, 'VIXCLS'),
            }
            res = {k: v.result() for k, v in futs.items()}
        # CPI from FRED is level, not YOY — approximate YOY
        cpi = res.get('cpi_yoy')
        return {
            'risk_free_rate': res.get('treasury_10y') or 4.42,
            'policy_rate':    res.get('fed_funds') or 5.33,
            'cpi_yoy':        3.2,  # fallback — FRED CPI needs two points to calc YOY
            'pmi_composite':  51.0, # no free real-time PMI API
            'credit_spread_hy': 320, # fallback
            'vix':            res.get('vix') or 18.0,
            'macro_note':     'Federal Reserve holding rates; inflation moderating toward 2% target.'
        }
    except:
        return {
            'risk_free_rate': 4.42, 'policy_rate': 5.33, 'cpi_yoy': 3.2,
            'pmi_composite': 51.0, 'credit_spread_hy': 320, 'vix': 18.0,
            'macro_note': 'Macro data temporarily unavailable — analysis based on company fundamentals only.'
        }

# ── Technical ────────────────────────────────────────────────────────────────
def calc_rsi(c, p=14):
    if len(c) < p+1: return None
    ag = al = 0.0
    for i in range(1, p+1):
        d = c[i]-c[i-1]
        if d>0: ag+=d
        else: al-=d
    ag/=p; al/=p
    for i in range(p+1, len(c)):
        d = c[i]-c[i-1]
        ag=(ag*(p-1)+max(d,0))/p; al=(al*(p-1)+max(-d,0))/p
    return round(100-100/(1+ag/al), 1) if al else 100.0

def calc_ema(c, p):
    if len(c)<p: return None
    k=2/(p+1); e=sum(c[:p])/p
    for x in c[p:]: e=x*k+e*(1-k)
    return e

def calc_macd(c):
    if len(c)<35: return None
    e12=calc_ema(c,12); e26=calc_ema(c,26)
    return round(e12-e26, 3) if e12 and e26 else None

def calc_sma(c, p):
    return round(sum(c[-p:])/p, 2) if len(c)>=p else None

# ── Metric helpers ────────────────────────────────────────────────────────────
def gm(m, *keys):
    for k in keys:
        v = m.get(k)
        if v is not None:
            try: return float(v)
            except: return v
    return None

def nv(m, *keys):
    v = gm(m, *keys)
    try: return float(v) if v is not None else 0.0
    except: return 0.0

def get_de(m):
    raw = gm(m,'totalDebt/totalEquityAnnual','totalDebt/totalEquityQuarterly',
              'debtToEquityAnnual','longTermDebt/equityAnnual')
    if raw is None: return None
    return float(raw)/100 if float(raw) > 10 else float(raw)

def get_net_margin(m):
    return gm(m,'netMarginAnnual','netMarginTTM','netProfitMarginAnnual','netProfitMarginTTM')

def get_rev_growth(m):
    v = gm(m,'revenueGrowthTTMYoy','revenueGrowthQuarterlyYoy','revenueGrowth3Y')
    if v is None: return None
    v = float(v)
    return v*100 if abs(v) < 3 else v

def get_eps_growth(m):
    v = gm(m,'epsGrowthTTMYoy','epsGrowthQuarterlyYoy','epsGrowth3Y')
    if v is None: return None
    v = float(v)
    return v*100 if abs(v) < 3 else v

def get_roic(m):
    return gm(m,'roicAnnual','roiAnnual','roiTTM','returnOnInvestedCapitalAnnual','roicTTM')

def get_ev_ebitda(m):
    return gm(m,'evToEbitdaAnnual','evToEbitdaTTM','enterpriseValueToEBITDA')

def get_fcf(m):
    return gm(m,'freeCashFlowAnnual','freeCashFlowTTM','cashFlowFromOperationsAnnual')

def get_fcf_str(m):
    v = get_fcf(m)
    if v is None: return None
    v = float(v)
    return f"${v/1e9:.1f}B" if abs(v)>=1e9 else f"${v/1e6:.0f}M"

def get_fcf_margin(m):
    return gm(m,'fcfMarginAnnual','fcfMarginTTM','freeCashFlowMarginTTM')

def get_quick_ratio(m):
    return gm(m,'quickRatioAnnual','quickRatioQuarterly')

def get_div_yield(m):
    return gm(m,'dividendYieldIndicatedAnnual','currentDividendYieldTTM','dividendYieldTTM')

def get_eps(m):
    return gm(m,'epsTTM','epsAnnual','epsNormalizedAnnual','epsBasicExclExtraTTM')

# ── Scores ────────────────────────────────────────────────────────────────────
def compute_score(m, rsi, s50, s200, macd, sb, b, h, se, ss, tp, price):
    pm  = nv(m,'netMarginAnnual','netMarginTTM','netProfitMarginAnnual')
    om  = nv(m,'operatingMarginAnnual','operatingMarginTTM')
    roe = nv(m,'roeAnnual','roeTTM')
    roa = nv(m,'roaAnnual','roaTTM')
    rg  = get_rev_growth(m) or 0
    de  = get_de(m) or 0
    cr  = nv(m,'currentRatioAnnual','currentRatioQuarterly')

    f=17.5
    f += 7 if pm>25 else 5 if pm>15 else 2 if pm>8 else (-5 if pm<0 else 0)
    f += 6 if om>30 else 4 if om>20 else 2 if om>10 else (-4 if om<0 else 0)
    f += 6 if roe>30 else 3 if roe>15 else (-4 if roe<0 else 0)
    f += 4 if roa>15 else 2 if roa>8 else (-2 if roa<0 else 0)
    f += 6 if rg>20 else 3 if rg>10 else 1 if rg>0 else -4
    f=max(0,min(35,f))

    t=12.5
    if rsi is not None:
        t += 6 if 40<=rsi<=65 else 2 if 30<=rsi<40 else 2 if 65<rsi<=75 else (-4 if rsi>75 else -2)
    if s50 and s200: t += 6 if s50>s200 else -4
    if macd is not None: t += 5 if macd>0 else -3
    t=max(0,min(25,t))

    a=12.5
    total=sb+b+h+se+ss
    if total>0:
        br=(sb+b)/total; sr=(se+ss)/total
        a += 10 if br>0.7 else 6 if br>0.5 else 2 if br>0.3 else 0
        a -= 8 if sr>0.5 else 4 if sr>0.3 else 0
    if tp and price and price>0:
        up=(tp-price)/price*100
        a += 5 if up>20 else 2 if up>10 else 1 if up>0 else (-5 if up<-10 else -2)
    a=max(0,min(25,a))

    acc=7.5
    acc += 4 if de<0.3 else 2 if de<1 else (-4 if de>3 else -2 if de>2 else 0)
    acc += 3 if cr>2 else 1 if cr>1.2 else (-3 if 0<cr<1 else 0)
    fcf=get_fcf(m)
    if fcf is not None: acc += 2 if float(fcf)>0 else -2
    acc=max(0,min(15,acc))

    return {'total':max(5,min(98,round(f+t+a+acc))),
            'fundamental':round(f),'technical':round(t),
            'analyst':round(a),'accounting':round(acc)}

def calc_altman(m):
    try:
        roa=nv(m,'roaAnnual','roaTTM')/100
        at =nv(m,'assetTurnoverAnnual','assetTurnoverTTM') or 0.8
        cr =nv(m,'currentRatioAnnual','currentRatioQuarterly') or 1
        de =get_de(m) or 1.0
        x1=max(0,(cr-1)*0.25); x2=max(0,roa*0.4); x3=max(0,roa*1.3)
        x4=min(5.0,1/de) if de>0 else 3.0; x5=at
        return round(1.2*x1+1.4*x2+3.3*x3+0.6*x4+1.0*x5,2)
    except: return None

def altman_zone(z):
    if z is None: return 'N/A'
    return 'Safe (Z>3)' if z>2.99 else 'Grey zone' if z>1.81 else 'Distress (Z<1.8)'

def calc_piotroski(m):
    s=0
    roa=nv(m,'roaAnnual','roaTTM'); fcf=nv(m,'freeCashFlowAnnual','freeCashFlowTTM')
    pm=nv(m,'netMarginAnnual','netMarginTTM'); fcfm=nv(m,'fcfMarginAnnual','fcfMarginTTM')
    gma=nv(m,'grossMarginAnnual'); gmt=nv(m,'grossMarginTTM')
    ata=nv(m,'assetTurnoverAnnual'); att=nv(m,'assetTurnoverTTM')
    cra=nv(m,'currentRatioAnnual'); crq=nv(m,'currentRatioQuarterly')
    de=get_de(m) or 0
    rg=get_rev_growth(m) or 0; eg=get_eps_growth(m) or 0
    if roa>0: s+=1
    if fcf>0: s+=1
    if nv(m,'roaTTM')>=roa*0.9: s+=1
    if fcfm>pm: s+=1
    if de<1.0: s+=1
    if crq>=cra: s+=1
    if eg>=rg*0.9: s+=1
    if gmt>=gma: s+=1
    if att>=ata*0.95: s+=1
    return min(9,s)

def piotroski_label(f):
    return 'Strong quality' if f>=7 else 'Moderate quality' if f>=4 else 'Weak signals'

# ── SYSTEM PROMPT (Goldman Sachs institutional analyst) ───────────────────────
SYSTEM_PROMPT = """You are a senior equity analyst at Goldman Sachs Equity Research with 15 years of cross-sector experience covering US, European, and emerging market equities. Your role is to produce institutional-grade, decisive investment analysis. Every sentence in your output that contains analysis MUST include at least one specific number, ratio, score, or percentage. Never use hedging language such as "could potentially", "might suggest", or "appears to be". Be direct and decisive in every field.

SECTION 2 — WACC BENCHMARKS BY SECTOR
Base ranges under neutral rate environment (risk_free_rate ≈ 3.5–4.5%). ADJUSTMENT: If risk_free_rate > 4.5%, shift all ranges up 0.5–1.0pp. If < 3.0%, shift down 0.5–1.0pp.
UTILITIES & REGULATED INFRASTRUCTURE — WACC: 5.0–6.5% | Min ROIC: 6.5%
REAL ESTATE (REITs) — WACC: 5.5–7.0% | Min ROIC: 7.0%
CONSUMER STAPLES — WACC: 6.0–7.5% | Min ROIC: 8.0%
TELECOMMUNICATIONS — WACC: 6.5–8.5% | Min ROIC: 8.0%
HEALTHCARE — Medical Devices & Services — WACC: 7.5–9.5% | Min ROIC: 10.0%
INDUSTRIALS — Aerospace & Defense — WACC: 7.0–9.0% | Min ROIC: 10.0%
INDUSTRIALS — Diversified & Conglomerates — WACC: 7.5–9.5% | Min ROIC: 10.0%
INDUSTRIALS — Transportation & Logistics — WACC: 7.5–9.5% | Min ROIC: 9.0%
CONSUMER DISCRETIONARY — Luxury — WACC: 7.5–9.5% | Min ROIC: 15.0%
CONSUMER DISCRETIONARY — Retail — WACC: 8.5–11.0% | Min ROIC: 12.0%
CONSUMER DISCRETIONARY — Travel, Hospitality & Leisure — WACC: 9.5–13.0% | Min ROIC: 12.0%
FINANCIALS — Banks (large-cap developed market) — CoE: 10.0–13.0% — DO NOT use ROIC/WACC. Use ROE vs CoE. Altman Z-Score NOT valid for banks.
FINANCIALS — Regional & Emerging Market Banks — CoE: 12.0–15.0%
FINANCIALS — Insurance — WACC: 8.0–10.5% | Min ROE: 12.0%
FINANCIALS — Asset Management & Fintech — WACC: 9.0–12.0% | Min ROIC: 15.0%
ENERGY — Integrated Majors — WACC: 8.0–10.0% | Min ROIC: 10.0% (mid-cycle)
ENERGY — Exploration & Production — WACC: 10.0–14.0% | Min ROIC: 12.0%
ENERGY — Renewables & Clean Energy — WACC: 7.5–10.0% | Min ROIC: 8.5%
MATERIALS — Chemicals, Metals & Mining — WACC: 9.0–12.0% | Min ROIC: 11.0%
HEALTHCARE — Pharma (Big Pharma) — WACC: 8.0–9.0% | Min ROIC: 12.0%
HEALTHCARE — Specialty Pharma — WACC: 9.0–10.5% | Min ROIC: 12.0%
HEALTHCARE — Biotech (pre-revenue) — WACC: 12.0–18.0% | ROIC: N/A
SEMICONDUCTORS — Fabless — WACC: 10.0–12.0% | Min ROIC: 15.0%
SEMICONDUCTORS — Integrated (IDM/Fab) — WACC: 9.5–10.5% | Min ROIC: 12.0%
SOFTWARE & SaaS — WACC: 9.0–12.0% | Min ROIC: 20.0%
TECHNOLOGY — Hardware & Electronics — WACC: 10.0–13.0% | Min ROIC: 12.0%
TECHNOLOGY — Internet, Platforms & E-commerce — WACC: 9.5–12.0% | Min ROIC: 18.0%

SECTION 3 — ANALYTICAL CRITERIA
VALUATION: Compare PE to sector median and company 5Y historical average. Flag PEG > 2.0 as expensive, PEG < 1.0 as potentially undervalued. FCF yield (FCF / Market Cap): below 2% = expensive, above 6% = value territory. PB meaningful for financials, utilities, industrials — irrelevant for software/services.
MACRO INTEGRATION: VIX below 15 = low risk premium; 15–25 = normal; above 25 = elevated. Rate-sensitive sectors: 1pp rate rise compresses fair value ~10–15%. CPI above 4%: gross margin stability becomes primary differentiator. PMI below 50: downgrade cyclical assumptions. HY spread above 450bps: flag refinancing risk for D/E above 2.0x.
BUSINESS QUALITY: ROIC vs sector WACC. ROIC below WACC = value-destructive growth. ROIC exceeding WACC by more than 5pp = likely durable competitive advantage. ROE vs ROA gap above 10pp = explicit leverage commentary required.
CASH FLOW: FCF vs net income divergence above 15% for 2+ quarters = red flag. FCF yield below 2% = stretched; above 6% = strong cash return potential.
SOLVENCY: Altman Z above 2.99 safe; 1.81–2.99 grey; below 1.81 distress. Piotroski 7–9 improving; 4–6 neutral; 0–3 deteriorating. Current ratio below 1.0 = liquidity concern.
TECHNICAL: RSI above 70 = overbought; below 30 = oversold. SMA50 above SMA200 = uptrend. MACD bullish crossover in oversold RSI = high-conviction setup. All data N/A: state in one sentence, do not speculate.
ANALYST CONSENSUS: Below 5 analysts = low statistical weight. Above 20 = high-conviction consensus. Hold majority above 50% = functionally equivalent to sell signal.
EARNINGS QUALITY: 4 consecutive beats = consistent execution. Beat EPS + guided lower = value trap. Miss revenue + beat EPS = cost-cutting, not growth.

SECTION 4 — METHODOLOGY CAVEATS
Generate methodology_notes array with 2–5 specific contextual caveats for THIS analysis. Each must name the metric, the limitation, and the implication. Trigger caveats when: Financial sector (Z-Score validity), cyclical sector (TTM ROIC), pre-revenue biotech (ROIC N/A), technical data N/A, analyst count below 5, FCF divergence above 15%, high D/E vs sector norm, Beta period unknown, ROIC above 30% in cyclical sector.

SECTION 5 — OUTPUT FORMAT
Return ONLY valid JSON. No preamble, no markdown. Every analysis string MUST include at least one specific number.

{
  "verdict": "2-4 word institutional verdict",
  "verdict_sub": "1 sentence core thesis with at least 2 specific numbers",
  "verdict_color": "green | yellow | red | gray",
  "verdict_icon": "bull | bear | neutral | watch",
  "capital": "3-4 sentences on valuation and business economics. PE vs sector/historical, FCF yield, ROIC vs sector WACC, margin trend. Each sentence must contain a number.",
  "cashflow": "2-3 sentences on FCF quality, FCF vs net income, FCF yield, capital allocation.",
  "technical": "2-3 sentences on RSI, SMA configuration, MACD. State N/A fields explicitly.",
  "analyst_view": "2-3 sentences on consensus quality, upside credibility, estimate revisions. Include analyst count and upside %.",
  "solvency": "2-3 sentences on Z-Score zone, Piotroski tier, liquidity ratios, sector D/E context.",
  "risks": "2-3 sentences on 2-3 material risks anchored to specific data points. Include 1 macro risk if relevant.",
  "credit_decision": "1-2 sentences on creditworthiness based on FCF coverage, solvency, credit spread environment.",
  "retail_summary": {
    "what_they_do": "2-3 sentences. What the company does and how it makes money. No jargon.",
    "price_story": "2-3 sentences. What the price is doing right now in plain language. RSI and SMA terms. State N/A if technical data unavailable.",
    "is_it_cheap": "2-3 sentences. Expensive or cheap? PE vs history/sector. FCF yield as dollars of cash per $100 of market value. End with direct verdict: undervalued, fairly priced, or expensive.",
    "making_money": "2 sentences. Is it genuinely profitable? Express net margin as: out of every $100 in revenue the company keeps $X.",
    "debt_plain": "2 sentences. Debt situation without jargon. Debt as equivalent of X years of earnings.",
    "main_risk_plain": "2-3 sentences. The 1-2 most specific risks in plain language, each anchored to a data point.",
    "analyst_take_plain": "2 sentences. How many analysts say buy vs sell, what upside they see, whether credible. Include target price.",
    "verdict_plain": "1 direct sentence. Overall investment case in plain language. Must include at least one number."
  },
  "methodology_notes": ["Caveat 1: metric, limitation, interpretation implication", "Caveat 2: ..."]
}"""

# ── OpenAI call ───────────────────────────────────────────────────────────────
def call_openai(ticker,name,industry,price,m,rsi,macd,s50,s200,sb,b,h,se,ss,tp,earnings,z,fs,sc,macro):
    pm =nv(m,'netMarginAnnual','netMarginTTM') or 0
    om =nv(m,'operatingMarginAnnual','operatingMarginTTM') or 0
    roe=nv(m,'roeAnnual','roeTTM') or 0
    roa=nv(m,'roaAnnual','roaTTM') or 0
    de =get_de(m) or 0; cr=nv(m,'currentRatioAnnual','currentRatioQuarterly') or 0
    rg =get_rev_growth(m) or 0; eg=get_eps_growth(m) or 0; beta=nv(m,'beta') or 0
    total=sb+b+h+se+ss
    upside=round((tp-price)/price*100,1) if tp and price and price>0 else None
    trend='BULLISH(SMA50>SMA200)' if s50 and s200 and s50>s200 else 'BEARISH(SMA50<SMA200)' if s50 and s200 else 'N/A'
    eq=' | '.join([f"Q{i+1}:Act${e.get('actual','?')}vEst${e.get('estimate','?')}({(e.get('surprise') or 0):.1f}%)" for i,e in enumerate((earnings or [])[:4])]) or 'N/A'
    fcf=get_fcf_str(m)
    mcap=nv(m,'marketCapitalization') or 0

    user_data = {
        "company": {
            "name": name, "ticker": ticker, "sector": industry,
            "price": price, "market_cap_m": mcap,
            "pe": nv(m,'peBasicExclExtraTTM','peAnnual'),
            "pb": nv(m,'pbAnnual'),
            "beta": beta,
            "gross_margin_pct": nv(m,'grossMarginAnnual','grossMarginTTM'),
            "operating_margin_pct": om,
            "net_margin_pct": pm,
            "roe_pct": roe, "roa_pct": roa,
            "roic_pct": nv(m,'roicAnnual','roiAnnual') or 0,
            "revenue_growth_yoy_pct": rg,
            "eps_growth_yoy_pct": eg,
            "eps_ttm": get_eps(m),
            "fcf": fcf,
            "fcf_margin_pct": get_fcf_margin(m),
            "debt_equity": de,
            "current_ratio": cr,
            "quick_ratio": get_quick_ratio(m),
            "dividend_yield_pct": get_div_yield(m),
            "altman_z": z, "altman_zone": altman_zone(z),
            "piotroski_f": fs,
            "rsi": rsi, "macd": macd, "sma50": s50, "sma200": s200,
            "technical_trend": trend,
            "analyst_strong_buy": sb, "analyst_buy": b, "analyst_hold": h,
            "analyst_sell": se, "analyst_strong_sell": ss,
            "analyst_total": total,
            "consensus_target": tp, "consensus_upside_pct": upside,
            "earnings_history": eq,
            "composite_score": sc['total'],
            "score_fundamental": sc['fundamental'],
            "score_technical": sc['technical'],
            "score_analyst": sc['analyst'],
            "score_accounting": sc['accounting']
        },
        "macro": macro
    }

    try:
        payload=json.dumps({
            'model':'gpt-4o-mini','max_tokens':2000,
            'messages':[
                {'role':'system','content':SYSTEM_PROMPT},
                {'role':'user','content':json.dumps(user_data)}
            ]
        }).encode()
        req=urllib.request.Request('https://api.openai.com/v1/chat/completions',data=payload,
            headers={'Content-Type':'application/json','Authorization':f'Bearer {OPENAI}'})
        with urllib.request.urlopen(req,timeout=35) as r:
            data=json.loads(r.read()); text=data['choices'][0]['message']['content']
            return json.loads(text.replace('```json','').replace('```','').strip())
    except:
        return fallback(name,pm,om,roe,roa,de,cr,rg,rsi,s50,s200,sb,b,h,se,ss,tp,z,fs,sc,upside,fcf)

def fallback(name,pm,om,roe,roa,de,cr,rg,rsi,s50,s200,sb,b,h,se,ss,tp,z,fs,sc,upside,fcf):
    sv=sc['total']; col='green' if sv>=70 else 'red' if sv<50 else 'yellow'; icon='bull' if sv>=70 else 'bear' if sv<50 else 'neutral'
    trend='bullish (SMA50>SMA200)' if s50 and s200 and s50>s200 else 'bearish (SMA50<SMA200)' if s50 and s200 else 'indeterminate'
    total=sb+b+h+se+ss
    return {
        'verdict': f"Score {sv}/100",
        'verdict_sub': f"Net margin {pm:.1f}%, ROE {roe:.1f}%, D/E {de:.2f}x — composite {sv}/100.",
        'verdict_color': col, 'verdict_icon': icon,
        'capital': f"D/E of {de:.2f}x. ROE {roe:.1f}% and ROA {roa:.1f}%.",
        'cashflow': f"Net margin {pm:.1f}%, operating margin {om:.1f}%. FCF: {fcf or 'N/A'}.",
        'technical': f"RSI {rsi or 'N/A'}, trend {trend}.",
        'analyst_view': f"{sb+b}/{total} analysts rate Buy. Target {'$'+str(round(tp,2)) if tp else 'N/A'}.",
        'solvency': f"Altman Z {z or 'N/A'} ({altman_zone(z)}). Piotroski F {fs}/9.",
        'risks': f"D/E {de:.2f}x leverage. Revenue growth {rg:.1f}%.",
        'credit_decision': f"D/E {de:.2f}x, net margin {pm:.1f}%.",
        'retail_summary': {
            'what_they_do': f"{name} — {pm:.1f}% net margin business.",
            'price_story': f"Technical data N/A — candles not available on current data tier.",
            'is_it_cheap': f"ROE {roe:.1f}%, score {sv}/100.",
            'making_money': f"Keeps ${pm:.1f} from every $100 in revenue.",
            'debt_plain': f"D/E ratio {de:.2f}x.",
            'main_risk_plain': f"Revenue growth {rg:.1f}%. Leverage {de:.2f}x.",
            'analyst_take_plain': f"{sb+b} analysts rate Buy out of {total}. Target {'$'+str(round(tp,2)) if tp else 'unavailable'}.",
            'verdict_plain': f"Score {sv}/100 — {'positive' if sv>=70 else 'cautious' if sv>=50 else 'negative'} outlook."
        },
        'methodology_notes': [
            f"Technical indicators (RSI, MACD, SMA) are N/A — candle data not available on current Finnhub tier. Technical pillar score defaults to 12.5/25.",
            f"Beta period is unspecified by data provider — treat as indicative only."
        ]
    }

# ── Main ──────────────────────────────────────────────────────────────────────
def analyse(ticker):
    now=int(time.time()); yr_ago=now-366*24*3600

    with ThreadPoolExecutor(max_workers=6) as ex:
        futs={
            'profile': ex.submit(fh,'stock/profile2',{'symbol':ticker}),
            'quote':   ex.submit(fh,'quote',{'symbol':ticker}),
            'metrics': ex.submit(fh,'stock/metric',{'symbol':ticker,'metric':'all'}),
            'recs':    ex.submit(fh,'stock/recommendation-trends',{'symbol':ticker}),
            'target':  ex.submit(fh,'stock/price-target',{'symbol':ticker}),
            'macro':   ex.submit(get_macro),
        }
        res={k:v.result() for k,v in futs.items()}

    profile=res['profile']
    if not profile.get('name'):
        raise Exception(f'Ticker "{ticker}" not found. Try AAPL, NVDA, MSFT, JPM.')

    time.sleep(0.3)
    candles = fh('stock/candle',{'symbol':ticker,'resolution':'D','from':yr_ago,'to':now}, timeout=15)
    time.sleep(0.2)
    earnings_raw = fh('stock/earnings',{'symbol':ticker}, timeout=10)

    quote=res['quote']; m=res['metrics'].get('metric',{})
    earnings=earnings_raw if isinstance(earnings_raw,list) else []
    recs=res['recs'] if isinstance(res['recs'],list) else []
    target=res['target'] if isinstance(res['target'],dict) else {}
    macro=res['macro']

    closes=[c for c in (candles.get('c') or []) if c is not None]
    rsi =calc_rsi(closes) if len(closes)>=15 else None
    macd=calc_macd(closes) if len(closes)>=35 else None
    s50 =calc_sma(closes,50); s200=calc_sma(closes,200)

    price=quote.get('c'); change=quote.get('d'); chg_pct=quote.get('dp')
    rec=recs[0] if recs else {}
    sb=rec.get('strongBuy',0); b=rec.get('buy',0); h=rec.get('hold',0)
    se=rec.get('sell',0); ss=rec.get('strongSell',0)
    tp=target.get('targetMean')
    upside=round((tp-price)/price*100,1) if tp and price and price>0 else None

    sc=compute_score(m,rsi,s50,s200,macd,sb,b,h,se,ss,tp,price)
    z=calc_altman(m); fs=calc_piotroski(m)
    name=profile.get('name',ticker); industry=profile.get('finnhubIndustry','N/A')
    ai=call_openai(ticker,name,industry,price,m,rsi,macd,s50,s200,sb,b,h,se,ss,tp,earnings,z,fs,sc,macro)

    return {
        'ticker':ticker,'name':name,'exchange':profile.get('exchange',''),
        'industry':industry,'logo':profile.get('logo',''),
        'price':price,'change':change,'change_pct':chg_pct,
        'score':sc,'altman':z,'altman_zone':altman_zone(z),
        'piotroski':fs,'piotroski_label':piotroski_label(fs),
        'macro': macro,
        'metrics':{
            'pe':          gm(m,'peBasicExclExtraTTM','peAnnual'),
            'pb':          gm(m,'pbAnnual'),
            'ps':          gm(m,'psTTM','psAnnual'),
            'ev_ebitda':   get_ev_ebitda(m),
            'net_margin':  get_net_margin(m),
            'op_margin':   gm(m,'operatingMarginAnnual','operatingMarginTTM'),
            'gross_margin':gm(m,'grossMarginAnnual','grossMarginTTM'),
            'fcf_margin':  get_fcf_margin(m),
            'roe':         gm(m,'roeAnnual','roeTTM'),
            'roa':         gm(m,'roaAnnual','roaTTM'),
            'roic':        gm(m,'roicAnnual','roiAnnual','roicTTM'),
            'rev_growth':  get_rev_growth(m),
            'eps_growth':  get_eps_growth(m),
            'eps':         get_eps(m),
            'de':          get_de(m),
            'current_ratio':gm(m,'currentRatioAnnual','currentRatioQuarterly'),
            'quick_ratio': gm(m,'quickRatioAnnual','quickRatioQuarterly'),
            'div_yield':   get_div_yield(m),
            'fcf':         get_fcf_str(m),
            'week52_high': gm(m,'52WeekHigh'),
            'week52_low':  gm(m,'52WeekLow'),
            'beta':        gm(m,'beta'),
            'asset_turnover':gm(m,'assetTurnoverAnnual','assetTurnoverTTM'),
        },
        'technical':{'rsi':rsi,'macd':macd,'sma50':s50,'sma200':s200},
        'analyst':{'strong_buy':sb,'buy':b,'hold':h,'sell':se,'strong_sell':ss,
                   'total':sb+b+h+se+ss,'target_price':tp,'upside':upside},
        'earnings':[{'period':e.get('period'),'actual':e.get('actual'),
                     'estimate':e.get('estimate'),'surprise':e.get('surprisePercent')}
                    for e in earnings[:8]],
        'ai':ai,
    }

class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin','*')
        self.end_headers()
    def do_GET(self):
        parsed=urllib.parse.urlparse(self.path)
        qs=urllib.parse.parse_qs(parsed.query)
        ticker=(qs.get('ticker',[''])[0]).upper().strip()
        self.send_response(200)
        self.send_header('Content-type','application/json')
        self.send_header('Access-Control-Allow-Origin','*')
        self.end_headers()
        if not ticker:
            self.wfile.write(json.dumps({'error':'Provide ?ticker=AAPL'}).encode()); return
        try:
            self.wfile.write(json.dumps(analyse(ticker)).encode())
        except Exception as e:
            self.wfile.write(json.dumps({'error':str(e)}).encode())
    def log_message(self,*a): pass
