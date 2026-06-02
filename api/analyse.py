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
    'SNOW':['DDOG','PLTR','CRM','MDB'],      'DDOG':['SNOW','PLTR','SPLK','MDB'],
    'MDB':['SNOW','DDOG','ESTC','CFLT'],     'UBER':['LYFT','DASH','ABNB','BKNG'],
    'ABNB':['BKNG','EXPE','UBER','LYFT'],    'PYPL':['V','MA','SQ','AFRM'],
    'SQ':['PYPL','V','MA','AFRM'],           'SHOP':['AMZN','WMT','ETSY','BIGC'],
    'ADBE':['CRM','ORCL','NOW','MSFT'],      'NOW':['CRM','ORCL','ADBE','WDAY'],
    'WDAY':['NOW','CRM','SAP','ORCL'],       'SPOT':['NFLX','DIS','PARA','WBD'],
    'COIN':['SQ','PYPL','V','MA'],           'SCHW':['MS','GS','BLK','STT'],
    'BLK':['SCHW','MS','GS','STT'],          'PFE':['JNJ','MRK','ABBV','BMY'],
    'MRK':['JNJ','PFE','ABBV','BMY'],        'ABBV':['JNJ','PFE','MRK','BMY'],
    'AMGN':['GILD','BIIB','VRTX','REGN'],    'GILD':['AMGN','BIIB','VRTX','MRNA'],
    'MRNA':['BNTX','PFE','GILD','AMGN'],     'VRTX':['AMGN','GILD','BIIB','REGN'],
    'CAT':['DE','HON','GE','MMM'],           'DE':['CAT','CNH','HON','GE'],
    'HON':['MMM','GE','CAT','EMR'],          'GE':['HON','RTX','CAT','MMM'],
    'RTX':['LMT','NOC','GD','BA'],           'LMT':['RTX','NOC','GD','BA'],
    'BA':['LMT','RTX','NOC','GD'],           'F':['GM','TSLA','STLA','HMC'],
    'GM':['F','TSLA','STLA','HMC'],          'INTC':['NVDA','AMD','AVGO','QCOM'],
}

# ─── HTTP helpers ──────────────────────────────────────────────────────────────

def fh(path, params, timeout=10):
    params['token'] = FINNHUB
    url = 'https://finnhub.io/api/v1/' + path + '?' + urllib.parse.urlencode(params)
    try:
        req = urllib.request.Request(url, headers={'Accept':'application/json','User-Agent':'FINscope/4.0'})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except:
        return {}

def fred(series_id):
    try:
        url = f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}'
        req = urllib.request.Request(url, headers={'User-Agent':'FINscope/4.0'})
        with urllib.request.urlopen(req, timeout=7) as r:
            lines = r.read().decode().strip().split('\n')
            for line in reversed(lines):
                parts = line.split(',')
                if len(parts)==2 and parts[1].strip() not in ('','.'):
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
        req = urllib.request.Request(url, headers={'User-Agent':'FINscope/4.0'})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
            if isinstance(data,dict) and ('Information' in data or 'Note' in data):
                return {}
            return data
    except:
        return {}

# ─── Scalar helpers ─────────────────────────────────────────────────────────

def _sf(v):
    if v in (None,'None','-','','N/A'): return None
    try: return float(str(v).replace(',',''))
    except: return None

def _sfpct(v):
    raw = _sf(v)
    if raw is None: return None
    return round(raw*100, 1)

def gm(m, *keys):
    for k in keys:
        v = m.get(k)
        if v is not None:
            try: return float(v)
            except: pass
    return None

def resolve(fh_val, av_val):
    for v in (fh_val, av_val):
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

# ─── Data sources ──────────────────────────────────────────────────────────────

def _parse_fh_financials(data):
    """Parse Finnhub stock/financials-reported (SEC XBRL) → hist_fin format."""
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
        r   = _find(ic,'Revenues','RevenueFromContractWithCustomerExcludingAssessedTax',
                    'SalesRevenueNet','RevenueFromContractWithCustomerIncludingAssessedTax')
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

_YF_USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15',
    'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
]

def _yf_fetch(url, ua_index=0):
    req = urllib.request.Request(url, headers={
        'User-Agent': _YF_USER_AGENTS[ua_index % len(_YF_USER_AGENTS)],
        'Accept': 'application/json',
        'Accept-Language': 'en-US,en;q=0.9',
    })
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())

def get_sec_edgar(cik):
    """
    SEC EDGAR XBRL companyconcept API — most reliable FCF source (data is official 10-K).
    Returns dict with fcf, ocf, capex, revenue (latest annual).  Requires CIK from Finnhub profile.
    """
    if not cik:
        return {}
    try:
        cik_padded = str(int(cik)).zfill(10)
    except Exception:
        return {}

    headers = {'User-Agent': 'FINscope Research alvaro2005ho@gmail.com', 'Accept': 'application/json'}
    base = f'https://data.sec.gov/api/xbrl/companyconcept/CIK{cik_padded}'

    def _fetch_concept(concept):
        url = f'{base}/us-gaap/{concept}.json'
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=8) as r:
                return json.loads(r.read())
        except Exception:
            return None

    def _latest_annual_usd(data):
        if not data: return None
        units = (data.get('units') or {}).get('USD') or []
        annuals = [x for x in units if x.get('form') == '10-K' and x.get('fp') == 'FY']
        if not annuals:
            annuals = [x for x in units if x.get('form') == '10-K']
        if not annuals:
            return None
        annuals.sort(key=lambda x: x.get('end', ''), reverse=True)
        return _sf(annuals[0].get('val'))

    # Try the 2 most common concepts only (saves ~6-8 HTTP calls vs prior 4×3=12)
    ocf_concepts = ['NetCashProvidedByUsedInOperatingActivities','NetCashProvidedByOperatingActivities']
    cpx_concepts = ['PaymentsToAcquirePropertyPlantAndEquipment','PurchaseOfPropertyPlantAndEquipment']
    rev_concepts = ['Revenues','RevenueFromContractWithCustomerExcludingAssessedTax']

    with ThreadPoolExecutor(max_workers=6) as ex:
        ocf_futs = {c: ex.submit(_fetch_concept, c) for c in ocf_concepts}
        cpx_futs = {c: ex.submit(_fetch_concept, c) for c in cpx_concepts}
        rev_futs = {c: ex.submit(_fetch_concept, c) for c in rev_concepts}

        ocf = None
        for c in ocf_concepts:
            try:
                d = ocf_futs[c].result(timeout=6)
                v = _latest_annual_usd(d)
                if v is not None: ocf = v; break
            except: continue
        capex = None
        for c in cpx_concepts:
            try:
                d = cpx_futs[c].result(timeout=6)
                v = _latest_annual_usd(d)
                if v is not None: capex = v; break
            except: continue
        revenue = None
        for c in rev_concepts:
            try:
                d = rev_futs[c].result(timeout=6)
                v = _latest_annual_usd(d)
                if v is not None: revenue = v; break
            except: continue

    fcf = (ocf - abs(capex)) if (ocf is not None and capex is not None) else None
    return {
        'fcf':     fcf,
        'ocf':     ocf,
        'capex':   capex,
        'revenue': revenue,
    }


def get_yf_data(ticker):
    """Yahoo Finance quoteSummary — no API key needed. Third data source. Retries with alt UA on failure."""
    modules = 'defaultKeyStatistics,financialData,summaryDetail,calendarEvents,cashflowStatementHistory,majorHoldersBreakdown'
    url = f'https://query1.finance.yahoo.com/v10/finance/quoteSummary/{ticker}?modules={urllib.parse.quote(modules)}'
    data = None
    for attempt in range(3):
        try:
            data = _yf_fetch(url, attempt)
            if data and (data.get('quoteSummary') or {}).get('result'):
                break
        except Exception:
            data = None
            time.sleep(0.4)
            continue
    if not data:
        return {}
    try:
        result = (data.get('quoteSummary') or {}).get('result') or []
        if not result: return {}
        obj = result[0]
        ks  = obj.get('defaultKeyStatistics') or {}
        fd  = obj.get('financialData') or {}
        sd  = obj.get('summaryDetail') or {}
        ce  = obj.get('calendarEvents') or {}
        cfh = obj.get('cashflowStatementHistory') or {}
        mhb = obj.get('majorHoldersBreakdown') or {}

        def _yf(d, *keys):
            for k in keys:
                v = d.get(k)
                if isinstance(v, dict): v = v.get('raw')
                if v is not None:
                    try: return float(v)
                    except: pass
            return None

        def _pct(v):
            if v is None: return None
            return round(v*100, 2) if abs(v) < 3 else round(v, 2)

        # ── FCF: cashflowStatementHistory first (more accurate), then financialData ──
        cf_stmts = cfh.get('cashflowStatements') or []
        fcf_yf = None
        if cf_stmts:
            cf0 = cf_stmts[0]
            fcf_yf = _yf(cf0, 'freeCashFlow')
            if fcf_yf is None:
                ocf  = _yf(cf0, 'totalCashFromOperatingActivities')
                cpx  = _yf(cf0, 'capitalExpenditures')
                if ocf is not None and cpx is not None:
                    fcf_yf = ocf - abs(cpx)
        if fcf_yf is None:
            fcf_yf = _yf(fd, 'freeCashflow')

        rev_yf   = _yf(fd, 'totalRevenue')
        fcf_m_yf = round(fcf_yf/rev_yf*100, 1) if (fcf_yf and rev_yf and rev_yf > 0) else None
        fcf_s_yf = None
        if fcf_yf is not None:
            fcf_s_yf = f"${fcf_yf/1e9:.1f}B" if abs(fcf_yf) >= 1e9 else f"${fcf_yf/1e6:.0f}M"

        # ── Ownership: majorHoldersBreakdown is more accurate than defaultKeyStatistics ──
        inst_pct = _yf(mhb, 'institutionsPercentHeld')
        insi_pct = _yf(mhb, 'insiderPercentHeld')
        if inst_pct is None: inst_pct = _yf(ks, 'heldPercentInstitutions')
        if insi_pct is None: insi_pct = _yf(ks, 'heldPercentInsiders')
        if inst_pct is not None and inst_pct < 2: inst_pct = round(inst_pct*100, 2)
        if insi_pct is not None and insi_pct < 2: insi_pct = round(insi_pct*100, 2)

        mc_yf = _yf(sd, 'marketCap')
        earn_dates = (ce.get('earnings') or {}).get('earningsDate') or []
        next_earn = None
        for ed in earn_dates:
            ts = ed.get('raw') if isinstance(ed, dict) else ed
            if ts:
                try: next_earn = time.strftime('%Y-%m-%d', time.gmtime(float(ts))); break
                except: pass

        return {
            'pe_forward':       _yf(ks, 'forwardPE'),
            'ev_ebitda':        _yf(ks, 'enterpriseToEbitda'),
            'pb':               _yf(ks, 'priceToBook'),
            'beta':             _yf(ks, 'beta'),
            'eps_fwd':          _yf(ks, 'forwardEps'),
            'peg_ratio':        _yf(ks, 'pegRatio'),
            'price_to_sales':   _yf(ks, 'priceToSalesTrailing12Months'),
            'short_pct':        _pct(_yf(ks, 'shortPercentOfFloat')),
            'enterprise_value': _yf(ks, 'enterpriseValue'),
            'pct_institutions': inst_pct,
            'pct_insiders':     insi_pct,
            'fcf_raw':          fcf_yf,
            'fcf_str':          fcf_s_yf,
            'fcf_margin':       fcf_m_yf,
            'rev_ttm':          rev_yf,
            'op_margin':        _pct(_yf(fd, 'operatingMargins')),
            'net_margin':       _pct(_yf(fd, 'profitMargins')),
            'roe':              _pct(_yf(fd, 'returnOnEquity')),
            'roa':              _pct(_yf(fd, 'returnOnAssets')),
            'rev_growth':       _pct(_yf(fd, 'revenueGrowth')),
            'eps_growth':       _pct(_yf(fd, 'earningsGrowth')),
            'gross_margin':     _pct(_yf(fd, 'grossMargins')),
            'div_yield':        _pct(_yf(sd, 'dividendYield')),
            'target_price':     _yf(fd, 'targetMeanPrice', 'targetMedianPrice'),
            'current_ratio':    _yf(fd, 'currentRatio'),
            'de':               _yf(fd, 'debtToEquity'),
            'week52_high':      _yf(sd, 'fiftyTwoWeekHigh'),
            'week52_low':       _yf(sd, 'fiftyTwoWeekLow'),
            'market_cap':       round(mc_yf/1e6) if mc_yf else None,
            'upcoming_earnings': next_earn,
        }
    except:
        return {}

