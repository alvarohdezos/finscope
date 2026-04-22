from http.server import BaseHTTPRequestHandler
import json, os, urllib.parse, urllib.request, time
from concurrent.futures import ThreadPoolExecutor

FINNHUB = os.environ.get('FINNHUB_KEY', '')
OPENAI  = os.environ.get('OPENAI_KEY', '')
AV_KEY  = os.environ.get('AV_KEY', '')

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
    'WMT':['TGT','COST','AMZN','KR'],        'COST':['WMT','TGT','BJ','KR'],
    'HD':['LOW','FND','WSM','TSCO'],         'KO':['PEP','KDP','MNST','CELH'],
    'PEP':['KO','KDP','MNST','CELH'],        'MCD':['YUM','SBUX','CMG','DPZ'],
    'SBUX':['MCD','YUM','CMG','DPZ'],        'UNH':['CI','ANTM','HUM','CVS'],
    'ABT':['MDT','SYK','BSX','EW'],          'TMO':['DHR','A','WAT','PKI'],
    'BRK.A':['BRK.B','JPM','BAC','V'],       'BRK.B':['BRK.A','JPM','BAC','V'],
}

def fh(path, params, timeout=10):
    params['token'] = FINNHUB
    url = 'https://finnhub.io/api/v1/' + path + '?' + urllib.parse.urlencode(params)
    try:
        req = urllib.request.Request(url, headers={'Accept':'application/json','User-Agent':'FINscope/3.0'})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except:
        return {}

def fred(series_id):
    try:
        url = f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}'
        req = urllib.request.Request(url, headers={'User-Agent':'FINscope/3.0'})
        with urllib.request.urlopen(req, timeout=7) as r:
            lines = r.read().decode().strip().split('\n')
            for line in reversed(lines):
                parts = line.split(',')
                if len(parts) == 2 and parts[1].strip() not in ('', '.'):
                    try: return float(parts[1].strip())
                    except: continue
    except: pass
    return None

def get_macro():
    try:
        with ThreadPoolExecutor(max_workers=3) as ex:
            futs = {'t10':ex.submit(fred,'DGS10'),'ff':ex.submit(fred,'FEDFUNDS'),'vix':ex.submit(fred,'VIXCLS')}
            res = {k:v.result() for k,v in futs.items()}
        return {'risk_free_rate':res.get('t10') or 4.42,'policy_rate':res.get('ff') or 5.33,
                'cpi_yoy':3.2,'pmi_composite':51.0,'credit_spread_hy':320,'vix':res.get('vix') or 18.0}
    except:
        return {'risk_free_rate':4.42,'policy_rate':5.33,'cpi_yoy':3.2,'pmi_composite':51.0,'credit_spread_hy':320,'vix':18.0}

def _av(function, extra_params, timeout=10):
    params = {'function':function,'apikey':AV_KEY,'datatype':'json'}
    params.update(extra_params)
    url = 'https://www.alphavantage.co/query?' + urllib.parse.urlencode(params)
    try:
        req = urllib.request.Request(url, headers={'User-Agent':'FINscope/3.0'})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
            if isinstance(data, dict) and ('Information' in data or 'Note' in data):
                return {}
            return data
    except:
        return {}

def _sf(v):
    if v in (None,'None','-','','N/A'): return None
    try: return float(str(v).replace(',',''))
    except: return None

def _sfpct(v):
    raw = _sf(v)
    if raw is None: return None
    return round(raw*100, 1)

def _parse_fh_financials(data):
    """Parse Finnhub stock/financials-reported into hist_fin format (fallback when AV rate-limited)."""
    def _find(items, *keys):
        for k in keys:
            for item in items:
                c = item.get('concept','')
                if c == k or c.endswith(':'+k):
                    v = item.get('value')
                    if v is not None:
                        try: return float(v)
                        except: pass
        return None
    reports = (data.get('data') or [])[:4]
    hist = []
    for rep in reports:
        year = (rep.get('endDate') or rep.get('startDate') or '')[:4]
        report = rep.get('report') or {}
        ic = report.get('ic') or []; cf_s = report.get('cf') or []
        r   = _find(ic,'Revenues','RevenueFromContractWithCustomerExcludingAssessedTax','SalesRevenueNet','RevenueFromContractWithCustomerIncludingAssessedTax')
        ni  = _find(ic,'NetIncomeLoss','NetIncome','ProfitLoss')
        gp  = _find(ic,'GrossProfit')
        oi  = _find(ic,'OperatingIncomeLoss','IncomeLossFromContinuingOperationsBeforeIncomeTaxes')
        ocf = _find(cf_s,'NetCashProvidedByUsedInOperatingActivities','NetCashProvidedByOperatingActivities')
        cpx = _find(cf_s,'PaymentsToAcquirePropertyPlantAndEquipment','PaymentsForCapitalImprovements')
        fcf_h = (ocf - abs(cpx)) if (ocf is not None and cpx is not None) else None
        if r and r > 0:
            hist.append({'year':year,'revenue_m':round(r/1e6),
                'net_income_m':round(ni/1e6) if ni is not None else None,
                'operating_income_m':round(oi/1e6) if oi is not None else None,
                'fcf_m':round(fcf_h/1e6) if fcf_h is not None else None,
                'gross_margin_pct':round(gp/r*100,1) if gp else None,
                'operating_margin_pct':round(oi/r*100,1) if oi else None,
                'net_margin_pct':round(ni/r*100,1) if ni else None})
    return hist

def get_yf_data(ticker):
    """Yahoo Finance quoteSummary — no API key needed. Third source for missing metrics."""
    modules = 'defaultKeyStatistics,financialData,summaryDetail,calendarEvents'
    url = f'https://query1.finance.yahoo.com/v10/finance/quoteSummary/{ticker}?modules={urllib.parse.quote(modules)}'
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (compatible; FINscope/3.0)',
            'Accept': 'application/json',
        })
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        result = (data.get('quoteSummary') or {}).get('result') or []
        if not result: return {}
        obj = result[0]
        ks = obj.get('defaultKeyStatistics') or {}
        fd = obj.get('financialData') or {}
        sd = obj.get('summaryDetail') or {}
        ce = obj.get('calendarEvents') or {}

        def _yf(d, *keys):
            for k in keys:
                v = d.get(k)
                if isinstance(v, dict): v = v.get('raw')
                if v is not None:
                    try: return float(v)
                    except: pass
            return None

        def _pct(v): return round(v*100, 2) if (v is not None and abs(v) < 3) else v

        fcf_yf  = _yf(fd,'freeCashflow')
        rev_yf  = _yf(fd,'totalRevenue')
        fcf_m_yf = round(fcf_yf/rev_yf*100,1) if (fcf_yf and rev_yf and rev_yf>0) else None
        fcf_s_yf = None
        if fcf_yf is not None:
            fcf_s_yf = f"${fcf_yf/1e9:.1f}B" if abs(fcf_yf)>=1e9 else f"${fcf_yf/1e6:.0f}M"

        pct_inst = _yf(ks,'heldPercentInstitutions')
        pct_insi = _yf(ks,'heldPercentInsiders')
        if pct_inst is not None and pct_inst < 2: pct_inst = round(pct_inst*100, 2)
        if pct_insi is not None and pct_insi < 2: pct_insi = round(pct_insi*100, 2)

        mc_yf = _yf(sd,'marketCap')
        earn_dates = (ce.get('earnings') or {}).get('earningsDate') or []
        next_earn = None
        for ed in earn_dates:
            ts = ed.get('raw') if isinstance(ed, dict) else ed
            if ts:
                try: next_earn = time.strftime('%Y-%m-%d', time.gmtime(float(ts)))
                except: pass
                break

        return {
            'pe_forward':       _yf(ks,'forwardPE'),
            'ev_ebitda':        _yf(ks,'enterpriseToEbitda'),
            'pb':               _yf(ks,'priceToBook'),
            'beta':             _yf(ks,'beta'),
            'eps_fwd':          _yf(ks,'forwardEps'),
            'pct_institutions': pct_inst,
            'pct_insiders':     pct_insi,
            'fcf_raw':          fcf_yf,
            'fcf_str':          fcf_s_yf,
            'fcf_margin':       fcf_m_yf,
            'rev_ttm':          rev_yf,
            'op_margin':        _pct(_yf(fd,'operatingMargins')),
            'net_margin':       _pct(_yf(fd,'profitMargins')),
            'roe':              _pct(_yf(fd,'returnOnEquity')),
            'roa':              _pct(_yf(fd,'returnOnAssets')),
            'rev_growth':       _pct(_yf(fd,'revenueGrowth')),
            'eps_growth':       _pct(_yf(fd,'earningsGrowth')),
            'gross_margin':     _pct(_yf(fd,'grossMargins')),
            'div_yield':        _pct(_yf(sd,'dividendYield')),
            'target_price':     _yf(fd,'targetMeanPrice'),
            'current_ratio':    _yf(fd,'currentRatio'),
            'de':               _yf(fd,'debtToEquity'),
            'week52_high':      _yf(sd,'fiftyTwoWeekHigh'),
            'week52_low':       _yf(sd,'fiftyTwoWeekLow'),
            'market_cap':       round(mc_yf/1e6) if mc_yf else None,
            'upcoming_earnings': next_earn,
        }
    except:
        return {}

def get_av_data(ticker):
    with ThreadPoolExecutor(max_workers=3) as ex:
        f_ov  = ex.submit(_av,'OVERVIEW',{'symbol':ticker},10)
        f_inc = ex.submit(_av,'INCOME_STATEMENT',{'symbol':ticker},12)
        f_cf  = ex.submit(_av,'CASH_FLOW',{'symbol':ticker},12)
        try:    ov      = f_ov.result(timeout=11) or {}
        except: ov      = {}
        try:    inc_rep = (f_inc.result(timeout=13) or {}).get('annualReports') or []
        except: inc_rep = []
        try:    cf_rep  = (f_cf.result(timeout=13) or {}).get('annualReports') or []
        except: cf_rep  = []
    inc_rep = inc_rep[:4]; cf_rep = cf_rep[:4]

    ev_ebitda  = _sf(ov.get('EVToEBITDA'));      pe_ttm    = _sf(ov.get('TrailingPE'))
    pe_forward = _sf(ov.get('ForwardPE'));        pb        = _sf(ov.get('PriceToBookRatio'))
    net_margin = _sfpct(ov.get('ProfitMargin'));  op_margin = _sfpct(ov.get('OperatingMarginTTM'))
    roe        = _sfpct(ov.get('ReturnOnEquityTTM')); roa   = _sfpct(ov.get('ReturnOnAssetsTTM'))
    rev_growth = _sfpct(ov.get('QuarterlyRevenueGrowthYOY'))
    eps_growth = _sfpct(ov.get('QuarterlyEarningsGrowthYOY'))
    eps_ttm    = _sf(ov.get('EPS')) or _sf(ov.get('DilutedEPSTTM'))
    beta       = _sf(ov.get('Beta'))
    week52_high= _sf(ov.get('52WeekHigh')); week52_low = _sf(ov.get('52WeekLow'))
    target_price = _sf(ov.get('AnalystTargetPrice'))
    div_yield_raw = _sf(ov.get('DividendYield'))
    div_yield  = round(div_yield_raw*100,2) if div_yield_raw else None
    rev_ttm    = _sf(ov.get('RevenueTTM')); gp_ttm = _sf(ov.get('GrossProfitTTM'))
    mc_raw     = _sf(ov.get('MarketCapitalization'))
    market_cap_m = round(mc_raw/1e6) if mc_raw else None
    gross_margin = round(gp_ttm/rev_ttm*100,1) if gp_ttm and rev_ttm else None
    # PercentInstitutions is already a percentage value (e.g. "65.27" = 65.27%)
    pct_inst   = _sf(ov.get('PercentInstitutions'))
    pct_insi   = _sf(ov.get('PercentInsiders'))
    description= ov.get('Description','') or ''
    country    = ov.get('Country','') or ''
    sector     = ov.get('Sector','') or ''
    industry   = ov.get('Industry','') or ''
    employees  = ov.get('FullTimeEmployees','') or ''
    shares_out = _sf(ov.get('SharesOutstanding'))

    cf_latest = cf_rep[0] if cf_rep else {}
    op_cf = _sf(cf_latest.get('operatingCashflow')); capex = _sf(cf_latest.get('capitalExpenditures'))
    fcf_raw = op_cf - abs(capex) if (op_cf is not None and capex is not None) else None
    fcf_str = None; fcf_margin = None
    if fcf_raw is not None:
        fcf_str = f"${fcf_raw/1e9:.1f}B" if abs(fcf_raw)>=1e9 else f"${fcf_raw/1e6:.0f}M"
        if rev_ttm and rev_ttm > 0:
            fcf_margin = round(fcf_raw/rev_ttm*100,1)

    hist_fin = []
    for i in range(min(4,len(inc_rep))):
        inc = inc_rep[i] or {}; cf = cf_rep[i] if i < len(cf_rep) else {}
        year = (inc.get('fiscalDateEnding') or '')[:4]
        r  = _sf(inc.get('totalRevenue'));  ni = _sf(inc.get('netIncome'))
        gp = _sf(inc.get('grossProfit'));   oi = _sf(inc.get('operatingIncome'))
        op_cf_h = _sf(cf.get('operatingCashflow')); capex_h = _sf(cf.get('capitalExpenditures'))
        fcf_h = (op_cf_h - abs(capex_h)) if (op_cf_h is not None and capex_h is not None) else None
        if r and r > 0:
            hist_fin.append({'year':year,'revenue_m':round(r/1e6),
                'net_income_m':round(ni/1e6) if ni is not None else None,
                'operating_income_m':round(oi/1e6) if oi is not None else None,
                'fcf_m':round(fcf_h/1e6) if fcf_h is not None else None,
                'gross_margin_pct':round(gp/r*100,1) if gp else None,
                'operating_margin_pct':round(oi/r*100,1) if oi else None,
                'net_margin_pct':round(ni/r*100,1) if ni else None})

    return {
        'ev_ebitda':ev_ebitda,'pe_ttm':pe_ttm,'pe_forward':pe_forward,'pb':pb,
        'net_margin':net_margin,'op_margin':op_margin,'gross_margin':gross_margin,
        'roe':roe,'roa':roa,'rev_growth':rev_growth,'eps_growth':eps_growth,
        'eps_ttm':eps_ttm,'beta':beta,'week52_high':week52_high,'week52_low':week52_low,
        'target_price':target_price,'div_yield':div_yield,
        'fcf_raw':fcf_raw,'fcf_str':fcf_str,'fcf_margin':fcf_margin,
        'market_cap':market_cap_m,'rev_ttm':rev_ttm,
        'pct_institutions':pct_inst,'pct_insiders':pct_insi,
        'description':description[:1200],'country':country,'sector':sector,'industry':industry,
        'employees':employees,'shares_out':shares_out,
        'historical_financials':hist_fin,
    }

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
    raw = gm(m,'totalDebt/totalEquityAnnual','totalDebt/totalEquityQuarterly','debtToEquityAnnual','longTermDebt/equityAnnual')
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