def get_av_data(ticker):
    with ThreadPoolExecutor(max_workers=3) as ex:
        f_ov  = ex.submit(_av, 'OVERVIEW', {'symbol':ticker}, 10)
        f_inc = ex.submit(_av, 'INCOME_STATEMENT', {'symbol':ticker}, 12)
        f_cf  = ex.submit(_av, 'CASH_FLOW', {'symbol':ticker}, 12)
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
    div_yield  = round(div_yield_raw*100, 2) if div_yield_raw else None
    rev_ttm    = _sf(ov.get('RevenueTTM')); gp_ttm = _sf(ov.get('GrossProfitTTM'))
    mc_raw     = _sf(ov.get('MarketCapitalization'))
    market_cap_m = round(mc_raw/1e6) if mc_raw else None
    gross_margin = round(gp_ttm/rev_ttm*100, 1) if gp_ttm and rev_ttm else None
    pct_inst   = _sf(ov.get('PercentInstitutions'))
    pct_insi   = _sf(ov.get('PercentInsiders'))
    description= ov.get('Description', '') or ''
    country    = ov.get('Country', '') or ''
    sector     = ov.get('Sector', '') or ''
    industry   = ov.get('Industry', '') or ''
    employees  = ov.get('FullTimeEmployees', '') or ''
    shares_out = _sf(ov.get('SharesOutstanding'))

    cf_latest = cf_rep[0] if cf_rep else {}
    op_cf = _sf(cf_latest.get('operatingCashflow')); capex = _sf(cf_latest.get('capitalExpenditures'))
    fcf_raw = op_cf - abs(capex) if (op_cf is not None and capex is not None) else None
    fcf_str = None; fcf_margin = None
    if fcf_raw is not None:
        fcf_str = f"${fcf_raw/1e9:.1f}B" if abs(fcf_raw) >= 1e9 else f"${fcf_raw/1e6:.0f}M"
        if rev_ttm and rev_ttm > 0:
            fcf_margin = round(fcf_raw/rev_ttm*100, 1)

    hist_fin = []
    for i in range(min(4, len(inc_rep))):
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

def get_candles_and_technicals(ticker):
    """Fetch 1Y daily candles from Finnhub and compute RSI(14), SMA50, SMA200, volatility, returns table."""
    try:
        now = int(time.time())
        from_ts = now - 5 * 365 * 24 * 3600  # 5Y for the longer returns
        data = fh('stock/candle', {'symbol':ticker, 'resolution':'D', 'from':from_ts, 'to':now}, 12)
        if not isinstance(data, dict) or data.get('s') != 'ok':
            return {}
        closes = data.get('c') or []
        timestamps = data.get('t') or []
        if len(closes) < 50:
            return {}
    except: return {}

    closes = [float(c) for c in closes if c is not None]
    n = len(closes)
    latest = closes[-1]

    # RSI(14)
    def _rsi(prices, period=14):
        if len(prices) < period+1: return None
        gains, losses = [], []
        for i in range(1, period+1):
            d = prices[-period-1+i] - prices[-period-2+i] if i>0 else 0
            (gains if d>0 else losses).append(abs(d))
        avg_gain = sum(gains)/period if gains else 0
        avg_loss = sum(losses)/period if losses else 0.0001
        rs = avg_gain/avg_loss if avg_loss>0 else 100
        return round(100 - (100/(1+rs)), 1)

    rsi14 = _rsi(closes, 14)
    sma20 = round(sum(closes[-20:])/20, 2) if n>=20 else None
    sma50 = round(sum(closes[-50:])/50, 2) if n>=50 else None
    sma200 = round(sum(closes[-200:])/200, 2) if n>=200 else None

    # Cross status
    cross_status = None
    if sma50 and sma200:
        if sma50 > sma200 * 1.005: cross_status = 'golden_cross_active'
        elif sma50 < sma200 * 0.995: cross_status = 'death_cross_active'
        else: cross_status = 'neutral'

    # 30d annualised vol
    vol_30d = None
    if n >= 31:
        try:
            import math as _m
            rets = [closes[i]/closes[i-1]-1 for i in range(n-30, n)]
            mean = sum(rets)/len(rets)
            var = sum((r-mean)**2 for r in rets)/len(rets)
            vol_30d = round((var**0.5) * (252**0.5) * 100, 1)
        except: pass

    # MACD (12,26 EMA)
    def _ema(prices, period):
        k = 2/(period+1)
        ema = prices[0]
        for p in prices[1:]:
            ema = p*k + ema*(1-k)
        return ema
    macd_value = None
    macd_signal_status = None
    if n >= 35:
        try:
            ema12 = _ema(closes[-50:], 12)
            ema26 = _ema(closes[-50:], 26)
            macd_value = round(ema12 - ema26, 2)
            macd_signal_status = 'bullish' if macd_value>0 else 'bearish'
        except: pass

    # Returns table vs different periods
    def _period_return(period_days):
        if n <= period_days: return None
        start = closes[-period_days-1] if period_days < n else closes[0]
        return round((latest/start - 1)*100, 2)

    ytd_ret = None
    try:
        import datetime as _dt
        if timestamps:
            year_start_ts = int(_dt.datetime(_dt.datetime.utcfromtimestamp(timestamps[-1]).year,1,1).timestamp())
            idx = next((i for i,t in enumerate(timestamps) if t >= year_start_ts), 0)
            if idx < n:
                ytd_ret = round((latest/closes[idx]-1)*100, 2)
    except: pass

    returns = {
        '1M':  _period_return(21),
        '3M':  _period_return(63),
        '6M':  _period_return(126),
        'YTD': ytd_ret,
        '1Y':  _period_return(252),
        '3Y':  _period_return(252*3),
        '5Y':  _period_return(252*5),
    }

    return {
        'rsi14': rsi14,
        'sma20': sma20, 'sma50': sma50, 'sma200': sma200,
        'cross_status': cross_status,
        'vol_30d_annualised': vol_30d,
        'macd': macd_value, 'macd_signal': macd_signal_status,
        'returns': returns,
        'latest_close': round(latest, 2),
    }


def get_sec_segments(cik):
    """SEC EDGAR — pull revenue disaggregated by segment (ProductOrService) and geography."""
    if not cik: return {}
    try: cik_padded = str(int(cik)).zfill(10)
    except: return {}
    headers = {'User-Agent':'FINscope Research alvaro2005ho@gmail.com', 'Accept':'application/json'}

    def _fetch(concept):
        url = f'https://data.sec.gov/api/xbrl/companyconcept/CIK{cik_padded}/us-gaap/{concept}.json'
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=8) as r:
                return json.loads(r.read())
        except: return None

    # Get the disaggregated revenue concept
    rev_data = (_fetch('RevenueFromContractWithCustomerExcludingAssessedTax')
                or _fetch('Revenues')
                or _fetch('SalesRevenueNet'))
    if not rev_data:
        return {}
    units = (rev_data.get('units') or {}).get('USD') or []
    # Find most recent fiscal year
    annuals = [x for x in units if x.get('form')=='10-K' and x.get('fp')=='FY']
    if not annuals: return {}
    annuals.sort(key=lambda x: x.get('end',''), reverse=True)
    latest_end = annuals[0].get('end','')[:7]  # YYYY-MM

    # All entries with same fiscal year end
    cohort = [x for x in units if x.get('end','')[:7] == latest_end]
    total_rev = max((x.get('val',0) for x in cohort), default=0)

    # Members: each "member" in disaggregation has accn/start/end/val
    segments = []
    seen = set()
    for x in cohort:
        member = x.get('member') or x.get('axis') or ''
        if not member: continue
        if member in seen: continue
        val = x.get('val', 0)
        if val and total_rev > 0 and val < total_rev:
            seen.add(member)
            # Clean member name: us-gaap:ProductMember → "Product"
            clean = member.split(':')[-1].replace('Member','').replace('SegmentMember','')
            # Heuristic to add spaces between CamelCase
            import re as _re
            clean_spaced = _re.sub(r'(?<!^)(?=[A-Z])', ' ', clean).strip()
            segments.append({'name': clean_spaced, 'value_usd': val, 'pct': round(val/total_rev*100, 1)})

    return {
        'fiscal_year_end': latest_end,
        'total_revenue_usd': total_rev,
        'segments': sorted(segments, key=lambda s: s['value_usd'], reverse=True)[:8],
    }


def get_finnhub_ownership(ticker):
    """Real top institutional holders + recent insider transactions from Finnhub."""
    out = {'top_holders': [], 'insider_transactions': [], 'esg_score': None}
    try:
        own = fh('stock/ownership', {'symbol':ticker, 'limit':10}, 8)
        if isinstance(own, dict):
            owners = own.get('ownership') or []
            for o in owners[:10]:
                out['top_holders'].append({
                    'name': o.get('name', '')[:80],
                    'share': o.get('share', 0),
                    'change': o.get('change', 0),
                    'filing_date': (o.get('filingDate', '') or '')[:10],
                    'portfolio_pct': o.get('portfolioPercent'),
                })
    except: pass
    try:
        now = int(time.time())
        from_d = time.strftime('%Y-%m-%d', time.gmtime(now - 180*24*3600))
        to_d   = time.strftime('%Y-%m-%d', time.gmtime(now))
        tx = fh('stock/insider-transactions', {'symbol':ticker, 'from':from_d, 'to':to_d}, 8)
        if isinstance(tx, dict):
            for t in (tx.get('data') or [])[:8]:
                out['insider_transactions'].append({
                    'name': t.get('name', '')[:80],
                    'share': t.get('share', 0),
                    'change': t.get('change', 0),
                    'transaction_price': t.get('transactionPrice', 0),
                    'transaction_date': (t.get('transactionDate', '') or '')[:10],
                    'transaction_code': t.get('transactionCode', ''),
                })
    except: pass
    return out


def compute_health_flags(net_margin, op_margin, gross_margin, roe, roic, de, cr, qr,
                        fcf_raw, fcf_margin, fcf_ni_ratio, rev_growth, hist_fin, lang='en'):
    """Compute 5-binary health semáforo with reasons."""
    flags = []
    def _f(name_en, name_es, ok, reason_en, reason_es):
        flags.append({
            'label': name_es if lang=='es' else name_en,
            'status': 'green' if ok else 'red',
            'reason': reason_es if lang=='es' else reason_en,
        })

    # 1) Liquidez
    _liq_ok = (cr is not None and cr >= 1.2) or (qr is not None and qr >= 1.0)
    _f('Liquidity', 'Liquidez',
       _liq_ok,
       f'Current ratio {cr}, quick ratio {qr}' if cr or qr else 'Insufficient liquidity data',
       f'Ratio de liquidez {cr}, test ácido {qr}' if cr or qr else 'Datos de liquidez insuficientes')

    # 2) Apalancamiento controlado
    _lev_ok = de is not None and de < 1.5
    _f('Leverage', 'Apalancamiento',
       _lev_ok,
       f'D/E {de:.2f} — within prudent range' if de is not None else 'D/E unknown',
       f'Deuda/Capital {de:.2f} — dentro del rango prudente' if de is not None else 'Apalancamiento desconocido')

    # 3) FCF positivo y saludable
    _fcf_ok = fcf_raw is not None and float(fcf_raw) > 0 and (fcf_margin is None or fcf_margin > 5)
    _f('FCF', 'Flujo de caja libre',
       _fcf_ok,
       f'FCF generation positive ({fcf_margin}% margin)' if fcf_margin else 'FCF positive',
       f'Generación de FCL positiva (margen {fcf_margin}%)' if fcf_margin else 'FCL positivo')

    # 4) Márgenes estables/expansivos
    _margin_ok = (net_margin is not None and net_margin > 5) and (op_margin is not None and op_margin > 8)
    _f('Margins', 'Márgenes',
       _margin_ok,
       f'Net margin {net_margin}%, op margin {op_margin}%',
       f'Margen neto {net_margin}%, operativo {op_margin}%')

    # 5) Calidad de beneficios (FCF/NI conversion)
    _eq_ok = fcf_ni_ratio is None or fcf_ni_ratio > 0.70
    _f('Earnings quality', 'Calidad de beneficios',
       _eq_ok,
       f'FCF/Net Income conversion {round(fcf_ni_ratio*100)}%' if fcf_ni_ratio else 'Conversion ratio unavailable',
       f'Conversión FCL/Beneficio Neto {round(fcf_ni_ratio*100)}%' if fcf_ni_ratio else 'Ratio de conversión no disponible')

    return flags