def compute_score(pm, om, roe, roa, rg, de, cr, fcf_raw, sb, b, h, se, ss, tp, price):
    f = 20
    if pm is not None: f += 7 if pm>25 else 5 if pm>15 else 2 if pm>8 else (-5 if pm<0 else 0)
    if om is not None: f += 6 if om>30 else 4 if om>20 else 2 if om>10 else (-4 if om<0 else 0)
    if roe is not None: f += 6 if roe>30 else 3 if roe>15 else (-4 if roe<0 else 0)
    if roa is not None: f += 4 if roa>15 else 2 if roa>8 else (-2 if roa<0 else 0)
    if rg is not None: f += 6 if rg>20 else 3 if rg>10 else 1 if rg>0 else -4
    f = max(0, min(40, f))
    a = 15
    total = (sb or 0)+(b or 0)+(h or 0)+(se or 0)+(ss or 0)
    if total > 0:
        br = (sb+b)/total; sr = (se+ss)/total
        a += 10 if br>0.7 else 6 if br>0.5 else 2 if br>0.3 else 0
        a -= 8 if sr>0.5 else 4 if sr>0.3 else 0
    if tp and price and price > 0:
        up = (tp-price)/price*100
        a += 5 if up>20 else 2 if up>10 else 1 if up>0 else (-5 if up<-10 else -2)
    a = max(0, min(30, a))
    acc = 10
    if de is not None: acc += 5 if de<0.3 else 3 if de<1 else (-5 if de>3 else -2 if de>2 else 0)
    if cr is not None: acc += 3 if cr>2 else 1 if cr>1.2 else (-3 if 0<cr<1 else 0)
    if fcf_raw is not None: acc += 3 if float(fcf_raw)>0 else -3
    acc = max(0, min(20, acc))
    return {'total':max(5,min(98,round(f+a+acc+5))),
            'fundamental':round(f),'accounting':round(acc),'analyst':round(a),'context':5}

def calc_altman(m, av):
    try:
        roa = resolve(gm(m,'roaAnnual','roaTTM'), av.get('roa')) or 0
        at  = gm(m,'assetTurnoverAnnual','assetTurnoverTTM') or 0.8
        cr  = gm(m,'currentRatioAnnual','currentRatioQuarterly') or 1
        de  = resolve(get_de_fh(m), av.get('de')) or 1.0
        roa = roa/100 if roa > 1 else roa
        x1  = max(0,(cr-1)*0.25); x2 = max(0,roa*0.4); x3 = max(0,roa*1.3)
        x4  = min(5.0, 1/de) if de > 0 else 3.0
        return round(1.2*x1 + 1.4*x2 + 3.3*x3 + 0.6*x4 + at, 2)
    except: return None

def altman_zone(z, lang='en'):
    if z is None: return 'N/A'
    if lang=='es':
        return 'Zona segura (Z>3)' if z>2.99 else 'Zona gris' if z>1.81 else 'Distress (Z<1.8)'
    return 'Safe (Z>3)' if z>2.99 else 'Grey zone' if z>1.81 else 'Distress (Z<1.8)'

def calc_piotroski(m, av):
    s = 0
    roa  = resolve(gm(m,'roaAnnual','roaTTM'), av.get('roa')) or 0
    fcf  = av.get('fcf_raw') or gm(m,'freeCashFlowAnnual','freeCashFlowTTM') or 0
    pm   = resolve(gm(m,'netMarginAnnual','netMarginTTM'), av.get('net_margin')) or 0
    fcfm = av.get('fcf_margin') or 0
    gma  = gm(m,'grossMarginAnnual') or 0
    gmt  = resolve(gm(m,'grossMarginTTM'), av.get('gross_margin')) or 0
    ata  = gm(m,'assetTurnoverAnnual') or 0; att = gm(m,'assetTurnoverTTM') or 0
    cra  = gm(m,'currentRatioAnnual') or 0; crq = gm(m,'currentRatioQuarterly') or 0
    de   = resolve(get_de_fh(m), av.get('de')) or 0
    rg   = resolve(get_rev_growth_fh(m), av.get('rev_growth')) or 0
    eg   = get_eps_growth_fh(m) or 0
    if roa > 0: s += 1
    if float(fcf) > 0: s += 1
    if gm(m,'roaTTM') and (gm(m,'roaTTM') or 0) >= roa*0.9: s += 1
    if fcfm > pm: s += 1
    if de < 1.0: s += 1
    if crq >= cra: s += 1
    if eg >= rg*0.9: s += 1
    if gmt >= gma: s += 1
    if att >= ata*0.95: s += 1
    return min(9, s)

def piotroski_label(f, lang='en'):
    if lang=='es':
        return 'Calidad alta' if f>=7 else 'Calidad media' if f>=4 else 'Senales debiles'
    return 'Strong quality' if f>=7 else 'Moderate quality' if f>=4 else 'Weak signals'

def prompt_a(lang='en'):
    lt = 'Write all content in natural, fluent Spanish. Keep section JSON keys in English.' if lang=='es' else 'Write all content in clear, professional English suitable for institutional finance.'
    return """You are a senior equity research analyst at Goldman Sachs Equity Research writing an INFORMATIONAL REPORT (not investment advice). Return ONLY valid JSON matching the schema exactly. No markdown fences, no preamble.

"""+lt+"""

CRITICAL STYLE RULES:
- Every analytical sentence MUST contain at least one specific number from the input data
- Use neutral framing: "The data suggests", "From a fundamental standpoint", "The financials indicate". NEVER say "we recommend", "investors should buy/sell", "this stock will"
- Explain WHY each metric matters, not just state the value
- Use the historical_financials array to show multi-year trends with exact YoY comparisons
- Use the company description to understand the business. Reference specific products/segments
- MINIMUM CONTENT: Each section text field MUST have at least 12 substantive sentences. Do not be brief.

REQUIRED JSON SCHEMA:
{"executive_summary":{"verdict":"3-6 word neutral status","verdict_sub":"1-2 sentence position with 2+ numbers","verdict_color":"green|amber|red","verdict_icon":"bull|neutral|bear|watch","text":"12-15 sentences covering: business in 1 sentence, composite score context with drivers, 2 key strengths with exact figures, 2 key risks with figures, valuation position, stance framing. Target ~250-300 words."},"business_model":{"text":"12-15 sentences covering: revenue streams (what products/services, their contribution), moat type (brand/network/scale/IP) with quantified evidence, customer or segment concentration with %, key geographic markets and why they matter, recent strategic shifts (M&A, launches, divestments), historical inflection points, competitive positioning vs sector. Target ~300-400 words.","revenue_segments":[{"name":"Segment","pct":50,"description":"what it covers"}],"geographic_exposure":[{"region":"United States","pct":45,"note":"why this market matters for the company"}]},"performance":{"text":"12-14 sentences covering: stock YTD vs S&P 500 with figures, 1Y total return, price vs 52W extremes with % distance, revenue growth trajectory across last 4 years using historical_financials, operating margin trend (expansion or compression with exact pp change), EPS growth context, notable catalysts in past 12 months, beta interpretation, dividend/buyback contribution. Target ~280-340 words."},"financial_quality":{"text":"14-16 sentences deep dive: gross margin level and multi-year trend with exact pp change, operating leverage (revenue growth vs operating income growth), FCF generation with absolute figure and margin, ROIC context, debt load with D/E interpretation. Then EXPLAIN Altman Z-Score: the 5 factors are X1=Working Capital/Total Assets (liquidity), X2=Retained Earnings/Total Assets (cumulative profitability), X3=EBIT/Total Assets (operating efficiency), X4=Market Cap/Book Value of Liabilities (solvency buffer), X5=Sales/Total Assets (asset utilization); values above 2.99 = safe zone, 1.81-2.99 = grey zone, below 1.81 = distress; note it is invalid for banks. Then EXPLAIN Piotroski F-Score: 9-point signal with Profitability (ROA positive, FCF positive, ROA improving, FCF>NI), Leverage (D/E declining, Current Ratio improving, no dilution), and Efficiency (Gross Margin improving, Asset Turnover improving); 7-9 = strong, 4-6 = moderate, 0-3 = deteriorating. Target ~380-460 words."},"sec_filings":{"text":"12-14 sentences drawing on most recent 10-K/10-Q: revenue recognition highlights with figures, management guidance with specific numbers, material risk factors disclosed with quantified exposure, segment performance from MD&A, related party or legal proceeding notes, recent insider transaction patterns, any critical accounting changes. Target ~240-300 words.","key_disclosures":["3-5 specific findings from recent filings, each with exact figure"]}}"""