def compute_multi_method_valuation(eps_ttm, eps_growth, ev_ebitda, net_margin, op_margin,
                                   rev_growth, fcf_raw, de, beta, risk_free_rate,
                                   peer_comparison, market_cap, price, hist_fin, sector_wacc=None):
    """Multi-method valuation: P/E relative, EV/EBITDA relative, DCF 2-stage, consensus."""
    result = {}

    # ── 1. P/E relative valuation ──
    if eps_ttm and eps_ttm > 0:
        try:
            peer_pes = [p.get('pe') for p in (peer_comparison or []) if p.get('pe') and 0 < p['pe'] < 100]
            if peer_pes:
                median_pe = sorted(peer_pes)[len(peer_pes)//2]
                eps_fwd = float(eps_ttm) * (1 + min(max(float(eps_growth or 0), -30), 80)/100) if eps_growth else float(eps_ttm)
                result['pe_relative'] = {
                    'method':           'P/E vs peer median',
                    'peer_median_pe':   round(median_pe, 1),
                    'eps_used':         round(eps_fwd, 2),
                    'fair_value':       round(median_pe * eps_fwd, 2),
                    'note':             'Uses peer median P/E applied to forward EPS estimate',
                }
        except: pass

    # ── 2. EV/EBITDA relative valuation ──
    if market_cap and net_margin and op_margin and price:
        try:
            peer_evs = [p.get('ev_ebitda') for p in (peer_comparison or []) if p.get('ev_ebitda') and 0 < p['ev_ebitda'] < 60]
            if peer_evs:
                median_ev = sorted(peer_evs)[len(peer_evs)//2]
                # Approx EBITDA from market cap × (op_margin/net_margin) × rev_yield
                rev_est = float(market_cap)*1e6 * (float(net_margin)/100) / float(price) if price else None
                if rev_est and rev_est > 0:
                    ebitda_est = rev_est * (float(op_margin)/100) * 1.25
                    net_debt = float(market_cap)*1e6 * (float(de) if de else 0) * 0.25
                    fair_ev = median_ev * ebitda_est
                    fair_equity = fair_ev - net_debt
                    shares_est = float(market_cap)*1e6 / float(price)
                    fair_price = fair_equity / shares_est if shares_est > 0 else None
                    if fair_price and 0 < fair_price < float(price)*10:
                        result['ev_ebitda_relative'] = {
                            'method':            'EV/EBITDA vs peer median',
                            'peer_median_ev':    round(median_ev, 1),
                            'ebitda_est_m':      round(ebitda_est/1e6, 0),
                            'fair_value':        round(fair_price, 2),
                            'note':              'Capital-structure neutral; preferred for cross-border comparison',
                        }
        except: pass

    # ── 3. DCF 2-stage ──
    try:
        if fcf_raw and float(fcf_raw) > 0 and risk_free_rate and price:
            # WACC: use sector_wacc if given, otherwise CAPM
            if sector_wacc:
                wacc = sector_wacc
            else:
                erp = 5.0  # equity risk premium for US large caps
                ke  = float(risk_free_rate) + (float(beta) if beta else 1.0) * erp
                kd  = 5.0  # rough after-tax cost of debt
                de_ratio = float(de) if de else 0.5
                e_weight = 1 / (1 + de_ratio)
                d_weight = de_ratio / (1 + de_ratio)
                wacc = ke * e_weight + kd * d_weight
            # FCF growth: blend rev_growth and 5% terminal
            g_high = min(max(float(rev_growth or 8), 2), 25) if rev_growth else 8
            g_term = 3.0  # perpetual
            # 5-year projection at g_high decaying to g_term
            fcf = float(fcf_raw)
            pv_sum = 0
            shares_est = (float(market_cap)*1e6 / float(price)) if (market_cap and price) else None
            for year in range(1, 6):
                # decay growth linearly
                g_t = g_high - (g_high - g_term) * year/5
                fcf = fcf * (1 + g_t/100)
                pv = fcf / ((1 + wacc/100) ** year)
                pv_sum += pv
            # Terminal value
            tv = fcf * (1 + g_term/100) / ((wacc - g_term)/100) if wacc > g_term else None
            tv_pv = tv / ((1 + wacc/100) ** 5) if tv else 0
            enterprise_value = pv_sum + tv_pv
            net_debt = float(market_cap)*1e6 * (float(de) if de else 0) * 0.25
            equity_value = enterprise_value - net_debt
            fair_price = equity_value / shares_est if shares_est else None
            if fair_price and 0 < fair_price < float(price)*5:
                result['dcf'] = {
                    'method':           'DCF (2-stage)',
                    'wacc_used':        round(wacc, 1),
                    'terminal_growth':  g_term,
                    'high_growth':      round(g_high, 1),
                    'tv_pct_of_ev':     round(tv_pv/enterprise_value*100, 1) if enterprise_value else None,
                    'fair_value':       round(fair_price, 2),
                    'note':             '5Y explicit FCF + Gordon terminal; WACC bottom-up from CAPM',
                }
    except: pass

    return result


def get_peer_snapshot(ticker):
    """Fetch real comparison metrics for a peer — Finnhub primary + Yahoo Finance fallback for missing fields."""
    out = {'ticker':ticker, 'name':ticker}
    try:
        m_raw = fh('stock/metric', {'symbol':ticker, 'metric':'all'}, 10)
        m = (m_raw.get('metric') or {}) if isinstance(m_raw, dict) else {}
        prof = fh('stock/profile2', {'symbol':ticker}, 6)
        name = (prof.get('name') or ticker) if isinstance(prof, dict) else ticker
        out.update({
            'name':        name,
            'market_cap':  gm(m, 'marketCapitalization'),
            'pe':          gm(m, 'peBasicExclExtraTTM', 'peAnnual'),
            'ev_ebitda':   gm(m, 'evToEbitdaAnnual', 'evToEbitdaTTM'),
            'net_margin':  gm(m, 'netMarginAnnual', 'netMarginTTM'),
            'gross_margin':gm(m, 'grossMarginAnnual', 'grossMarginTTM'),
            'roe':         gm(m, 'roeAnnual', 'roeTTM'),
            'roa':         gm(m, 'roaAnnual', 'roaTTM'),
            'rev_growth':  get_rev_growth_fh(m),
            'beta':        gm(m, 'beta'),
            'div_yield':   gm(m, 'dividendYieldIndicatedAnnual', 'currentDividendYieldTTM'),
        })
    except: pass

    # Yahoo Finance fallback for any missing field
    try:
        if any(out.get(k) is None for k in ('pe','ev_ebitda','net_margin','gross_margin','roe','market_cap')):
            yf_peer = get_yf_data(ticker)
            if yf_peer:
                if out.get('pe') is None:           out['pe']           = yf_peer.get('pe_forward')
                if out.get('ev_ebitda') is None:    out['ev_ebitda']    = yf_peer.get('ev_ebitda')
                if out.get('net_margin') is None:   out['net_margin']   = yf_peer.get('net_margin')
                if out.get('gross_margin') is None: out['gross_margin'] = yf_peer.get('gross_margin')
                if out.get('roe') is None:          out['roe']          = yf_peer.get('roe')
                if out.get('rev_growth') is None:   out['rev_growth']   = yf_peer.get('rev_growth')
                if out.get('market_cap') is None:   out['market_cap']   = yf_peer.get('market_cap')
                if out.get('beta') is None:         out['beta']         = yf_peer.get('beta')
    except: pass

    return out

# ─── Scoring ─────────────────────────────────────────────────────────────────

def _t(en, es, lang):
    return es if lang=='es' else en

def compute_score(pm, om, roe, roa, roic, rg, de, cr, qr, fcf_raw, fcf_margin, fcf_ni_ratio,
                  sb, bu, hd, se, ss, tp, price, beta, vix, hy_spread, lang='en'):
    """
    Returns dict with the four pillar scores AND a breakdown of each rule that fired.
    Tighter thresholds — 40/40 fundamental requires elite quality across multiple axes.
    breakdown[pillar] = [{pts: int, reason: str}, ...]
    """
    bd = {'fundamental':[], 'accounting':[], 'analyst':[], 'context':[]}

    # ── FUNDAMENTAL (base 12, max 40) ──────────────────────────────────────────
    f = 12
    bd['fundamental'].append({'pts':12, 'reason':_t('Base score','Puntuación base', lang)})

    # Net margin (max +7)
    if pm is not None:
        if pm > 30:
            f += 7; bd['fundamental'].append({'pts':+7, 'reason':_t(f'Net margin {pm:.1f}% > 30% — elite profitability', f'Margen neto {pm:.1f}% > 30% — rentabilidad élite', lang)})
        elif pm > 20:
            f += 5; bd['fundamental'].append({'pts':+5, 'reason':_t(f'Net margin {pm:.1f}% > 20% — strong', f'Margen neto {pm:.1f}% > 20% — sólido', lang)})
        elif pm > 10:
            f += 3; bd['fundamental'].append({'pts':+3, 'reason':_t(f'Net margin {pm:.1f}% > 10%', f'Margen neto {pm:.1f}% > 10%', lang)})
        elif pm > 3:
            f += 1; bd['fundamental'].append({'pts':+1, 'reason':_t(f'Net margin {pm:.1f}% positive but thin', f'Margen neto {pm:.1f}% positivo pero ajustado', lang)})
        elif pm < 0:
            f -= 5; bd['fundamental'].append({'pts':-5, 'reason':_t(f'Net margin {pm:.1f}% negative — loss-making', f'Margen neto {pm:.1f}% negativo — pérdidas', lang)})

    # Operating margin (max +6)
    if om is not None:
        if om > 35:
            f += 6; bd['fundamental'].append({'pts':+6, 'reason':_t(f'Operating margin {om:.1f}% > 35% — best-in-class', f'Margen operativo {om:.1f}% > 35% — top sector', lang)})
        elif om > 25:
            f += 4; bd['fundamental'].append({'pts':+4, 'reason':_t(f'Operating margin {om:.1f}% > 25%', f'Margen operativo {om:.1f}% > 25%', lang)})
        elif om > 15:
            f += 2; bd['fundamental'].append({'pts':+2, 'reason':_t(f'Operating margin {om:.1f}% > 15%', f'Margen operativo {om:.1f}% > 15%', lang)})
        elif om < 0:
            f -= 4; bd['fundamental'].append({'pts':-4, 'reason':_t(f'Operating margin {om:.1f}% negative', f'Margen operativo {om:.1f}% negativo', lang)})

    # ROE (max +5) — penalised when extreme leverage drives it
    if roe is not None:
        if roe > 40 and (de is None or de < 1.5):
            f += 5; bd['fundamental'].append({'pts':+5, 'reason':_t(f'ROE {roe:.1f}% with controlled leverage', f'ROE {roe:.1f}% con apalancamiento controlado', lang)})
        elif roe > 20:
            f += 3; bd['fundamental'].append({'pts':+3, 'reason':_t(f'ROE {roe:.1f}% > 20%', f'ROE {roe:.1f}% > 20%', lang)})
        elif roe > 10:
            f += 1; bd['fundamental'].append({'pts':+1, 'reason':_t(f'ROE {roe:.1f}% above cost of equity proxy', f'ROE {roe:.1f}% por encima del coste de capital', lang)})
        elif roe < 0:
            f -= 4; bd['fundamental'].append({'pts':-4, 'reason':_t(f'ROE {roe:.1f}% negative', f'ROE {roe:.1f}% negativo', lang)})

    # ROIC (max +5) — most important capital-efficiency metric
    if roic is not None:
        if roic > 25:
            f += 5; bd['fundamental'].append({'pts':+5, 'reason':_t(f'ROIC {roic:.1f}% — strong economic profit signal', f'ROIC {roic:.1f}% — fuerte señal de beneficio económico', lang)})
        elif roic > 15:
            f += 3; bd['fundamental'].append({'pts':+3, 'reason':_t(f'ROIC {roic:.1f}% above sector WACC', f'ROIC {roic:.1f}% por encima del WACC sectorial', lang)})
        elif roic > 8:
            f += 1; bd['fundamental'].append({'pts':+1, 'reason':_t(f'ROIC {roic:.1f}% modest spread vs WACC', f'ROIC {roic:.1f}% diferencial modesto vs WACC', lang)})
        elif roic < 0:
            f -= 3; bd['fundamental'].append({'pts':-3, 'reason':_t(f'ROIC {roic:.1f}% negative — value destruction', f'ROIC {roic:.1f}% negativo — destrucción de valor', lang)})

    # Revenue growth (max +5)
    if rg is not None:
        if rg > 25:
            f += 5; bd['fundamental'].append({'pts':+5, 'reason':_t(f'Revenue growth +{rg:.1f}% — top decile', f'Crecimiento de ingresos +{rg:.1f}% — decil superior', lang)})
        elif rg > 12:
            f += 3; bd['fundamental'].append({'pts':+3, 'reason':_t(f'Revenue growth +{rg:.1f}%', f'Crecimiento de ingresos +{rg:.1f}%', lang)})
        elif rg > 3:
            f += 1; bd['fundamental'].append({'pts':+1, 'reason':_t(f'Revenue growth +{rg:.1f}% modest', f'Crecimiento de ingresos +{rg:.1f}% modesto', lang)})
        elif rg < 0:
            f -= 4; bd['fundamental'].append({'pts':-4, 'reason':_t(f'Revenue declining {rg:.1f}%', f'Ingresos en caída {rg:.1f}%', lang)})

    f = max(0, min(40, f))

    # ── ANALYST (base 12, max 30) ──────────────────────────────────────────────
    a = 12
    bd['analyst'].append({'pts':12, 'reason':_t('Base score','Puntuación base', lang)})
    total_recs = (sb or 0)+(bu or 0)+(hd or 0)+(se or 0)+(ss or 0)
    if total_recs > 0:
        buy_ratio = (sb+bu)/total_recs
        sell_ratio = (se+ss)/total_recs
        if buy_ratio > 0.75:
            a += 8; bd['analyst'].append({'pts':+8, 'reason':_t(f'{buy_ratio*100:.0f}% Buy-rated by {total_recs} analysts', f'{buy_ratio*100:.0f}% recomendaciones Compra entre {total_recs} analistas', lang)})
        elif buy_ratio > 0.55:
            a += 5; bd['analyst'].append({'pts':+5, 'reason':_t(f'Majority Buy-rated ({buy_ratio*100:.0f}%)', f'Mayoría Compra ({buy_ratio*100:.0f}%)', lang)})
        elif buy_ratio > 0.35:
            a += 2; bd['analyst'].append({'pts':+2, 'reason':_t(f'Mixed coverage ({buy_ratio*100:.0f}% Buy)', f'Cobertura mixta ({buy_ratio*100:.0f}% Compra)', lang)})
        if sell_ratio > 0.40:
            a -= 6; bd['analyst'].append({'pts':-6, 'reason':_t(f'{sell_ratio*100:.0f}% Sell-rated', f'{sell_ratio*100:.0f}% recomendaciones Venta', lang)})
        elif sell_ratio > 0.20:
            a -= 3; bd['analyst'].append({'pts':-3, 'reason':_t(f'{sell_ratio*100:.0f}% Sell-rated', f'{sell_ratio*100:.0f}% recomendaciones Venta', lang)})
    else:
        bd['analyst'].append({'pts':0, 'reason':_t('No recent analyst recommendations available', 'Sin recomendaciones de analistas recientes', lang)})

    if tp and price and price > 0:
        up = (tp-price)/price*100
        if up > 25:
            a += 6; bd['analyst'].append({'pts':+6, 'reason':_t(f'Consensus target +{up:.1f}% above price', f'Precio objetivo consenso +{up:.1f}% sobre cotización', lang)})
        elif up > 10:
            a += 3; bd['analyst'].append({'pts':+3, 'reason':_t(f'Consensus target +{up:.1f}%', f'Consenso +{up:.1f}%', lang)})
        elif up > 0:
            a += 1; bd['analyst'].append({'pts':+1, 'reason':_t(f'Consensus target marginally above price (+{up:.1f}%)', f'Precio objetivo marginalmente sobre cotización (+{up:.1f}%)', lang)})
        elif up < -10:
            a -= 5; bd['analyst'].append({'pts':-5, 'reason':_t(f'Consensus target {up:.1f}% below price — overvaluation flag', f'Consenso {up:.1f}% bajo cotización — alerta de sobrevaloración', lang)})
        elif up < 0:
            a -= 2; bd['analyst'].append({'pts':-2, 'reason':_t(f'Consensus target {up:.1f}% below price', f'Consenso {up:.1f}% bajo cotización', lang)})

    a = max(0, min(30, a))

    # ── ACCOUNTING / SOLVENCY (base 8, max 20) ─────────────────────────────────
    acc = 8
    bd['accounting'].append({'pts':8, 'reason':_t('Base score','Puntuación base', lang)})

    # Debt / Equity
    if de is not None:
        if de < 0.25:
            acc += 5; bd['accounting'].append({'pts':+5, 'reason':_t(f'D/E {de:.2f} — minimal leverage', f'Deuda/Capital {de:.2f} — apalancamiento mínimo', lang)})
        elif de < 0.75:
            acc += 3; bd['accounting'].append({'pts':+3, 'reason':_t(f'D/E {de:.2f} — conservative', f'Deuda/Capital {de:.2f} — conservador', lang)})
        elif de < 1.5:
            acc += 1; bd['accounting'].append({'pts':+1, 'reason':_t(f'D/E {de:.2f} — moderate', f'Deuda/Capital {de:.2f} — moderado', lang)})
        elif de > 3:
            acc -= 5; bd['accounting'].append({'pts':-5, 'reason':_t(f'D/E {de:.2f} — heavily leveraged', f'Deuda/Capital {de:.2f} — muy apalancado', lang)})
        elif de > 2:
            acc -= 3; bd['accounting'].append({'pts':-3, 'reason':_t(f'D/E {de:.2f} — high leverage', f'Deuda/Capital {de:.2f} — apalancamiento alto', lang)})

    # Current ratio
    if cr is not None:
        if cr > 2:
            acc += 3; bd['accounting'].append({'pts':+3, 'reason':_t(f'Current ratio {cr:.2f} — strong liquidity', f'Ratio liquidez {cr:.2f} — sólido', lang)})
        elif cr > 1.3:
            acc += 1; bd['accounting'].append({'pts':+1, 'reason':_t(f'Current ratio {cr:.2f} — adequate liquidity', f'Ratio liquidez {cr:.2f} — adecuado', lang)})
        elif 0 < cr < 1:
            acc -= 3; bd['accounting'].append({'pts':-3, 'reason':_t(f'Current ratio {cr:.2f} below 1 — short-term liquidity stress', f'Ratio liquidez {cr:.2f} < 1 — tensión de tesorería', lang)})

    # FCF generation (sign + magnitude vs revenue)
    if fcf_raw is not None:
        if float(fcf_raw) > 0 and fcf_margin and fcf_margin > 15:
            acc += 3; bd['accounting'].append({'pts':+3, 'reason':_t(f'FCF margin {fcf_margin:.1f}% — high cash generation', f'Margen FCL {fcf_margin:.1f}% — alta generación de caja', lang)})
        elif float(fcf_raw) > 0:
            acc += 2; bd['accounting'].append({'pts':+2, 'reason':_t('Positive free cash flow', 'Flujo de caja libre positivo', lang)})
        else:
            acc -= 3; bd['accounting'].append({'pts':-3, 'reason':_t('Negative free cash flow', 'Flujo de caja libre negativo', lang)})

    # FCF / Net Income conversion (earnings quality)
    if fcf_ni_ratio is not None:
        if fcf_ni_ratio > 0.95:
            acc += 1; bd['accounting'].append({'pts':+1, 'reason':_t(f'FCF/NI {fcf_ni_ratio*100:.0f}% — high earnings quality', f'FCL/Beneficio neto {fcf_ni_ratio*100:.0f}% — alta calidad de beneficios', lang)})
        elif fcf_ni_ratio < 0.50 and fcf_ni_ratio > 0:
            acc -= 2; bd['accounting'].append({'pts':-2, 'reason':_t(f'FCF/NI {fcf_ni_ratio*100:.0f}% — earnings quality concern', f'FCL/Beneficio neto {fcf_ni_ratio*100:.0f}% — alerta calidad beneficios', lang)})

    acc = max(0, min(20, acc))

    # ── CONTEXT / MACRO-ADJUSTED (base 4, max 10) ──────────────────────────────
    ctx = 4
    bd['context'].append({'pts':4, 'reason':_t('Base score','Puntuación base', lang)})

    # Beta vs market regime
    if beta is not None and vix is not None:
        if beta < 1.0 and vix > 22:
            ctx += 2; bd['context'].append({'pts':+2, 'reason':_t(f'Beta {beta:.2f} (defensive) in elevated VIX {vix:.1f}', f'Beta {beta:.2f} (defensiva) con VIX elevado {vix:.1f}', lang)})
        elif beta > 1.5 and vix > 25:
            ctx -= 2; bd['context'].append({'pts':-2, 'reason':_t(f'Beta {beta:.2f} (high) into volatile market (VIX {vix:.1f})', f'Beta {beta:.2f} (alta) en mercado volátil (VIX {vix:.1f})', lang)})
        elif beta is not None:
            ctx += 1; bd['context'].append({'pts':+1, 'reason':_t(f'Beta {beta:.2f} aligned with market regime', f'Beta {beta:.2f} alineada con régimen de mercado', lang)})

    # Credit spread regime
    if hy_spread is not None:
        if hy_spread < 350:
            ctx += 2; bd['context'].append({'pts':+2, 'reason':_t(f'HY credit spread {hy_spread}bps — risk-on environment', f'Spread HY {hy_spread}pb — entorno risk-on', lang)})
        elif hy_spread > 600:
            ctx -= 2; bd['context'].append({'pts':-2, 'reason':_t(f'HY credit spread {hy_spread}bps — credit stress', f'Spread HY {hy_spread}pb — estrés crediticio', lang)})

    # Quick ratio bonus
    if qr is not None and qr > 1.5:
        ctx += 1; bd['context'].append({'pts':+1, 'reason':_t(f'Quick ratio {qr:.2f} — solid acid-test', f'Test ácido {qr:.2f} — sólido', lang)})

    ctx = max(0, min(10, ctx))

    return {
        'total': max(5, min(98, round(f+a+acc+ctx))),
        'fundamental': round(f),
        'accounting':  round(acc),
        'analyst':     round(a),
        'context':     round(ctx),
        'breakdown':   bd,
    }

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
        return 'Zona segura (Z>3)' if z>2.99 else 'Zona gris (1.8–3)' if z>1.81 else 'Zona de riesgo (Z<1.8)'
    return 'Safe zone (Z>3)' if z>2.99 else 'Grey zone (1.8–3)' if z>1.81 else 'Distress zone (Z<1.8)'

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
        return 'Calidad alta' if f>=7 else 'Calidad media' if f>=4 else 'Señales débiles'
    return 'Strong quality' if f>=7 else 'Moderate quality' if f>=4 else 'Weak signals'

# ─── AI prompts ─────────────────────────────────────────────────────────────

def _lang_tag(lang):
    if lang=='es':
        return ('Redacta TODO el contenido en español financiero institucional, fluido y preciso, '
                'como un analista senior CFA de un buy-side en Madrid escribiendo para un comité de '
                'inversiones. Terminología obligatoria: "BPA" (no EPS), "VE/EBITDA" (no EV/EBITDA), '
                '"margen de flujo de caja libre" (no FCF margin), "valor razonable" (no fair value), '
                '"flujo de caja libre" o "FCL" (no FCF), "tasa de descuento" o "WACC" indistintamente, '
                '"deuda neta" (no net debt), "apalancamiento financiero" (no leverage), "rotación de '
                'activos" (no asset turnover), "fondo de maniobra" (no working capital), "cobertura de '
                'intereses" (no interest coverage), "ROIC" o "retorno sobre capital invertido", '
                '"economic profit" o "beneficio económico" (ROIC-WACC), "BPA estimado" (forward EPS), '
                '"per estimado" (forward P/E). Mantén las claves JSON en inglés.')
    return ('Write in clear, institutional-grade English for a sell-side / buy-side audience. '
            'Use precise CFA terminology. Avoid generic adjectives ("strong", "good") unless backed '
            'by an exact figure. Reference balance-sheet quality, working capital efficiency, '
            'interest coverage, and FCF conversion when relevant.')


def prompt_a(lang='en'):
    lt = _lang_tag(lang)
    return f"""You are the lead equity analyst at FINscope Research — an independent institutional research desk. You write for portfolio managers, CFOs and credit analysts. Output is INFORMATIONAL ONLY — never investment advice. Return ONLY valid JSON matching the schema exactly. No markdown fences, no preamble, no text outside the JSON.

{lt}

NON-NEGOTIABLE STANDARDS:
- Every analytical sentence MUST contain at least one specific figure from input (P/E, margin, growth %, $bn, ratio, year)
- NEVER say "we recommend / investors should / the stock will". Neutral framing only: "The data indicates", "Balance-sheet quality reflects", "Operating leverage of X% suggests".
- Connect ratios to underlying drivers. Don't just quote them — explain WHY: e.g. "ROE of 65% reflects high asset turnover (X.Xx) combined with strong net margin (XX%) and modest leverage (D/E X.XX); a Du Pont decomposition would attribute most of the spread above peers to operating efficiency, not financial gearing."
- Use historical_financials to extract multi-year trends with EXACT pp deltas: "Operating margin expanded from 28.4% in 2021 to 31.2% TTM, +280bps".
- Cross-reference real news headlines and economic_calendar events when material.
- MINIMUM 12 substantive sentences per text field. Verbose where it adds insight; never padding.
- Explicitly identify accounting red flags when relevant: aggressive revenue recognition, FCF/NI gap, capitalised costs, working capital ballooning, off-balance-sheet liabilities. If none, say "No material accounting concerns identified in the disclosed line items."
- Cite the specific business segments and geographies from the company description rather than generic "consumer markets".
- Anchor every valuation reference to a sector-appropriate benchmark (sector median P/E, sector ROIC) — do not float numbers in a vacuum.

REQUIRED JSON SCHEMA — only two sections, but DEEP coverage. EACH section ends with an `invalidation` array — falsifiable conditions with a metric, operator, value, and deadline. Without these, the memo is essay, not analysis.

{{"executive_summary":{{"verdict":"3-6 word neutral status (e.g. 'High-quality compounder, premium multiple', 'Cyclical recovery in motion', 'Capital-intensive turnaround', 'Asset-light cash machine')","verdict_sub":"1-2 sentences with at least 3 specific figures: composite score, key strength, key risk","verdict_color":"green|amber|red","verdict_icon":"bull|neutral|bear|watch","text":"14-18 sentences. (1) Open with the business in one factual sentence — what they sell, to whom, where. (2) Composite score positioning with the two top drivers AND the clearest gap (use the score breakdown context). (3) Three strengths backed by exact figures including at least one balance-sheet metric (e.g. 'gross margin 71.3% vs peer median 52%, ROIC 64.5% with D/E 0.05'). (4) Three risks backed by figures with at least one valuation or accounting flag (FCF/NI conversion, working capital, multiple compression risk). (5) Quote valuation position vs peers in exact % premium/discount terms — use peer_comparison data. (6) Close with a forward-looking framing tied to upcoming_earnings, a named catalyst, or a macro factor — never a directional call. Target 320-380 words.","key_takeaways":[{{"label":"≤8 words","status":"green|amber|red","reason":"≤22 words with specific figure"}}],"invalidation":[{{"trigger":"≤25 words concrete and falsifiable","metric":"name of metric","operator":"<|>|=|crosses","value":"specific numeric value or event","horizon":"P1Q|P2Q|P1Y"}}]}},"business_model":{{"text":"16-20 sentences. (1) What products / services and the underlying technology or service mechanism — 2-3 sentences. (2) Real revenue streams with their EXACT % from sec_segments input when available (otherwise from description) — name each segment as the company names it in 10-K. (3) For each top segment, one-sentence growth dynamic with YoY direction. (4) Explicit moat classification: pick from {{Network Effect, Switching Cost, Scale, IP / Patents, Brand, Regulatory, Cost Advantage, Distribution}} and quantify the evidence (e.g. 'TSMC capacity exclusivity'). (5) Customer or segment concentration with the exact figure from the description or 10-K (e.g. 'top 3 customers = 38% of revenue'). (6) Geographic exposure from sec_segments input when available — name actual countries / regions, not generic 'international'. (7) Strategic rationale for each major geography — why does that market matter (regulation, supply, demand). (8) Recent M&A, divestitures, product launches in the past 24 months with the dollar impact. (9) Historical inflection points using the full 4-year historical_financials series: revenue CAGR, margin trajectory, an explicit before-and-after framing. (10) Competitive positioning vs the named peers in peer_comparison — who's gaining share, who's losing. Target 420-520 words.","revenue_segments":[{{"name":"Segment name AS THE COMPANY NAMES IT","pct":50,"description":"what it covers and its YoY growth dynamic"}}],"geographic_exposure":[{{"region":"Region name","pct":45,"note":"strategic rationale + main risk/opportunity"}}],"moat":{{"type":"Network Effect|Switching Cost|Scale|IP/Patents|Brand|Regulatory|Cost Advantage|Distribution","strength_0_5":4,"evidence":"1-2 sentence quantified evidence"}},"invalidation":[{{"trigger":"≤25 words concrete and falsifiable on moat or segment dynamics","metric":"name","operator":"<|>|=|crosses","value":"specific","horizon":"P1Q|P2Q|P1Y"}}]}}}}"""

def prompt_b(lang='en'):
    lt = _lang_tag(lang)
    return f"""You are the lead equity analyst at FINscope Research. You write INFORMATIONAL REPORTS for portfolio managers and credit analysts (never investment advice). Return ONLY valid JSON. No markdown, no text outside the JSON. Output covers Performance (§3), Financial Quality (§4), and SEC Filings (§11).

{lt}

NON-NEGOTIABLE STANDARDS:
- Every sentence must include a specific figure from the input
- Use the technicals input (RSI, SMA50/200, returns table) for the Performance section
- Use the health_flags input to anchor the Financial Quality intro
- Use the recent_filings input to ground SEC Filings discussion
- NEVER say "we recommend"; use neutral institutional framing
- Cite specific YoY pp deltas from historical_financials

REQUIRED JSON SCHEMA. Each section ends with `invalidation` — falsifiable conditions with metric + operator + value + horizon.

{{"performance":{{"text":"14-18 sentences. (1) Open with the returns table: 1Y, 3Y, 5Y, YTD with EXACT numbers from technicals.returns. (2) Outperformance/underperformance vs S&P 500 if context allows. (3) Distance from 52W high/low with %. (4) Technical position: RSI {{rsi14}} (overbought >70, oversold <30), price vs SMA50 and SMA200, golden/death cross status from technicals.cross_status. (5) 30-day annualised volatility figure with interpretation. (6) Full revenue trajectory across all years in historical_financials with CAGR. (7) Operating margin evolution in exact pp expansion or compression — frame as 'margin walk'. (8) Net income trajectory with FCF/NI quality lens. (9) EPS growth context — call out any one-off items if visible. (10) Beta interpretation in plain language (defensive < 1.0, market = 1.0, offensive > 1.0). (11) Named catalysts in the past 12 months (earnings beats/misses, product launches, M&A). (12) Capital return: buybacks reducing share count, dividend changes, total shareholder yield. Target 360-460 words.","returns_summary":"4-6 sentence summary of the returns table emphasising the strongest period and the weakest.","invalidation":[{{"trigger":"≤25 words","metric":"name","operator":"<|>|=|crosses","value":"specific","horizon":"P1Q|P2Q|P1Y"}}]}},"financial_quality":{{"text":"18-22 sentences forming a deep balance-sheet AND income-statement audit. (1) Open by referencing the health_flags input: list the 5 flags and their status (green/red) with the underlying figure. (2) Then deep dive — gross margin level with multi-year pp trend. (3) Operating leverage computed in the input (use operating_leverage value), framed as: 'each 1pp of revenue growth translates to X pp of op income growth'. (4) FCF with absolute figure and FCF/Net Income conversion ratio (>100% = high earnings quality, <70% = potential aggressive accruals). (5) ROIC level and the ROIC-WACC spread context (positive spread = economic profit creation). (6) Net Debt / EBITDA from net_debt_ebitda input. (7) Working capital efficiency from current ratio and quick ratio. (8) Asset turnover from latest historical_financials. Then EXPLICITLY EXPLAIN Altman Z-Score: '5 factors. X1 = Working Capital / Total Assets (short-term liquidity buffer); X2 = Retained Earnings / TA (cumulative historical profitability); X3 = EBIT / TA (asset productivity); X4 = Market Cap / Total Liabilities (market-implied solvency cushion); X5 = Sales / TA (asset turnover). Z = 1.2·X1 + 1.4·X2 + 3.3·X3 + 0.6·X4 + X5. Bands: Z > 2.99 safe, 1.81-2.99 grey, < 1.81 distress. Not applicable to banks or asset-light tech firms.' This company's Z is X.XX → interpret. Then EXPLAIN Piotroski F-Score: '9 binary signals across Profitability (ROA+, FCF+, ROA rising YoY, FCF > NI), Leverage (D/E falling YoY, Current Ratio rising, no dilution), Efficiency (Gross Margin rising, Asset Turnover rising). 7-9 = improving; 4-6 = moderate; 0-3 = deteriorating.' This company is X/9 → interpret which sub-pillar drives it. Identify any accounting red flags (FCF/NI gap, capitalised costs, working capital ballooning, stock-based compensation inflation) or explicitly state none found. Target 500-600 words.","invalidation":[{{"trigger":"≤25 words","metric":"name","operator":"<|>|=|crosses","value":"specific","horizon":"P1Q|P2Q|P1Y"}}]}},"sec_filings":{{"text":"14-16 sentences mining the recent_filings list and the company description. (1) List the most recent 10-K and 10-Q filings with their dates from recent_filings input. (2) Revenue recognition policy and any recent segment reclassifications with figures. (3) Management guidance from the most recent quarterly call with exact dollar figure. (4) Material risk factors disclosed in the 10-K — quantify each (e.g. 'customer concentration: top 5 customers = 42% of revenue'). (5) Segment MD&A highlights — what management emphasised in their commentary. (6) Related-party transactions or material legal proceedings if disclosed. (7) Recent insider transaction patterns over the last quarter (Forms 4) — net buying or selling. (8) Critical accounting estimates (impairment tests, deferred tax, stock-based compensation) that meaningfully shape reported earnings. (9) Any restatements, going-concern language, auditor changes — flag explicitly; otherwise say 'no material flags identified in the reviewed filings'. Target 300-360 words.","key_disclosures":["5-7 specific findings each anchored to a 10-K / 10-Q line item with exact figure or %"],"filing_summaries":[{{"form":"10-K|10-Q|8-K|DEF 14A","date":"YYYY-MM-DD","one_line_summary":"≤30 words describing what THIS specific filing contains and its material content"}}]}}}}"""


def prompt_c(lang='en'):
    lt = _lang_tag(lang)
    return f"""You are the lead equity analyst at FINscope Research. You write INFORMATIONAL REPORTS for portfolio managers and credit analysts (never investment advice). Return ONLY valid JSON. No markdown, no text outside the JSON. Output covers Macro Context (§5), Risk Analysis (§6), Ownership (§7), Valuation (§8), Competitors (§9) and Scenarios (§10).

{lt}

NON-NEGOTIABLE STANDARDS:
- Every sentence carries at least one specific figure from the input
- Neutral institutional tone — never "we recommend / investors should"
- For competitors.table: COPY EXACTLY the peer_comparison numbers provided. Do NOT invent or round-trip. Preserve nulls as null.
- For ownership.top_holders: USE THE NAMES AND % FROM real_top_holders input (real Form 13F data). Do not invent holders.
- For valuation: reference the EXACT fair values from valuation_methods input (P/E relative, EV/EBITDA relative, DCF). State each method's fair value and reconcile them.
- MINIMUM 12 substantive sentences per text field — verbose where it adds insight
- Use the macro and economic_calendar fields when discussing rate, currency, or geopolitical exposure
- For valuation, build the WACC bottom-up using the provided risk-free rate + sector benchmark, and explicitly show: Ke = Rf + β×ERP

SECTOR WACC BENCHMARKS (use as anchor; adjust +0.5-1.0pp if risk_free_rate >4.5%):
UTILITIES 5.0-6.5% | REITS 5.5-7.0% | STAPLES 6.0-7.5% | TELECOM 6.5-8.5% | HEALTHCARE 7.5-9.5% | INDUSTRIALS 7.5-9.5% | RETAIL 8.5-11.0% | TRAVEL 9.5-13.0% | BANKS (use ROE vs CoE ~10-13%, Z-Score invalid) | INSURANCE 8.0-10.5% | FINTECH 9.0-12.0% | ENERGY MAJORS 8.0-10.0% | ENERGY E&P 10.0-14.0% | RENEWABLES 7.5-10.0% | MATERIALS 9.0-12.0% | PHARMA 8.0-9.0% | BIOTECH 12.0-18.0% | SEMIS 10.0-12.0% | SOFTWARE 9.0-12.0% | HARDWARE 10.0-13.0% | INTERNET 9.5-12.0%

REQUIRED JSON SCHEMA (fill ALL fields, no placeholders). Each section ends with `invalidation` — falsifiable conditions.

{{"macro_context":{{"text":"13-16 sentences SPECIFIC to this company. (1) Open with company's geographic revenue breakdown (% by region) using description as anchor — never use generic 60/20/20. (2) For each major region, discuss the live macro variable that matters most: US (10Y yield at X.XX%, Fed Funds at X.XX%, CPI at X.X% YoY, ISM PMI), Europe (ECB depo rate, energy price impact, EUR/USD), China (PBoC stance, property sector, US chip sanctions), EMs (USD strength, commodity terms-of-trade). (3) Sector-specific macro: tech (capex cycle, semis cycle phase, AI demand), banks (NIM trajectory, credit-loss provisioning), energy (Brent forward curve, OPEC+), consumer (real wages, savings rate, credit card delinquencies), pharma (FDA backlog, IRA pricing impact). (4) Geopolitical risks tied to THIS company: Taiwan exposure for semis, EU AI Act for Big Tech, GLP-1 obesity drug cycle for pharma, etc. (5) Translate the 10Y yield environment into impact on this company's WACC and refinancing cost. Reference at least 2 items from the economic_calendar input. Target 320-400 words.","invalidation":[{{"trigger":"≤25 words","metric":"macro variable","operator":"<|>|=|crosses","value":"specific","horizon":"P1Q|P2Q|P1Y"}}]}},"risk_analysis":{{"text":"13-15 sentences. Cover ALL eight risk types in order, each anchored to a quantified data point: (i) Valuation risk vs sector multiple, (ii) Operational risk (execution, supply chain, key talent), (iii) Financial risk (D/E, interest coverage, refinancing wall), (iv) Regulatory risk specific to industry/region, (v) Competitive risk citing the named peers from peer_comparison, (vi) Macro risk linked to live indicators, (vii) Technology/disruption risk, (viii) Concentration risk (customer, geography, single product). Target 280-340 words.","risks":["7-9 risks, each 1-2 sentences with a quantified data point. Use distinct categories — no duplicates."],"technical_takeaway":"3-4 sentences interpreting the technicals input (RSI, SMA cross, MACD, volatility) in plain language and flagging any divergence with the fundamental story.","invalidation":[{{"trigger":"≤25 words","metric":"name","operator":"<|>|=|crosses","value":"specific","horizon":"P1Q|P2Q|P1Y"}}]}},"ownership":{{"text":"13-15 sentences. (1) EXPLAIN the principal-agent problem in one sentence with concrete framing for THIS company. (2) Institutional ownership % and what it implies: high (>70%) = price stability but herd risk on outflows; low = retail-driven volatility. (3) Reference the real top institutional holders from real_top_holders input by name with their exact stake. (4) Insider ownership level + alignment quality. (5) Insider MSPR — quantify: positive = net buying, negative = net selling. (6) Executive compensation structure (RSU/PSU mix, alignment with TSR). (7) Board independence and any recent governance friction. (8) Capital-return policy — buyback yield + dividend yield combined = total shareholder yield. (9) Free float and implied liquidity. Target 280-340 words.","top_holders":[{{"name":"Real institution name from real_top_holders input","stake_pct":8.5}}],"invalidation":[{{"trigger":"≤25 words","metric":"insider MSPR or institutional change","operator":"<|>|=","value":"specific","horizon":"P1Q|P2Q"}}]}},"valuation":{{"text":"16-18 sentences forming a CFA-level valuation walk-through. (1) EXPLAIN each multiple in one sentence: P/E TTM, P/E Forward, EV/EBITDA (capital-structure neutral), P/B, P/S, FCF Yield, PEG. (2) Quote each multiple for the company AND the sector median using peer_comparison. (3) BUILD the WACC bottom-up: Ke = Rf + β × ERP. State Rf = current 10Y yield from macro input, β = company beta, ERP = 4.5-5.5% for US large-caps; show the arithmetic. After-tax cost of debt Kd × (1-t) using ~21% US tax rate. WACC = Ke·(E/V) + Kd(1-t)·(D/V). (4) ROIC vs WACC spread. (5) DCF framework: 5-year FCF projection, terminal value at g=2.5-3.0%, discount at WACC. Terminal value typically 60-80% of EV — sensitivity severe (±1pp on g moves fair value ~15-25%). (6) State fair-value range with WACC assumption used. Reference the valuation_methods input — quote each method's fair value (P/E relative, EV/EBITDA relative, DCF) and reconcile. (7) Compare to current price → margin of safety %. Target 440-540 words.","fair_value_low":100,"fair_value_high":150,"wacc_used":9.5,"invalidation":[{{"trigger":"≤25 words","metric":"P/E or fair value driver","operator":"<|>|=","value":"specific","horizon":"P1Q|P2Q|P1Y"}}]}},"competitors":{{"text":"13-15 sentences positioning the company within its peer group using ONLY the peer_comparison data. State margin leadership rank, revenue growth rank, P/E premium/discount vs peer median, EV/EBITDA premium/discount, ROE rank — all with exact %. Then 1-2 sentences per top peer contextualising it. Conclude on whether premium is justified by quality or vulnerable to multiple compression. Target 300-360 words.","table":[{{"ticker":"SUBJ","name":"Full Name","pe":35.2,"ev_ebitda":31.1,"rev_growth_pct":15.0,"net_margin_pct":25.0,"gross_margin_pct":60.0,"roe_pct":30.0,"market_cap_m":2000000,"is_subject":true}},{{"ticker":"P1","name":"Peer 1","pe":40.0,"ev_ebitda":25.0,"rev_growth_pct":10.0,"net_margin_pct":15.0,"gross_margin_pct":50.0,"roe_pct":20.0,"market_cap_m":500000,"is_subject":false}}],"invalidation":[{{"trigger":"≤25 words","metric":"peer relative multiple","operator":"<|>|=","value":"specific","horizon":"P1Q|P2Q"}}]}},"scenarios":{{"text":"5-6 sentences framing the scenario range. State the current price as anchor. Compute the probability-weighted expected return = Σ(prob × Δ%) and quote it.","bull":{{"label":"Bull Case","price_target":180,"upside_pct":25,"probability_pct":30,"thesis":"6-8 sentences with REQUIRED structure: (1) Named catalyst with exact timeline (e.g. 'Q3 2026 earnings beat on Data Center segment'). (2) Revenue assumption with exact YoY %. (3) Operating margin assumption with exact pp. (4) Implied forward P/E or EV/EBITDA at the target. (5) What investors must observe to validate (specific metric thresholds). (6) Key risk that would invalidate THIS bull case.","assumptions":{{"revenue_growth_yoy_pct":15,"operating_margin_pct":35,"implied_pe":28,"catalyst":"named catalyst with date"}},"triggers_to_monitor":["specific data point that confirms","another data point that confirms"]}},"base":{{"label":"Base Case","price_target":145,"upside_pct":5,"probability_pct":50,"thesis":"6-8 sentences with same structure: catalyst (or absence of catalyst), revenue/margin assumptions, implied multiple, validation criteria.","assumptions":{{"revenue_growth_yoy_pct":8,"operating_margin_pct":30,"implied_pe":24,"catalyst":"steady-state with no surprises"}},"triggers_to_monitor":["specific","specific"]}},"bear":{{"label":"Bear Case","price_target":90,"downside_pct":35,"probability_pct":20,"thesis":"6-8 sentences: downside catalyst with quantified impact, multiple compression to specific figure, trigger threshold.","assumptions":{{"revenue_growth_yoy_pct":-5,"operating_margin_pct":22,"implied_pe":18,"catalyst":"named downside catalyst"}},"triggers_to_monitor":["specific","specific"]}}}}}}"""

def _repair_json(text):
    text = text.strip()
    if not text: return None
    text = text.replace('```json','').replace('```','').strip()
    try: return json.loads(text)
    except: pass
    opens=0; open_sq=0; in_str=False; escape=False
    for c in text:
        if escape: escape=False; continue
        if c=='\\': escape=True; continue
        if c=='"' and not escape: in_str=not in_str; continue
        if in_str: continue
        if c=='{': opens+=1
        elif c=='}': opens-=1
        elif c=='[': open_sq+=1
        elif c==']': open_sq-=1
    if in_str: text+='"'
    text+=']'*max(0,open_sq)
    text+='}'*max(0,opens)
    try: return json.loads(text)
    except: return None

def call_openai(system_prompt, user_data, max_tokens=5000):
    try:
        payload = json.dumps({
            'model':'gpt-4o-mini', 'max_tokens':max_tokens,
            'messages':[
                {'role':'system','content':system_prompt},
                {'role':'user','content':json.dumps(user_data)}
            ]
        }).encode()
        req = urllib.request.Request('https://api.openai.com/v1/chat/completions', data=payload,
            headers={'Content-Type':'application/json','Authorization':f'Bearer {OPENAI}'})
        with urllib.request.urlopen(req, timeout=55) as r:
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
            'executive_summary':{'verdict':f'Puntuación {sc["total"]}/100','verdict_sub':'Síntesis de IA no disponible — consulta las métricas cuantitativas del panel lateral.','verdict_color':'amber','verdict_icon':'neutral','text':f'Síntesis completa de la IA no disponible en este intento. Puntuación compuesta {sc["total"]}/100. Las métricas cuantitativas y los ratios calculados sí están disponibles en las demás secciones — reintenta el análisis en unos minutos.','key_takeaways':[]},
            'business_model':{'text':f'{name}: síntesis de IA no disponible. Consulta la descripción de la empresa y los datos cuantitativos.','revenue_segments':[],'geographic_exposure':[],'moat':{}},
        }
    return {
        'executive_summary':{'verdict':f'Score {sc["total"]}/100','verdict_sub':'AI synthesis unavailable for this run — review quantitative metrics in the sidebar.','verdict_color':'amber','verdict_icon':'neutral','text':f'Full AI synthesis unavailable for this run. Composite score {sc["total"]}/100. Quantitative metrics and computed ratios remain available in the other sections — retry the analysis in a couple of minutes.','key_takeaways':[]},
        'business_model':{'text':f'{name} AI synthesis unavailable. Refer to the company description and quantitative data below.','revenue_segments':[],'geographic_exposure':[],'moat':{}},
    }

def _fallback_b(name, fs, lang='en'):
    msg_es = 'Síntesis de IA no disponible — los datos cuantitativos siguen disponibles abajo.'
    msg_en = 'AI synthesis unavailable — quantitative data remains available below.'
    msg = msg_es if lang=='es' else msg_en
    return {
        'performance':{'text':msg,'returns_summary':''},
        'financial_quality':{'text':f'{msg} Piotroski F-Score: {fs}/9.'},
        'sec_filings':{'text':msg,'key_disclosures':[]},
    }

def _fallback_c(lang='en'):
    msg = 'Síntesis de IA no disponible.' if lang=='es' else 'AI synthesis unavailable.'
    return {
        'macro_context':{'text':msg},
        'risk_analysis':{'text':msg,'risks':[]},
        'ownership':{'text':msg,'top_holders':[]},
        'valuation':{'text':msg,'fair_value_low':0,'fair_value_high':0,'wacc_used':0},
        'competitors':{'text':msg,'table':[]},
        'scenarios':{'text':msg,
            'bull':{'label':'Bull','price_target':0,'upside_pct':0,'probability_pct':33,'thesis':msg},
            'base':{'label':'Base','price_target':0,'upside_pct':0,'probability_pct':34,'thesis':msg},
            'bear':{'label':'Bear','price_target':0,'downside_pct':0,'probability_pct':33,'thesis':msg}}
    }

# ─── Main analysis ─────────────────────────────────────────────────────────────

def analyse(ticker, lang='en'):
    now_ts    = int(time.time())
    from_date = time.strftime('%Y-%m-%d', time.gmtime(now_ts - 30*24*3600))
    to_date   = time.strftime('%Y-%m-%d', time.gmtime(now_ts))
    peers_list = PEERS_MAP.get(ticker, ['SPY','QQQ','IWM','GLD'])[:4]

    # ── Parallel fetch: 15 core + 4 peer snapshots ──
    with ThreadPoolExecutor(max_workers=24) as ex:
        futs = {
            'profile':    ex.submit(fh,'stock/profile2',{'symbol':ticker}),
            'quote':      ex.submit(fh,'quote',{'symbol':ticker}),
            'metrics':    ex.submit(fh,'stock/metric',{'symbol':ticker,'metric':'all'}),
            'recs':       ex.submit(fh,'stock/recommendation-trends',{'symbol':ticker}),
            'target':     ex.submit(fh,'stock/price-target',{'symbol':ticker}),
            'earnings':   ex.submit(fh,'stock/earnings',{'symbol':ticker}),
            'news':       ex.submit(fh,'company-news',{'symbol':ticker,'from':from_date,'to':to_date}),
            'insider':    ex.submit(fh,'stock/insider-sentiment',{'symbol':ticker,'from':from_date,'to':to_date}),
            'macro':      ex.submit(get_macro),
            'av':         ex.submit(get_av_data, ticker),
            'yf':         ex.submit(get_yf_data, ticker),
            'fh_fin':     ex.submit(fh,'stock/financials-reported',{'symbol':ticker,'freq':'annual'},14),
            'filings':    ex.submit(fh,'stock/filings',{'symbol':ticker},10),
            'technicals': ex.submit(get_candles_and_technicals, ticker),
            'spy_tech':   ex.submit(get_candles_and_technicals, 'SPY'),
            'ownership':  ex.submit(get_finnhub_ownership, ticker),
            **{f'peer_{p}': ex.submit(get_peer_snapshot, p) for p in peers_list}
        }
        res = {}
        for k, fut in futs.items():
            try:    res[k] = fut.result(timeout=25)
            except: res[k] = {}

    profile     = res.get('profile') or {}
    if not profile.get('name'):
        raise Exception(f'Ticker "{ticker}" not found. Try AAPL, NVDA, MSFT, JPM.')

    # ── SEC EDGAR pulls (uses CIK from Finnhub profile). Strict 12s ceiling so it can never timeout the whole analyse. ──
    sec_data = {}
    sec_segments = {}
    try:
        cik = profile.get('cik') or profile.get('CIK')
        if cik:
            with ThreadPoolExecutor(max_workers=2) as _ex2:
                _f1 = _ex2.submit(get_sec_edgar, cik)
                _f2 = _ex2.submit(get_sec_segments, cik)
                try: sec_data     = _f1.result(timeout=10) or {}
                except: sec_data  = {}
                try: sec_segments = _f2.result(timeout=10) or {}
                except: sec_segments = {}
    except: pass

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
    technicals  = res.get('technicals') or {}
    spy_tech    = res.get('spy_tech') or {}
    fh_own      = res.get('ownership') or {}
    filings_raw = res.get('filings') or []
    filings_raw = filings_raw if isinstance(filings_raw, list) else []

    # ── Real SEC filings: 10-K, 10-Q, 8-K with links ──
    sec_filings_list = []
    for fl in filings_raw[:12]:
        form = (fl.get('form') or '').strip()
        if form not in ('10-K', '10-Q', '8-K', '20-F', '6-K', 'DEF 14A', 'S-1'):
            continue
        sec_filings_list.append({
            'form':         form,
            'filed_date':   fl.get('filedDate', '')[:10],
            'accepted':     fl.get('acceptedDate', '')[:10],
            'period':       fl.get('reportDate', '')[:10] if fl.get('reportDate') else '',
            'url':          fl.get('reportUrl') or fl.get('filingUrl') or '',
            'accession':    fl.get('accessNumber', ''),
        })
        if len(sec_filings_list) >= 8:
            break

    # ── Real peer comparison (Finnhub data, not AI-fabricated) ──
    peer_comparison = []
    for p in peers_list:
        pd = res.get(f'peer_{p}') or {}
        if pd and any(pd.get(k) for k in ('pe','ev_ebitda','net_margin','roe')):
            peer_comparison.append(pd)

    seen_urls=set(); news=[]
    for a in news_list[:30]:
        hl=(a.get('headline') or '').strip(); url=a.get('url','')
        if not hl or url in seen_urls or len(hl)<15: continue
        seen_urls.add(url)
        news.append({'headline':hl[:220],'source':a.get('source','') or '','url':url,'datetime':a.get('datetime',0)})
        if len(news)>=8: break

    insider_data = (insider_raw or {}).get('data') or []
    insider_net  = sum((d.get('change',0) or 0) for d in insider_data[-3:])
    insider_mspr = sum((d.get('mspr',0) or 0) for d in insider_data[-3:])

    price  = quote.get('c'); change = quote.get('d'); chg_pct = quote.get('dp')
    rec_fh = recs[0] if recs else {}
    sb=rec_fh.get('strongBuy',0) or 0; b=rec_fh.get('buy',0) or 0
    h=rec_fh.get('hold',0) or 0;      se=rec_fh.get('sell',0) or 0
    ss=rec_fh.get('strongSell',0) or 0
    tp = target.get('targetMean') or av.get('target_price') or yf.get('target_price')
    upside = round((tp-price)/price*100,1) if tp and price and price>0 else None

    # ── 3-source waterfall: Finnhub → Alpha Vantage → Yahoo Finance ──
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
    peg_ratio = yf.get('peg_ratio')
    price_sales=yf.get('price_to_sales')
    short_pct = yf.get('short_pct')

    # ── Short Interest: Finnhub metric fallback if Yahoo blocked ──
    if short_pct is None:
        si_fh = gm(m_fh, 'shortInterestQuarterly', 'shortInterestAnnual')
        if si_fh is not None and si_fh > 0:
            # Finnhub returns absolute short interest; estimate % of float using shares outstanding
            _shrs = gm(m_fh, 'sharesOutstanding') or (av.get('shares_out') if av else None)
            if _shrs and _shrs > 0:
                try:
                    short_pct = round(float(si_fh)/float(_shrs)*100, 2)
                except: pass
        # Last resort: Finnhub also exposes a direct short ratio
        if short_pct is None:
            _sr = gm(m_fh, 'shortRatio', 'shortFloatPercent')
            if _sr is not None:
                short_pct = round(float(_sr), 2)

    # ── Historical financials (AV primary → Finnhub SEC fallback) ──
    hist_fin = av.get('historical_financials', [])
    if not hist_fin and fh_fin_raw:
        hist_fin = _parse_fh_financials(fh_fin_raw)

    # ── FCF fallback chain: AV → YF → hist_fin[0] → SEC EDGAR → estimation ──
    if fcf_raw is None and hist_fin:
        latest_fcf = hist_fin[0].get('fcf_m')
        if latest_fcf is not None:
            fcf_raw = latest_fcf * 1e6
            if not fcf_str:
                fcf_str = f"${latest_fcf/1000:.1f}B" if abs(latest_fcf)>=1000 else f"${latest_fcf:.0f}M"
    # SEC EDGAR fallback (most reliable when others fail — official 10-K XBRL)
    if fcf_raw is None and sec_data.get('fcf') is not None:
        fcf_raw = float(sec_data['fcf'])
        if not fcf_str:
            v = fcf_raw
            fcf_str = f"${v/1e9:.1f}B" if abs(v)>=1e9 else f"${v/1e6:.0f}M"
    # Last resort: estimate from operating income in hist_fin
    if fcf_raw is None and hist_fin and hist_fin[0].get('operating_income_m'):
        try:
            _oi = float(hist_fin[0]['operating_income_m']) * 1e6
            _rev = (hist_fin[0].get('revenue_m') or 0) * 1e6
            # Rough: FCF ≈ Op Inc × (1 - tax_rate) - CapEx; assume CapEx≈4% of revenue, tax≈21%
            _est = _oi * 0.79 - _rev * 0.04
            if _est > 0:
                fcf_raw = _est
                if not fcf_str:
                    fcf_str = f"${_est/1e9:.1f}B*" if abs(_est)>=1e9 else f"${_est/1e6:.0f}M*"
        except: pass

    # ── Mathematical fallbacks for key multiples ──
    if pe_fwd is None and eps_ttm and price and float(price)>0 and float(eps_ttm)>0:
        try:
            _fwd_eps = float(eps_ttm)*(1+min(max(float(eps_growth or 0),-50),150)/100)
            if _fwd_eps>0: pe_fwd = round(float(price)/_fwd_eps, 1)
        except: pass

    if ev_ebitda is None and pe_ttm and net_margin and op_margin and market_cap:
        try:
            if float(pe_ttm)>0 and float(net_margin)>0 and float(op_margin)>0:
                _mc  = float(market_cap)*1e6
                _rev = _mc/float(pe_ttm)/(float(net_margin)/100)
                _ebi = _rev*float(op_margin)/100*1.3
                _ev  = _mc + _mc*(float(de) if de else 0)*0.25
                if _ebi>0: ev_ebitda = round(_ev/_ebi, 1)
        except: pass

    if fcf_margin is None and fcf_raw is not None:
        # 1) SEC EDGAR revenue (most reliable)
        try:
            if sec_data.get('revenue') and sec_data['revenue'] > 0:
                fcf_margin = round(float(fcf_raw)/float(sec_data['revenue'])*100, 1)
        except: pass
        # 2) hist_fin latest revenue
        if fcf_margin is None and hist_fin and hist_fin[0].get('revenue_m'):
            try:
                _rev = float(hist_fin[0]['revenue_m'])*1e6
                if _rev > 0: fcf_margin = round(float(fcf_raw)/_rev*100, 1)
            except: pass
        # 3) revenuePerShareTTM × shares (Finnhub)
        if fcf_margin is None:
            try:
                _rps = gm(m_fh,'revenuePerShareTTM','revenuePerShareAnnual')
                if _rps and market_cap and price and float(price)>0:
                    _rev = float(_rps)*float(market_cap)*1e6/float(price)
                    if _rev>0: fcf_margin = round(float(fcf_raw)/_rev*100, 1)
            except: pass
        # 4) Math derivation from PE + net margin + market cap
        if fcf_margin is None:
            try:
                if pe_ttm and net_margin and market_cap and float(pe_ttm)>0 and float(net_margin)>0:
                    _rev = float(market_cap)*1e6/float(pe_ttm)/(float(net_margin)/100)
                    if _rev>0: fcf_margin = round(float(fcf_raw)/_rev*100, 1)
            except: pass
        # 5) Last resort: ~80% of operating margin
        if fcf_margin is None and hist_fin:
            latest_om = hist_fin[0].get('operating_margin_pct')
            if latest_om and latest_om > 0: fcf_margin = round(latest_om * 0.80, 1)

    if fcf_raw and not fcf_str:
        v = float(fcf_raw)
        fcf_str = f"${v/1e9:.1f}B" if abs(v)>=1e9 else f"${v/1e6:.0f}M"

    # ── P/S (Price / Sales) — derive from Market Cap and Revenue if Yahoo blocked ──
    if price_sales is None:
        try:
            _rev = av.get('rev_ttm') or yf.get('rev_ttm')
            if not _rev and pe_ttm and net_margin and market_cap and float(pe_ttm)>0 and float(net_margin)>0:
                _rev = float(market_cap)*1e6/float(pe_ttm)/(float(net_margin)/100)
            if not _rev and hist_fin:
                latest_rev = hist_fin[0].get('revenue_m')
                if latest_rev: _rev = float(latest_rev)*1e6
            if _rev and market_cap and float(_rev)>0:
                price_sales = round(float(market_cap)*1e6/float(_rev), 2)
        except: pass

    # ── PEG (P/E / EPS growth) — derive from existing data ──
    if peg_ratio is None and pe_ttm and eps_growth:
        try:
            _g = float(eps_growth)
            _pe = float(pe_ttm)
            if _g > 0 and _pe > 0:
                # Cap absurd values: PEG > 10 usually indicates noise
                _peg = round(_pe/_g, 2)
                if 0 < _peg < 20:
                    peg_ratio = _peg
        except: pass
    # Final PEG fallback using rev_growth as proxy when EPS growth missing
    if peg_ratio is None and pe_ttm and rev_growth and float(rev_growth) > 0:
        try:
            _peg = round(float(pe_ttm)/float(rev_growth), 2)
            if 0 < _peg < 20:
                peg_ratio = _peg
        except: pass

    # ── Advanced ratio derivations (for score input + frontend display) ──
    # FCF / Net Income conversion ratio (earnings quality indicator)
    fcf_ni_ratio = None
    try:
        if fcf_raw and net_margin and pe_ttm and price and market_cap:
            _ni_est = float(market_cap)*1e6/float(pe_ttm) if float(pe_ttm)>0 else None
            if _ni_est and _ni_est > 0:
                fcf_ni_ratio = round(float(fcf_raw)/_ni_est, 3)
        elif fcf_raw and hist_fin and hist_fin[0].get('net_income_m'):
            _ni = float(hist_fin[0]['net_income_m'])*1e6
            if _ni and _ni > 0:
                fcf_ni_ratio = round(float(fcf_raw)/_ni, 3)
    except: pass

    # Operating leverage from historical financials (last 2 years)
    op_leverage = None
    try:
        if hist_fin and len(hist_fin) >= 2:
            r0, r1 = hist_fin[0].get('revenue_m'), hist_fin[1].get('revenue_m')
            o0, o1 = hist_fin[0].get('operating_income_m'), hist_fin[1].get('operating_income_m')
            if r0 and r1 and o0 and o1 and r1 > 0 and o1 != 0:
                rev_chg = (r0-r1)/r1
                op_chg  = (o0-o1)/o1
                if abs(rev_chg) > 0.01:
                    op_leverage = round(op_chg/rev_chg, 2)
    except: pass

    # Net Debt / EBITDA proxy (uses D/E + market cap + EBITDA proxy)
    net_debt_ebitda = None
    try:
        if de is not None and market_cap and op_margin and pe_ttm:
            _equity_m = float(market_cap)
            _debt_m = _equity_m * float(de)
            _rev_m = _equity_m / float(pe_ttm) / (float(net_margin)/100) if (net_margin and float(net_margin)>0 and float(pe_ttm)>0) else None
            if _rev_m:
                _ebitda_m = _rev_m * float(op_margin)/100 * 1.25  # approx EBITDA = OpInc × 1.25
                if _ebitda_m > 0:
                    net_debt_ebitda = round(_debt_m / _ebitda_m, 2)
    except: pass

    # ── Derived scores (with full breakdown for transparency) ──
    sc = compute_score(
        net_margin, op_margin, roe, roa, roic, rev_growth, de, cr, qr,
        fcf_raw, fcf_margin, fcf_ni_ratio,
        sb, b, h, se, ss, tp, price,
        beta, macro.get('vix'), macro.get('credit_spread_hy'),
        lang
    )
    z   = calc_altman(m_fh, av)
    fs  = calc_piotroski(m_fh, av)

    # ── Financial health semáforo (5 flags) ──
    health_flags = compute_health_flags(
        net_margin, op_margin, gross_m, roe, roic, de, cr, qr,
        fcf_raw, fcf_margin, fcf_ni_ratio, rev_growth, hist_fin, lang
    )

    # ── Multi-method valuation ──
    valuation_methods = compute_multi_method_valuation(
        eps_ttm, eps_growth, ev_ebitda, net_margin, op_margin, rev_growth,
        fcf_raw, de, beta, macro.get('risk_free_rate'),
        peer_comparison, market_cap, price, hist_fin
    )
    name        = profile.get('name', ticker)
    fh_industry = profile.get('finnhubIndustry','')
    industry    = av.get('industry','') or fh_industry or 'N/A'
    sector      = av.get('sector','') or fh_industry or ''
    peers       = peers_list

    # Employees fallback: AV → Finnhub profile → blank
    employees = av.get('employees','') or profile.get('employeeTotal','') or ''

    # Source tracking dict — which source provided each visible metric (for UI badges)
    def _src(*pairs):
        """pairs are (value, source_label). Returns the first source whose value is not None."""
        for v, s in pairs:
            if v is not None: return s
        return None
    metrics_sources = {
        'pe':           _src((gm(m_fh,'peBasicExclExtraTTM','peAnnual'),'FH'), (av.get('pe_ttm'),'AV')),
        'pe_forward':   _src((av.get('pe_forward'),'AV'), (yf.get('pe_forward'),'YF')),
        'pb':           _src((gm(m_fh,'pbAnnual'),'FH'), (av.get('pb'),'AV'), (yf.get('pb'),'YF')),
        'ev_ebitda':    _src((gm(m_fh,'evToEbitdaAnnual','evToEbitdaTTM'),'FH'), (av.get('ev_ebitda'),'AV'), (yf.get('ev_ebitda'),'YF')),
        'peg':          _src((yf.get('peg_ratio'),'YF')) or ('CALC' if peg_ratio is not None else None),
        'ps':           _src((yf.get('price_to_sales'),'YF')) or ('CALC' if price_sales is not None else None),
        'net_margin':   _src((gm(m_fh,'netMarginAnnual','netMarginTTM'),'FH'), (av.get('net_margin'),'AV'), (yf.get('net_margin'),'YF')),
        'op_margin':    _src((gm(m_fh,'operatingMarginAnnual','operatingMarginTTM'),'FH'), (av.get('op_margin'),'AV'), (yf.get('op_margin'),'YF')),
        'gross_margin': _src((gm(m_fh,'grossMarginAnnual','grossMarginTTM'),'FH'), (av.get('gross_margin'),'AV'), (yf.get('gross_margin'),'YF')),
        'fcf':          _src((av.get('fcf_raw'),'AV'), (yf.get('fcf_raw'),'YF'), (sec_data.get('fcf'),'SEC')),
        'fcf_margin':   _src((av.get('fcf_margin'),'AV'), (yf.get('fcf_margin'),'YF')) or ('CALC' if fcf_margin is not None else None),
        'roe':          _src((gm(m_fh,'roeAnnual','roeTTM'),'FH'), (av.get('roe'),'AV'), (yf.get('roe'),'YF')),
        'roa':          _src((gm(m_fh,'roaAnnual','roaTTM'),'FH'), (av.get('roa'),'AV'), (yf.get('roa'),'YF')),
        'roic':         _src((gm(m_fh,'roicAnnual','roiAnnual','roicTTM'),'FH')),
        'rev_growth':   _src((get_rev_growth_fh(m_fh),'FH'), (av.get('rev_growth'),'AV'), (yf.get('rev_growth'),'YF')),
        'eps_growth':   _src((get_eps_growth_fh(m_fh),'FH'), (av.get('eps_growth'),'AV'), (yf.get('eps_growth'),'YF')),
        'eps':          _src((gm(m_fh,'epsTTM','epsAnnual'),'FH'), (av.get('eps_ttm'),'AV')),
        'de':           _src((get_de_fh(m_fh),'FH'), (av.get('de'),'AV'), (yf.get('de'),'YF')),
        'current_ratio':_src((gm(m_fh,'currentRatioAnnual','currentRatioQuarterly'),'FH'), (yf.get('current_ratio'),'YF')),
        'div_yield':    _src((gm(m_fh,'dividendYieldIndicatedAnnual','currentDividendYieldTTM'),'FH'), (av.get('div_yield'),'AV'), (yf.get('div_yield'),'YF')),
        'beta':         _src((gm(m_fh,'beta'),'FH'), (av.get('beta'),'AV'), (yf.get('beta'),'YF')),
        'market_cap':   _src((gm(m_fh,'marketCapitalization'),'FH'), (av.get('market_cap'),'AV'), (yf.get('market_cap'),'YF')),
        'short_pct':    _src((yf.get('short_pct'),'YF'), (gm(m_fh,'shortInterestQuarterly','shortInterestAnnual'),'FH')),
    }

    # ── Ownership ──
    pct_inst = av.get('pct_institutions') or yf.get('pct_institutions')
    pct_insi = av.get('pct_insiders') or yf.get('pct_insiders')

    # ── Upcoming earnings ──
    upcoming_earnings = None
    try:
        earn_cal = fh('stock/earnings-calendar',{'symbol':ticker,'from':to_date,'to':time.strftime('%Y-%m-%d',time.gmtime(now_ts+90*24*3600))},timeout=6)
        if earn_cal.get('earningsCalendar'):
            upcoming_earnings = earn_cal['earningsCalendar'][0].get('date')
    except: pass
    if not upcoming_earnings:
        upcoming_earnings = yf.get('upcoming_earnings')

    # ── Economic calendar ──
    econ_events = []
    try:
        econ_cal = fh('calendar/economic',{'from':to_date,'to':time.strftime('%Y-%m-%d',time.gmtime(now_ts+14*24*3600))},timeout=6)
        for ev in (econ_cal.get('economicCalendar') or [])[:8]:
            if ev.get('impact') in ('high','medium'):
                econ_events.append({'event':ev.get('event',''),'date':ev.get('time','')[:10],'impact':ev.get('impact',''),'country':ev.get('country','')})
    except: econ_events=[]

    # ── Build peer comparison table with subject as first row ──
    peer_table_for_ai = [{'ticker':ticker,'name':name,'pe':pe_ttm,'ev_ebitda':ev_ebitda,
        'net_margin_pct':net_margin,'gross_margin_pct':gross_m,'roe_pct':roe,
        'rev_growth_pct':rev_growth,'market_cap_m':market_cap,'is_subject':True}]
    for pd in peer_comparison:
        peer_table_for_ai.append({
            'ticker':pd['ticker'],'name':pd.get('name',pd['ticker']),
            'pe':pd.get('pe'),'ev_ebitda':pd.get('ev_ebitda'),
            'net_margin_pct':pd.get('net_margin'),'gross_margin_pct':pd.get('gross_margin'),
            'roe_pct':pd.get('roe'),'rev_growth_pct':pd.get('rev_growth'),
            'market_cap_m':pd.get('market_cap'),'is_subject':False
        })

    # ── AI input payload (rich data feed) ──
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
            'peg_ratio':peg_ratio,'price_to_sales':price_sales,
            'gross_margin':gross_m,'op_margin':op_margin,'net_margin':net_margin,
            'roe':roe,'roa':roa,'roic':roic,
            'rev_growth':rev_growth,'eps_growth':eps_growth,'eps_ttm':eps_ttm,
            'fcf':fcf_str,'fcf_margin':fcf_margin,
            'fcf_raw_bn':round(float(fcf_raw)/1e9,1) if fcf_raw else None,
            'fcf_ni_conversion':fcf_ni_ratio,
            'operating_leverage':op_leverage,
            'net_debt_ebitda':net_debt_ebitda,
            'de':de,'current_ratio':cr,'quick_ratio':qr,'div_yield':div_yield,'beta':beta,
            'short_pct':short_pct,
            'week52_high':w52h,'week52_low':w52l,
            'pct_institutions':pct_inst,'pct_insiders':pct_insi,
            'insider_net_change':insider_net,'insider_mspr':round(insider_mspr,2),
            'analyst_strong_buy':sb,'analyst_buy':b,'analyst_hold':h,
            'analyst_sell':se,'analyst_strong_sell':ss,
            'consensus_target':tp,'consensus_upside':upside,
            'historical_financials':hist_fin[:4],
            'upcoming_earnings':upcoming_earnings,'peers':peers,
        },
        'macro':macro,
        'peer_comparison':peer_table_for_ai,
        'recent_news':[{'headline':n['headline'],'source':n['source']} for n in news[:6]],
        'economic_calendar':econ_events[:6],
        'recent_filings':[{'form':f['form'],'filed_date':f['filed_date'],'period':f['period']} for f in sec_filings_list[:6]],
        'sec_segments':sec_segments,
        'technicals':technicals,
        'spy_returns':(spy_tech.get('returns') if spy_tech else {}),
        'real_top_holders':[h for h in fh_own.get('top_holders', [])[:8]],
        'recent_insider_txns':[t for t in fh_own.get('insider_transactions', [])[:6]],
        'health_flags':health_flags,
        'valuation_methods':valuation_methods,
    }

    # ── 3 parallel AI calls (5500 tokens each — more depth per section, same wall clock) ──
    with ThreadPoolExecutor(max_workers=3) as ex:
        fa = ex.submit(call_openai, prompt_a(lang), user_data_for_ai, 5500)
        fb = ex.submit(call_openai, prompt_b(lang), user_data_for_ai, 5500)
        fc = ex.submit(call_openai, prompt_c(lang), user_data_for_ai, 5500)
        try: ai_a = fa.result(timeout=55)
        except: ai_a = {'_error':'timeout'}
        try: ai_b = fb.result(timeout=55)
        except: ai_b = {'_error':'timeout'}
        try: ai_c = fc.result(timeout=55)
        except: ai_c = {'_error':'timeout'}

    if ai_a.get('_error'): ai_a = _fallback_a(name, sc, fs, lang)
    if ai_b.get('_error'): ai_b = _fallback_b(name, fs, lang)
    if ai_c.get('_error'): ai_c = _fallback_c(lang)
    ai = {**ai_a, **ai_b, **ai_c}

    # ── Competitor table: AI output backed by real data, fallback to raw peer data ──
    ai_comp_table = (ai.get('competitors') or {}).get('table') or []
    if not ai_comp_table and peer_table_for_ai:
        if 'competitors' not in ai: ai['competitors'] = {}
        ai['competitors']['table'] = peer_table_for_ai

    return {
        'ticker':ticker,'name':name,'news':news,
        'exchange':profile.get('exchange',''),'industry':industry,'sector':sector,
        'logo':profile.get('logo',''),'country':av.get('country','') or profile.get('country',''),
        'employees':employees,'description':(av.get('description','') or '')[:400],
        'price':price,'change':change,'change_pct':chg_pct,
        'score':sc,'altman':z,'altman_zone':altman_zone(z,lang),
        'piotroski':fs,'piotroski_label':piotroski_label(fs,lang),
        'macro':macro,'historical_financials':hist_fin,
        'economic_calendar':econ_events,'upcoming_earnings':upcoming_earnings,
        'sec_filings_list':sec_filings_list,
        'peer_comparison':peer_comparison,
        'metrics':{
            'pe':pe_ttm,'pe_forward':pe_fwd,'pb':pb,'ev_ebitda':ev_ebitda,
            'peg':peg_ratio,'ps':price_sales,
            'net_margin':net_margin,'op_margin':op_margin,'gross_margin':gross_m,
            'fcf_margin':fcf_margin,'roe':roe,'roa':roa,'roic':roic,
            'rev_growth':rev_growth,'eps_growth':eps_growth,'eps':eps_ttm,
            'de':de,'current_ratio':cr,'quick_ratio':qr,'div_yield':div_yield,
            'fcf':fcf_str,'week52_high':w52h,'week52_low':w52l,'beta':beta,
            'short_pct':short_pct,'market_cap_m':market_cap,
        },
        'advanced_ratios':{
            'fcf_ni_conversion': fcf_ni_ratio,
            'operating_leverage': op_leverage,
            'net_debt_ebitda':   net_debt_ebitda,
        },
        'metrics_sources':    metrics_sources,
        'health_flags':       health_flags,
        'valuation_methods':  valuation_methods,
        'technicals':         technicals,
        'spy_returns':        (spy_tech.get('returns') if spy_tech else {}),
        'sec_segments':       sec_segments,
        'real_top_holders':   fh_own.get('top_holders', []),
        'recent_insider_txns':fh_own.get('insider_transactions', []),
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

import math as _math

def _clean_for_json(obj):
    """Recursively replace NaN, Infinity, -Infinity (invalid in JSON) with None."""
    if isinstance(obj, dict):
        return {k: _clean_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean_for_json(x) for x in obj]
    if isinstance(obj, tuple):
        return tuple(_clean_for_json(x) for x in obj)
    if isinstance(obj, float):
        if _math.isnan(obj) or _math.isinf(obj):
            return None
    return obj

class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200); self.send_header('Access-Control-Allow-Origin','*'); self.end_headers()
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path); qs = urllib.parse.parse_qs(parsed.query)
        ticker = (qs.get('ticker',[''])[0]).upper().strip()
        lang   = (qs.get('lang',['en'])[0]).lower().strip()
        if lang not in ('en','es'): lang = 'en'
        # Build response BEFORE sending headers so we don't half-send on failure
        try:
            result = analyse(ticker, lang) if ticker else {'error':'Provide ?ticker=AAPL'}
            result = _clean_for_json(result)
            body = json.dumps(result, allow_nan=False, default=str).encode()
            status = 200
        except Exception as e:
            body = json.dumps({'error': str(e)[:300]}).encode()
            status = 200
        self.send_response(status)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *a): pass