def prompt_b(lang='en'):
    lt = 'Write all content in natural, fluent Spanish. Keep section JSON keys in English.' if lang=='es' else 'Write all content in clear, professional English suitable for institutional finance.'
    return """You are a senior equity research analyst at Goldman Sachs writing an INFORMATIONAL REPORT (not investment advice). Return ONLY valid JSON. No markdown.

"""+lt+"""

RULES:
- Every sentence includes specific numbers
- Neutral tone: "The data suggests...", never "we recommend"
- Explain WHY metrics matter (WACC, FCF yield, multiples)
- Tailor macro analysis to THIS company's actual geographic exposure
- MINIMUM CONTENT: Each section text field MUST have at least 12 substantive sentences. Do not be brief.

SECTOR WACC BENCHMARKS (adjust +0.5-1.0pp if risk_free_rate >4.5%):
UTILITIES 5.0-6.5% | REITS 5.5-7.0% | STAPLES 6.0-7.5% | TELECOM 6.5-8.5% | HEALTHCARE 7.5-9.5% | INDUSTRIALS 7.5-9.5% | RETAIL 8.5-11.0% | TRAVEL 9.5-13.0% | BANKS (use ROE vs CoE ~10-13%, Z-Score invalid) | INSURANCE 8.0-10.5% | FINTECH 9.0-12.0% | ENERGY MAJORS 8.0-10.0% | ENERGY E&P 10.0-14.0% | RENEWABLES 7.5-10.0% | MATERIALS 9.0-12.0% | PHARMA 8.0-9.0% | BIOTECH 12.0-18.0% | SEMIS 10.0-12.0% | SOFTWARE 9.0-12.0% | HARDWARE 10.0-13.0% | INTERNET 9.5-12.0%

REQUIRED JSON SCHEMA:
{"macro_context":{"text":"12-15 sentences, SPECIFIC to this company. Start with its geographic revenue breakdown. For each key region discuss specific macro dynamics. Then sector-specific macro. Then geopolitical risks relevant to THIS company. Then interest rate implications at current 10Y yield. Target ~300-370 words."},"risk_analysis":{"text":"12-14 sentences covering the MOST material risks for this company specifically. Include fundamental, operational, competitive, regulatory, and macro risks. Each risk quantified where possible. Target ~240-300 words.","risks":["6-8 specific risks, each 1-2 sentences with a quantified data point. Categories: Valuation risk, Operational risk, Financial risk, Regulatory risk, Competitive risk, Macro risk, Technology/disruption risk, Concentration risk"]},"ownership":{"text":"12-14 sentences: EXPLAIN agency theory (principal-agent problem between shareholders and management); institutional ownership % and implications (high = stable but herd risk, low = retail volatility); name 3-5 typical top institutional holders for this size company; insider ownership and alignment signals; comment on insider MSPr (Monthly Share Purchase Ratio, positive = net buying); executive compensation alignment; board composition; capital return policy with payout ratio figure; free float and liquidity. Target ~260-320 words.","top_holders":[{"name":"Holder name","stake_pct":8.5}]},"valuation":{"text":"14-16 sentences. EXPLAIN each multiple: PE Ratio measures how much investors pay per dollar of earnings; EV/EBITDA is more comparable across capital structures; P/B measures premium over net asset value; FCF Yield is conceptually equivalent to a bond yield. Compare multiples to sector median. EXPLAIN WACC: Ke = Rf + Beta x ERP (CAPM); Kd x (1-t) for after-tax debt cost; WACC = Ke x E/V + Kd(1-t) x D/V. Discuss ROIC vs WACC spread - when ROIC exceeds WACC the company creates economic profit. EXPLAIN DCF: projects FCF discounted at WACC; terminal value is 60-80% of total and highly sensitive to terminal growth rate (1pp change moves fair value 15-25%). State fair value range, WACC assumption, margin of safety vs current price. Target ~380-460 words.","fair_value_low":100,"fair_value_high":150,"wacc_used":9.5},"competitors":{"text":"12-14 sentences positioning this company vs peer group. State margin leadership rank with exact figures. Compare growth rank with numbers. State valuation premium/discount vs peer median with exact %. Contextualize each peer 1-2 sentences. Target ~280-340 words.","table":[{"ticker":"SUBJ","name":"Full Name","pe":35.2,"ev_ebitda":31.1,"rev_growth_pct":15.0,"net_margin_pct":25.0,"gross_margin_pct":60.0,"roe_pct":30.0,"is_subject":true},{"ticker":"P1","name":"Peer 1","pe":40.0,"ev_ebitda":25.0,"rev_growth_pct":10.0,"net_margin_pct":15.0,"gross_margin_pct":50.0,"roe_pct":20.0,"is_subject":false},{"ticker":"P2","name":"Peer 2","pe":28.0,"ev_ebitda":18.0,"rev_growth_pct":8.0,"net_margin_pct":18.0,"gross_margin_pct":55.0,"roe_pct":22.0,"is_subject":false},{"ticker":"P3","name":"Peer 3","pe":30.0,"ev_ebitda":22.0,"rev_growth_pct":12.0,"net_margin_pct":12.0,"gross_margin_pct":48.0,"roe_pct":18.0,"is_subject":false},{"ticker":"P4","name":"Peer 4","pe":22.0,"ev_ebitda":15.0,"rev_growth_pct":5.0,"net_margin_pct":14.0,"gross_margin_pct":45.0,"roe_pct":14.0,"is_subject":false}]},"scenarios":{"text":"4-5 sentence intro framing the range, current price as anchor, probability-weighted expected return with figures.","bull":{"label":"Bull Case","price_target":180,"upside_pct":25,"probability_pct":30,"thesis":"4-5 sentences: specific catalyst with timeline, revenue/margin assumption with exact figures, implied forward multiple at target."},"base":{"label":"Base Case","price_target":145,"upside_pct":5,"probability_pct":50,"thesis":"4-5 sentences with central assumptions and multiple at target."},"bear":{"label":"Bear Case","price_target":90,"downside_pct":35,"probability_pct":20,"thesis":"4-5 sentences: downside catalyst with quantified impact, multiple compression, trigger threshold."}}}"""

def _repair_json(text):
    text = text.strip()
    if not text: return None
    text = text.replace('```json','').replace('```','').strip()
    try: return json.loads(text)
    except: pass
    opens = 0; open_sq = 0; in_str = False; escape = False
    for c in text:
        if escape: escape = False; continue
        if c == '\\': escape = True; continue
        if c == '"' and not escape: in_str = not in_str; continue
        if in_str: continue
        if c == '{': opens += 1
        elif c == '}': opens -= 1
        elif c == '[': open_sq += 1
        elif c == ']': open_sq -= 1
    if in_str: text += '"'
    text += ']'*max(0,open_sq)
    text += '}'*max(0,opens)
    try: return json.loads(text)
    except: return None

def call_openai(system_prompt, user_data, max_tokens=2800):
    try:
        payload = json.dumps({
            'model':'gpt-4o-mini','max_tokens':max_tokens,
            'messages':[{'role':'system','content':system_prompt},{'role':'user','content':json.dumps(user_data)}]
        }).encode()
        req = urllib.request.Request('https://api.openai.com/v1/chat/completions', data=payload,
            headers={'Content-Type':'application/json','Authorization':f'Bearer {OPENAI}'})
        with urllib.request.urlopen(req, timeout=50) as r:
            data = json.loads(r.read())
            text = data['choices'][0]['message']['content']
            result = _repair_json(text)
            if result: return result
            return {'_error':'JSON parse failed after repair attempt'}
    except Exception as e:
        return {'_error':str(e)}

def _fallback_a(name, sc, fs, lang='en'):
    if lang=='es':
        return {
            'executive_summary':{'verdict':f'Score {sc["total"]}/100','verdict_sub':'Sintesis AI no disponible.','verdict_color':'amber','verdict_icon':'neutral','text':f'Sintesis completa no disponible. Score compuesto {sc["total"]}/100.'},
            'business_model':{'text':f'{name} sintesis AI no disponible.','revenue_segments':[],'geographic_exposure':[]},
            'performance':{'text':'Sintesis AI no disponible.'},
            'financial_quality':{'text':f'Piotroski F {fs}/9. Sintesis completa no disponible.'},
            'sec_filings':{'text':'Sintesis AI no disponible.','key_disclosures':[]}
        }
    return {
        'executive_summary':{'verdict':f'Score {sc["total"]}/100','verdict_sub':'AI synthesis unavailable.','verdict_color':'amber','verdict_icon':'neutral','text':f'Full AI synthesis unavailable. Composite score {sc["total"]}/100. Review the quantitative metrics in sidebar.'},
        'business_model':{'text':f'{name} AI synthesis unavailable. Please retry.','revenue_segments':[],'geographic_exposure':[]},
        'performance':{'text':'AI synthesis unavailable.'},
        'financial_quality':{'text':f'Piotroski F {fs}/9. Full AI synthesis unavailable.'},
        'sec_filings':{'text':'AI synthesis unavailable.','key_disclosures':[]}
    }

def _fallback_b(lang='en'):
    msg = 'Sintesis AI no disponible.' if lang=='es' else 'AI synthesis unavailable.'
    return {
        'macro_context':{'text':msg},
        'risk_analysis':{'text':msg,'risks':[]},
        'ownership':{'text':msg,'top_holders':[]},
        'valuation':{'text':msg,'fair_value_low':0,'fair_value_high':0,'wacc_used':0},
        'competitors':{'text':msg,'table':[]},
        'scenarios':{'text':msg,'bull':{'label':'Bull','price_target':0,'upside_pct':0,'probability_pct':33,'thesis':msg},'base':{'label':'Base','price_target':0,'upside_pct':0,'probability_pct':34,'thesis':msg},'bear':{'label':'Bear','price_target':0,'downside_pct':0,'probability_pct':33,'thesis':msg}}
    }

def analyse(ticker, lang='en'):
    now_ts    = int(time.time())
    from_date = time.strftime('%Y-%m-%d', time.gmtime(now_ts - 30*24*3600))
    to_date   = time.strftime('%Y-%m-%d', time.gmtime(now_ts))

    # All sources in parallel: Finnhub + Alpha Vantage + Yahoo Finance + FRED + Finnhub financials
    with ThreadPoolExecutor(max_workers=12) as ex:
        futs = {
            'profile':  ex.submit(fh,'stock/profile2',{'symbol':ticker}),
            'quote':    ex.submit(fh,'quote',{'symbol':ticker}),
            'metrics':  ex.submit(fh,'stock/metric',{'symbol':ticker,'metric':'all'}),
            'recs':     ex.submit(fh,'stock/recommendation-trends',{'symbol':ticker}),
            'target':   ex.submit(fh,'stock/price-target',{'symbol':ticker}),
            'earnings': ex.submit(fh,'stock/earnings',{'symbol':ticker}),
            'news':     ex.submit(fh,'company-news',{'symbol':ticker,'from':from_date,'to':to_date}),
            'insider':  ex.submit(fh,'stock/insider-sentiment',{'symbol':ticker,'from':from_date,'to':to_date}),
            'macro':    ex.submit(get_macro),
            'av':       ex.submit(get_av_data, ticker),
            'yf':       ex.submit(get_yf_data, ticker),
            'fh_fin':   ex.submit(fh,'stock/financials-reported',{'symbol':ticker,'freq':'annual'},14),
        }
        res = {}
        for k, fut in futs.items():
            try:    res[k] = fut.result(timeout=25)
            except: res[k] = {}

    profile     = res.get('profile') or {}
    if not profile.get('name'):
        raise Exception(f'Ticker "{ticker}" not found. Try AAPL, NVDA, MSFT, JPM.')

    quote       = res.get('quote') or {}
    m_fh        = (res.get('metrics') or {}).get('metric') or {}
    recs_raw    = res.get('recs') or {}
    recs        = recs_raw if isinstance(recs_raw,list) else []
    target_raw  = res.get('target') or {}
    target      = target_raw if isinstance(target_raw,dict) else {}
    earnings_raw= res.get('earnings') or {}
    earnings    = earnings_raw if isinstance(earnings_raw,list) else []
    news_list   = res.get('news') or {}
    news_list   = news_list if isinstance(news_list,list) else []
    insider_raw = res.get('insider') or {}
    macro       = res.get('macro') or {}
    av          = res.get('av') or {}
    yf          = res.get('yf') or {}
    fh_fin_raw  = res.get('fh_fin') or {}

    seen_urls = set(); news = []
    for a in news_list[:30]:
        hl = (a.get('headline') or '').strip(); url = a.get('url','')
        if not hl or url in seen_urls or len(hl)<15: continue
        seen_urls.add(url)
        news.append({'headline':hl[:220],'source':a.get('source','') or '','url':url,'datetime':a.get('datetime',0)})
        if len(news)>=8: break

    insider_data = (insider_raw or {}).get('data') or []
    insider_net  = sum((d.get('change',0) or 0) for d in insider_data[-3:])
    insider_mspr = sum((d.get('mspr',0) or 0) for d in insider_data[-3:])

    price  = quote.get('c'); change = quote.get('d'); chg_pct = quote.get('dp')
    rec_fh = recs[0] if recs else {}
    sb = rec_fh.get('strongBuy',0) or 0; b  = rec_fh.get('buy',0) or 0
    h  = rec_fh.get('hold',0) or 0;      se = rec_fh.get('sell',0) or 0
    ss = rec_fh.get('strongSell',0) or 0
    tp = target.get('targetMean') or av.get('target_price') or yf.get('target_price')
    upside = round((tp-price)/price*100,1) if tp and price and price>0 else None

    # 3-source waterfall: Finnhub → Alpha Vantage → Yahoo Finance
    pe_ttm    = resolve(gm(m_fh,'peBasicExclExtraTTM','peAnnual'), av.get('pe_ttm'))
    pe_fwd    = av.get('pe_forward') or yf.get('pe_forward')
    pb        = resolve(gm(m_fh,'pbAnnual'), av.get('pb')) or yf.get('pb')
    ev_ebitda = resolve(gm(m_fh,'evToEbitdaAnnual','evToEbitdaTTM'), av.get('ev_ebitda')) or yf.get('ev_ebitda')
    net_margin= resolve(gm(m_fh,'netMarginAnnual','netMarginTTM','netProfitMarginAnnual'), av.get('net_margin')) or yf.get('net_margin')
    op_margin = resolve(gm(m_fh,'operatingMarginAnnual','operatingMarginTTM'), av.get('op_margin')) or yf.get('op_margin')
    gross_m   = resolve(gm(m_fh,'grossMarginAnnual','grossMarginTTM'), av.get('gross_margin')) or yf.get('gross_margin')
    roe       = resolve(gm(m_fh,'roeAnnual','roeTTM'), av.get('roe')) or yf.get('roe')
    roa       = resolve(gm(m_fh,'roaAnnual','roaTTM'), av.get('roa')) or yf.get('roa')
    roic      = gm(m_fh,'roicAnnual','roiAnnual','roicTTM')
    rev_growth= resolve(get_rev_growth_fh(m_fh), av.get('rev_growth')) or yf.get('rev_growth')
    eps_growth= resolve(get_eps_growth_fh(m_fh), av.get('eps_growth')) or yf.get('eps_growth')
    eps_ttm   = resolve(gm(m_fh,'epsTTM','epsAnnual'), av.get('eps_ttm'))
    de        = resolve(get_de_fh(m_fh), av.get('de')) or yf.get('de')
    cr        = gm(m_fh,'currentRatioAnnual','currentRatioQuarterly') or yf.get('current_ratio')
    qr        = gm(m_fh,'quickRatioAnnual')
    div_yield = resolve(gm(m_fh,'dividendYieldIndicatedAnnual','currentDividendYieldTTM'), av.get('div_yield')) or yf.get('div_yield')
    fcf_raw   = av.get('fcf_raw') or yf.get('fcf_raw') or gm(m_fh,'freeCashFlowAnnual','freeCashFlowTTM')
    fcf_str   = av.get('fcf_str') or yf.get('fcf_str')
    fcf_margin= av.get('fcf_margin') or yf.get('fcf_margin')
    beta      = resolve(gm(m_fh,'beta'), av.get('beta')) or yf.get('beta')
    w52h      = resolve(gm(m_fh,'52WeekHigh'), av.get('week52_high')) or yf.get('week52_high')
    w52l      = resolve(gm(m_fh,'52WeekLow'), av.get('week52_low')) or yf.get('week52_low')
    market_cap= gm(m_fh,'marketCapitalization') or av.get('market_cap') or yf.get('market_cap')

    # Computed fallbacks when all APIs unavailable
    if pe_fwd is None and eps_ttm and price and float(price)>0 and float(eps_ttm)>0:
        try:
            _fwd_eps = float(eps_ttm)*(1+min(max(float(eps_growth or 0),-50),150)/100)
            if _fwd_eps>0: pe_fwd = round(float(price)/_fwd_eps,1)
        except: pass

    if ev_ebitda is None and pe_ttm and net_margin and op_margin and market_cap:
        try:
            if float(pe_ttm)>0 and float(net_margin)>0 and float(op_margin)>0:
                _mc  = float(market_cap)*1e6
                _rev = _mc/float(pe_ttm)/(float(net_margin)/100)
                _ebi = _rev*float(op_margin)/100*1.3
                _ev  = _mc + _mc*(float(de) if de else 0)*0.25
                if _ebi>0: ev_ebitda = round(_ev/_ebi,1)
        except: pass

    if fcf_margin is None and fcf_raw is not None and market_cap and price and float(price)>0:
        try:
            _rps = gm(m_fh,'revenuePerShareTTM','revenuePerShareAnnual')
            if _rps:
                _rev = float(_rps)*float(market_cap)*1e6/float(price)
                if _rev>0: fcf_margin = round(float(fcf_raw)/_rev*100,1)
        except: pass
    if fcf_margin is None and fcf_raw is not None and net_margin and pe_ttm and market_cap:
        try:
            if float(pe_ttm)>0 and float(net_margin)>0:
                _rev = float(market_cap)*1e6/float(pe_ttm)/(float(net_margin)/100)
                if _rev>0: fcf_margin = round(float(fcf_raw)/_rev*100,1)
        except: pass

    if fcf_raw and not fcf_str:
        v = float(fcf_raw)
        fcf_str = f"${v/1e9:.1f}B" if abs(v)>=1e9 else f"${v/1e6:.0f}M"

    sc  = compute_score(net_margin,op_margin,roe,roa,rev_growth,de,cr,fcf_raw,sb,b,h,se,ss,tp,price)
    z   = calc_altman(m_fh, av)
    fs  = calc_piotroski(m_fh, av)
    name        = profile.get('name', ticker)
    fh_industry = profile.get('finnhubIndustry','')
    industry    = av.get('industry','') or fh_industry or 'N/A'
    sector      = av.get('sector','') or fh_industry or ''
    peers       = PEERS_MAP.get(ticker, ['SPY','QQQ','IWM','GLD'])
    hist_fin    = av.get('historical_financials',[])
    if not hist_fin and fh_fin_raw:
        hist_fin = _parse_fh_financials(fh_fin_raw)

    econ_events = []
    try:
        econ_cal = fh('calendar/economic',{'from':to_date,'to':time.strftime('%Y-%m-%d',time.gmtime(now_ts+14*24*3600))},timeout=6)
        for ev in (econ_cal.get('economicCalendar') or [])[:8]:
            if ev.get('impact') in ('high','medium'):
                econ_events.append({'event':ev.get('event',''),'date':ev.get('time','')[:10],'impact':ev.get('impact',''),'country':ev.get('country','')})
    except: econ_events = []

    upcoming_earnings = None
    try:
        earn_cal = fh('stock/earnings-calendar',{'symbol':ticker,'from':to_date,'to':time.strftime('%Y-%m-%d',time.gmtime(now_ts+90*24*3600))},timeout=6)
        if earn_cal.get('earningsCalendar'):
            upcoming_earnings = earn_cal['earningsCalendar'][0].get('date')
    except: pass
    if not upcoming_earnings:
        upcoming_earnings = yf.get('upcoming_earnings')

    pct_inst = av.get('pct_institutions') or yf.get('pct_institutions')
    pct_insi = av.get('pct_insiders') or yf.get('pct_insiders')

    user_data_for_ai = {
        'company':{
            'ticker':ticker,'name':name,'sector':sector,'industry':industry,
            'country':av.get('country',''),'employees':av.get('employees',''),
            'description':(av.get('description','') or '')[:600],
            'price':price,'change_pct':chg_pct,'market_cap_m':market_cap,
            'composite_score':sc['total'],'score_fund':sc['fundamental'],
            'score_accounting':sc['accounting'],'score_analyst':sc['analyst'],
            'altman_z':z,'altman_zone':altman_zone(z,lang),'piotroski_f':fs,
            'pe_ttm':pe_ttm,'pe_forward':pe_fwd,'pb':pb,'ev_ebitda':ev_ebitda,
            'gross_margin':gross_m,'op_margin':op_margin,'net_margin':net_margin,
            'roe':roe,'roa':roa,'roic':roic,
            'rev_growth':rev_growth,'eps_growth':eps_growth,'eps_ttm':eps_ttm,
            'fcf':fcf_str,'fcf_margin':fcf_margin,
            'de':de,'current_ratio':cr,'div_yield':div_yield,'beta':beta,
            'week52_high':w52h,'week52_low':w52l,
            'pct_institutions':pct_inst,'pct_insiders':pct_insi,
            'insider_net_change':insider_net,'insider_mspr':round(insider_mspr,2),
            'analyst_strong_buy':sb,'analyst_buy':b,'analyst_hold':h,
            'analyst_sell':se,'analyst_strong_sell':ss,
            'consensus_target':tp,'consensus_upside':upside,
            'historical_financials':hist_fin[:3],
            'upcoming_earnings':upcoming_earnings,'peers':peers,
        },
        'macro':macro,
        'recent_news':[{'headline':n['headline'],'source':n['source']} for n in news[:4]],
        'economic_calendar':econ_events[:6],
    }

    with ThreadPoolExecutor(max_workers=2) as ex:
        fa = ex.submit(call_openai, prompt_a(lang), user_data_for_ai, 2800)
        fb = ex.submit(call_openai, prompt_b(lang), user_data_for_ai, 2800)
        try: ai_a = fa.result(timeout=52)
        except: ai_a = {'_error':'timeout'}
        try: ai_b = fb.result(timeout=52)
        except: ai_b = {'_error':'timeout'}

    if ai_a.get('_error'): ai_a = _fallback_a(name, sc, fs, lang)
    if ai_b.get('_error'): ai_b = _fallback_b(lang)
    ai = {**ai_a, **ai_b}

    return {
        'ticker':ticker,'name':name,'news':news,
        'exchange':profile.get('exchange',''),'industry':industry,'sector':sector,
        'logo':profile.get('logo',''),'country':av.get('country',''),
        'employees':av.get('employees',''),'description':(av.get('description','') or '')[:400],
        'price':price,'change':change,'change_pct':chg_pct,
        'score':sc,'altman':z,'altman_zone':altman_zone(z,lang),
        'piotroski':fs,'piotroski_label':piotroski_label(fs,lang),
        'macro':macro,'historical_financials':hist_fin,
        'economic_calendar':econ_events,'upcoming_earnings':upcoming_earnings,
        'metrics':{
            'pe':pe_ttm,'pe_forward':pe_fwd,'pb':pb,'ev_ebitda':ev_ebitda,
            'net_margin':net_margin,'op_margin':op_margin,'gross_margin':gross_m,
            'fcf_margin':fcf_margin,'roe':roe,'roa':roa,'roic':roic,
            'rev_growth':rev_growth,'eps_growth':eps_growth,'eps':eps_ttm,
            'de':de,'current_ratio':cr,'quick_ratio':qr,'div_yield':div_yield,
            'fcf':fcf_str,'week52_high':w52h,'week52_low':w52l,'beta':beta,
            'market_cap_m':market_cap,
        },
        'ownership':{
            'pct_institutions':pct_inst,'pct_insiders':pct_insi,
            'insider_net_change':insider_net,'insider_mspr':round(insider_mspr,2),
        },
        'analyst':{
            'strong_buy':sb,'buy':b,'hold':h,'sell':se,'strong_sell':ss,
            'total':sb+b+h+se+ss,'target_price':tp,'upside':upside,
        },
        'earnings':[{'period':e.get('period'),'actual':e.get('actual'),'estimate':e.get('estimate'),
                     'surprise':e.get('surprisePercent')} for e in earnings[:8]],
        'ai':ai,'lang':lang,
    }

class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200); self.send_header('Access-Control-Allow-Origin','*'); self.end_headers()
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path); qs = urllib.parse.parse_qs(parsed.query)
        ticker = (qs.get('ticker',[''])[0]).upper().strip()
        lang   = (qs.get('lang',['en'])[0]).lower().strip()
        if lang not in ('en','es'): lang = 'en'
        self.send_response(200); self.send_header('Content-type','application/json')
        self.send_header('Access-Control-Allow-Origin','*'); self.end_headers()
        if not ticker:
            self.wfile.write(json.dumps({'error':'Provide ?ticker=AAPL'}).encode()); return
        try:
            self.wfile.write(json.dumps(analyse(ticker, lang)).encode())
        except Exception as e:
            self.wfile.write(json.dumps({'error':str(e)}).encode())
    def log_message(self, *a): pass
