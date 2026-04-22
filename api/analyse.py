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
def get_av_data(ticker):
    with ThreadPoolExecutor(max_workers=3) as ex:
        f_ov  = ex.submit(_av, 'OVERVIEW', {'symbol':ticker}, 10)
        f_inc = ex.submit(_av, 'INCOME_STATEMENT', {'symbol':ticker}, 12)
        f_cf  = ex.submit(_av, 'CASH_FLOW', {'symbol':ticker}, 12)
        try:    ov      = f_ov.result(timeout=11)  or {}
        except: ov      = {}
        try:    inc_rep = (f_inc.result(timeout=13) or {}).get('annualReports') or []
        except: inc_rep = []
        try:    cf_rep  = (f_cf.result(timeout=13) or {}).get('annualReports') or []
        except: cf_rep  = []
    inc_rep = inc_rep[:4]; cf_rep = cf_rep[:4]
    ev_ebitda  = _sf(ov.get('EVToEBITDA'));      pe_ttm   = _sf(ov.get('TrailingPE'))
    pe_forward = _sf(ov.get('ForwardPE'));       pb       = _sf(ov.get('PriceToBookRatio'))
    net_margin = _sfpct(ov.get('ProfitMargin')); op_margin = _sfpct(ov.get('OperatingMarginTTM'))
    roe        = _sfpct(ov.get('ReturnOnEquityTTM')); roa  = _sfpct(ov.get('ReturnOnAssetsTTM'))
    rev_growth = _sfpct(ov.get('QuarterlyRevenueGrowthYOY'))
    eps_growth = _sfpct(ov.get('QuarterlyEarningsGrowthYOY'))
    eps_ttm    = _sf(ov.get('EPS')) or _sf(ov.get('DilutedEPSTTM'))
    beta       = _sf(ov.get('Beta'))
    week52_high= _sf(ov.get('52WeekHigh')); week52_low = _sf(ov.get('52WeekLow'))
    target_price = _sf(ov.get('AnalystTargetPrice'))
    div_yield_raw = _sf(ov.get('DividendYield'))
    div_yield    = round(div_yield_raw*100, 2) if div_yield_raw else None
    rev_ttm = _sf(ov.get('RevenueTTM')); gp_ttm = _sf(ov.get('GrossProfitTTM'))
    mc_raw  = _sf(ov.get('MarketCapitalization'))
    market_cap_m = round(mc_raw/1e6) if mc_raw else None
    gross_margin = round(gp_ttm/rev_ttm*100, 1) if gp_ttm and rev_ttm else None
    pct_inst = _sfpct(ov.get('PercentInstitutions'))
    pct_insi = _sfpct(ov.get('PercentInsiders'))
    description = ov.get('Description', '') or ''
    country     = ov.get('Country', '') or ''
    sector      = ov.get('Sector', '') or ''
    industry    = ov.get('Industry', '') or ''
    employees   = ov.get('FullTimeEmployees', '') or ''
    shares_out  = _sf(ov.get('SharesOutstanding'))
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
        r = _sf(inc.get('totalRevenue')); ni = _sf(inc.get('netIncome'))
        gp = _sf(inc.get('grossProfit'))
        oi = _sf(inc.get('operatingIncome'))
        op_cf_h = _sf(cf.get('operatingCashflow')); capex_h = _sf(cf.get('capitalExpenditures'))
        fcf_h = (op_cf_h - abs(capex_h)) if (op_cf_h is not None and capex_h is not None) else None
        if r and r > 0:
            hist_fin.append({
                'year': year,
                'revenue_m': round(r/1e6),
                'net_income_m': round(ni/1e6) if ni is not None else None,
                'operating_income_m': round(oi/1e6) if oi is not None else None,
                'fcf_m': round(fcf_h/1e6) if fcf_h is not None else None,
                'gross_margin_pct': round(gp/r*100, 1) if gp else None,
                'operating_margin_pct': round(oi/r*100, 1) if oi else None,
                'net_margin_pct': round(ni/r*100, 1) if ni else None,
            })
    return {
        'ev_ebitda':ev_ebitda, 'pe_ttm':pe_ttm, 'pe_forward':pe_forward, 'pb':pb,
        'net_margin':net_margin, 'op_margin':op_margin, 'gross_margin':gross_margin,
        'roe':roe, 'roa':roa, 'rev_growth':rev_growth, 'eps_growth':eps_growth,
        'eps_ttm':eps_ttm, 'beta':beta, 'week52_high':week52_high, 'week52_low':week52_low,
        'target_price':target_price, 'div_yield':div_yield,
        'fcf_raw':fcf_raw, 'fcf_str':fcf_str, 'fcf_margin':fcf_margin,
        'market_cap':market_cap_m, 'rev_ttm':rev_ttm,
        'pct_institutions':pct_inst, 'pct_insiders':pct_insi,
        'description':description[:1200], 'country':country, 'sector':sector, 'industry':industry,
        'employees':employees, 'shares_out':shares_out,
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
    if fcf_raw is not None: acc += 3 if float(fcf_raw) > 0 else -3
    acc = max(0, min(20, acc))
    qi = 5
    qi = max(0, min(10, qi))
    return {'total': max(5, min(98, round(f+a+acc+qi))),
            'fundamental':round(f), 'accounting':round(acc), 'analyst':round(a), 'context':round(qi)}
def calc_altman(m, av):
    try:
        roa = resolve(gm(m,'roaAnnual','roaTTM'), av.get('roa')) or 0
        at = gm(m,'assetTurnoverAnnual','assetTurnoverTTM') or 0.8
        cr = gm(m,'currentRatioAnnual','currentRatioQuarterly') or 1
        de = resolve(get_de_fh(m), av.get('de')) or 1.0
        roa = roa/100 if roa > 1 else roa
        x1 = max(0,(cr-1)*0.25); x2 = max(0,roa*0.4); x3 = max(0,roa*1.3)
        x4 = min(5.0, 1/de) if de > 0 else 3.0
        return round(1.2*x1 + 1.4*x2 + 3.3*x3 + 0.6*x4 + at, 2)
    except: return None
def altman_zone(z, lang='en'):
    if z is None: return 'N/A'
    if lang == 'es':
        return 'Zona segura (Z>3)' if z > 2.99 else 'Zona gris' if z > 1.81 else 'Distress (Z<1.8)'
    return 'Safe (Z>3)' if z > 2.99 else 'Grey zone' if z > 1.81 else 'Distress (Z<1.8)'
def calc_piotroski(m, av):
    s = 0
    roa = resolve(gm(m,'roaAnnual','roaTTM'), av.get('roa')) or 0
    fcf = av.get('fcf_raw') or gm(m,'freeCashFlowAnnual','freeCashFlowTTM') or 0
    pm = resolve(gm(m,'netMarginAnnual','netMarginTTM'), av.get('net_margin')) or 0
    fcfm = av.get('fcf_margin') or 0
    gma = gm(m,'grossMarginAnnual') or 0
    gmt = resolve(gm(m,'grossMarginTTM'), av.get('gross_margin')) or 0
    ata = gm(m,'assetTurnoverAnnual') or 0; att = gm(m,'assetTurnoverTTM') or 0
    cra = gm(m,'currentRatioAnnual') or 0; crq = gm(m,'currentRatioQuarterly') or 0
    de  = resolve(get_de_fh(m), av.get('de')) or 0
    rg  = resolve(get_rev_growth_fh(m), av.get('rev_growth')) or 0
    eg  = get_eps_growth_fh(m) or 0
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
    if lang == 'es':
        return 'Calidad alta' if f>=7 else 'Calidad media' if f>=4 else 'Señales débiles'
    return 'Strong quality' if f>=7 else 'Moderate quality' if f>=4 else 'Weak signals'
def prompt_a(lang='en'):
    lang_tag = 'Write all content in natural, fluent Spanish. Keep section JSON keys in English.' if lang=='es' else 'Write all content in clear, professional English suitable for institutional finance.'
    return f"""You are a senior equity research analyst at Goldman Sachs Equity Research writing an INFORMATIONAL REPORT (not investment advice). Return ONLY valid JSON matching the schema exactly. No markdown fences, no preamble.
{lang_tag}
CRITICAL STYLE RULES:
- Every analytical sentence MUST contain at least one specific number from the input data
- Use neutral framing: "The data suggests", "From a fundamental standpoint". NEVER say "we recommend", "investors should buy/sell"
- Explain WHY each metric matters
- Use the company description to understand the business
REQUIRED JSON SCHEMA (fill every field with substantive content):
{{"executive_summary":{{"verdict":"3-6 word neutral status","verdict_sub":"1-2 sentence position with 2+ numbers","verdict_color":"green|amber|red","verdict_icon":"bull|neutral|bear|watch","text":"8-10 sentences. Business in 1 sentence, composite score context, 2 key strengths with figures, 2 key risks with figures, valuation position, stance. Target ~200-250 words."}},"business_model":{{"text":"10-12 sentences covering: revenue streams, moat type, key geographic markets, recent strategic shifts, competitive positioning. Target ~250-300 words.","revenue_segments":[{{"name":"Segment","pct":50,"description":"what it covers"}}],"geographic_exposure":[{{"region":"United States","pct":45,"note":"why this market matters"}}]}},"performance":{{"text":"8-10 sentences covering: stock YTD vs S&P 500 with figures, 1Y total return, price vs 52W extremes, revenue growth trajectory, operating margin trend, EPS growth context, catalysts in past 12 months. Target ~200-250 words."}},"financial_quality":{{"text":"12-14 sentences: gross margin level and trend, operating leverage, FCF generation, ROIC context. THEN EXPLAIN Altman Z-Score and Piotroski F-Score with exact definitions and this company's scores. Target ~300-350 words."}},"sec_filings":{{"text":"7-9 sentences on revenue recognition, management guidance, material risk factors, segment performance, insider transactions. Target ~150-200 words.","key_disclosures":["2-3 specific findings from recent filings with exact figures"]}}}}"""
def prompt_b(lang='en'):
    lang_tag = 'Write all content in natural, fluent Spanish. Keep section JSON keys in English.' if lang=='es' else 'Write all content in clear, professional English suitable for institutional finance.'
    return f"""You are a senior equity research analyst at Goldman Sachs writing an INFORMATIONAL REPORT (not investment advice). Return ONLY valid JSON. No markdown.
{lang_tag}
RULES: Every sentence includes specific numbers. Neutral tone. Explain WHY metrics matter.
SECTOR WACC BENCHMARKS: UTILITIES 5.0-6.5% | STAPLES 6.0-7.5% | HEALTHCARE 7.5-9.5% | INDUSTRIALS 7.5-9.5% | RETAIL 8.5-11.0% | BANKS ~11-13% (ROE vs CoE) | SEMIS 10.0-12.0% | SOFTWARE 9.0-12.0% | INTERNET 9.5-12.0%
REQUIRED JSON SCHEMA:
{{"macro_context":{{"text":"10-12 sentences: geographic revenue breakdown, macro dynamics affecting each region, sector-specific macro, geopolitical risks, interest rate implications. Target ~220-280 words."}},"risk_analysis":{{"text":"6-8 sentences covering fundamental, operational, competitive, regulatory, macro risks with quantified data. Target ~140-180 words.","risks":["4-6 specific risks, each with a data point"]}},"ownership":{{"text":"8-10 sentences: institutional vs insider ownership, top holders, recent insider sentiment, capital return policy, free float. Target ~160-220 words.","top_holders":[{{"name":"Holder name","stake_pct":8.5}}]}},"valuation":{{"text":"12-14 sentences: EXPLAIN each multiple (PE, EV/EBITDA, FCF Yield), EXPLAIN WACC, ROIC vs WACC, state fair value range with WACC assumption. Target ~280-340 words.","fair_value_low":100,"fair_value_high":150,"wacc_used":9.5}},"competitors":{{"text":"10-12 sentences: margin leader/laggard status with figures, growth rank, valuation premium/discount vs median, brief contextualization of top peers. Target ~220-280 words.","table":[{{"ticker":"SUBJ","name":"Full Name","pe":35.2,"ev_ebitda":31.1,"rev_growth_pct":15.0,"net_margin_pct":25.0,"is_subject":true}},{{"ticker":"P1","name":"Peer 1","pe":40.0,"ev_ebitda":25.0,"rev_growth_pct":10.0,"net_margin_pct":15.0,"is_subject":false}},{{"ticker":"P2","name":"Peer 2","pe":28.0,"ev_ebitda":18.0,"rev_growth_pct":8.0,"net_margin_pct":18.0,"is_subject":false}},{{"ticker":"P3","name":"Peer 3","pe":30.0,"ev_ebitda":22.0,"rev_growth_pct":12.0,"net_margin_pct":12.0,"is_subject":false}},{{"ticker":"P4","name":"Peer 4","pe":22.0,"ev_ebitda":15.0,"rev_growth_pct":5.0,"net_margin_pct":14.0,"is_subject":false}}]}},"scenarios":{{"text":"4 sentences framing the range, current price anchor, probability-weighted expected return.","bull":{{"label":"Bull Case","price_target":180,"upside_pct":25,"probability_pct":30,"thesis":"3-4 sentences: catalyst, revenue/margin assumption, implied multiple at target."}},"base":{{"label":"Base Case","price_target":145,"upside_pct":5,"probability_pct":50,"thesis":"3-4 sentences with central assumptions."}},"bear":{{"label":"Bear Case","price_target":90,"downside_pct":35,"probability_pct":20,"thesis":"3-4 sentences: downside catalyst, multiple compression, trigger."}}}}}}"""
def call_openai(system_prompt, user_data_str, max_tokens=2200):
    try:
        payload = json.dumps({
            'model':'gpt-4o-mini','max_tokens':max_tokens,
            'messages':[{'role':'system','content':system_prompt},{'role':'user','content':user_data_str}]
        }).encode()
        req = urllib.request.Request('https://api.openai.com/v1/chat/completions', data=payload,
            headers={'Content-Type':'application/json','Authorization':f'Bearer {OPENAI}'})
        with urllib.request.urlopen(req, timeout=55) as r:
            data = json.loads(r.read())
            text = data['choices'][0]['message']['content']
            return json.loads(text.replace('```json','').replace('```','').strip())
    except Exception as e:
        return {'_error': str(e)}
def _fallback_a(name, sc, fs, lang='en'):
    if lang == 'es':
        return {
            'executive_summary':{'verdict':f'Score {sc["total"]}/100','verdict_sub':'Síntesis AI no disponible.','verdict_color':'amber','verdict_icon':'neutral','text':f'Síntesis completa no disponible. Score compuesto {sc["total"]}/100. Revisa los datos cuantitativos en la barra lateral.'},
            'business_model':{'text':f'{name} — síntesis AI no disponible.','revenue_segments':[],'geographic_exposure':[]},
            'performance':{'text':'Síntesis AI no disponible.'},
            'financial_quality':{'text':f'Piotroski F {fs}/9. Síntesis completa no disponible.'},
            'sec_filings':{'text':'Síntesis AI no disponible.','key_disclosures':[]}
        }
    return {
        'executive_summary':{'verdict':f'Score {sc["total"]}/100','verdict_sub':'AI synthesis unavailable.','verdict_color':'amber','verdict_icon':'neutral','text':f'Full AI synthesis unavailable. Composite score {sc["total"]}/100. Review the quantitative metrics in sidebar.'},
        'business_model':{'text':f'{name} — AI synthesis unavailable. Please retry.','revenue_segments':[],'geographic_exposure':[]},
        'performance':{'text':'AI synthesis unavailable.'},
        'financial_quality':{'text':f'Piotroski F {fs}/9. Full AI synthesis unavailable.'},
        'sec_filings':{'text':'AI synthesis unavailable.','key_disclosures':[]}
    }
def _fallback_b(lang='en'):
    msg = 'Síntesis AI no disponible.' if lang=='es' else 'AI synthesis unavailable.'
    return {
        'macro_context':{'text':msg},
        'risk_analysis':{'text':msg,'risks':[]},
        'ownership':{'text':msg,'top_holders':[]},
        'valuation':{'text':msg,'fair_value_low':0,'fair_value_high':0,'wacc_used':0},
        'competitors':{'text':msg,'table':[]},
        'scenarios':{'text':msg,'bull':{'label':'Bull','price_target':0,'upside_pct':0,'probability_pct':33,'thesis':msg},'base':{'label':'Base','price_target':0,'upside_pct':0,'probability_pct':34,'thesis':msg},'bear':{'label':'Bear','price_target':0,'downside_pct':0,'probability_pct':33,'thesis':msg}}
    }
def analyse(ticker, lang='en'):
    now_ts = int(time.time())
    from_date = time.strftime('%Y-%m-%d', time.gmtime(now_ts - 30*24*3600))
    to_date   = time.strftime('%Y-%m-%d', time.gmtime(now_ts))
    with ThreadPoolExecutor(max_workers=9) as ex:
        futs = {
            'profile':ex.submit(fh,'stock/profile2',{'symbol':ticker}),
            'quote':  ex.submit(fh,'quote',{'symbol':ticker}),
            'metrics':ex.submit(fh,'stock/metric',{'symbol':ticker,'metric':'all'}),
            'recs':   ex.submit(fh,'stock/recommendation-trends',{'symbol':ticker}),
            'target': ex.submit(fh,'stock/price-target',{'symbol':ticker}),
            'earnings':ex.submit(fh,'stock/earnings',{'symbol':ticker}),
            'news':   ex.submit(fh,'company-news',{'symbol':ticker,'from':from_date,'to':to_date}),
            'insider':ex.submit(fh,'stock/insider-sentiment',{'symbol':ticker,'from':from_date,'to':to_date}),
            'macro':  ex.submit(get_macro),
        }
        res = {k:v.result() for k,v in futs.items()}
    profile = res['profile']
    if not profile.get('name'):
        raise Exception(f'Ticker "{ticker}" not found. Try AAPL, NVDA, MSFT, JPM.')
    quote    = res['quote']
    m_fh     = (res['metrics'].get('metric') or {})
    recs     = res['recs']     if isinstance(res['recs'], list) else []
    target   = res['target']   if isinstance(res['target'], dict) else {}
    earnings = res['earnings'] if isinstance(res['earnings'], list) else []
    news_raw = res['news']     if isinstance(res['news'], list) else []
    insider_raw = res['insider']
    macro    = res['macro']
    seen_urls = set(); news = []
    for a in news_raw[:30]:
        hl = (a.get('headline') or '').strip()
        url = a.get('url','')
        if not hl or url in seen_urls: continue
        if len(hl) < 15: continue
        seen_urls.add(url)
        news.append({
            'headline': hl[:220],
            'source': a.get('source','') or '',
            'url': url,
            'datetime': a.get('datetime', 0),
        })
        if len(news) >= 8: break
    insider_data = (insider_raw or {}).get('data') or []
    insider_net = sum((d.get('change', 0) or 0) for d in insider_data[-3:])
    insider_mspr = sum((d.get('mspr', 0) or 0) for d in insider_data[-3:])
    with ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(get_av_data, ticker)
        try: av = fut.result(timeout=22) or {}
        except: av = {}
    price   = quote.get('c'); change = quote.get('d'); chg_pct = quote.get('dp')
    rec_fh = recs[0] if recs else {}
    sb = rec_fh.get('strongBuy', 0) or 0; b = rec_fh.get('buy', 0) or 0
    h  = rec_fh.get('hold', 0) or 0; se = rec_fh.get('sell', 0) or 0
    ss = rec_fh.get('strongSell', 0) or 0
    tp_fh = target.get('targetMean')
    tp = tp_fh or av.get('target_price')
    upside = round((tp-price)/price*100, 1) if tp and price and price > 0 else None
    pe_ttm     = resolve(gm(m_fh,'peBasicExclExtraTTM','peAnnual'), av.get('pe_ttm'))
    pe_fwd     = av.get('pe_forward')
    pb         = resolve(gm(m_fh,'pbAnnual'), av.get('pb'))
    ev_ebitda  = resolve(gm(m_fh,'evToEbitdaAnnual','evToEbitdaTTM'), av.get('ev_ebitda'))
    net_margin = resolve(gm(m_fh,'netMarginAnnual','netMarginTTM','netProfitMarginAnnual'), av.get('net_margin'))
    op_margin  = resolve(gm(m_fh,'operatingMarginAnnual','operatingMarginTTM'), av.get('op_margin'))
    gross_m    = resolve(gm(m_fh,'grossMarginAnnual','grossMarginTTM'), av.get('gross_margin'))
    roe        = resolve(gm(m_fh,'roeAnnual','roeTTM'), av.get('roe'))
    roa        = resolve(gm(m_fh,'roaAnnual','roaTTM'), av.get('roa'))
    roic       = gm(m_fh,'roicAnnual','roiAnnual','roicTTM')
    rev_growth = resolve(get_rev_growth_fh(m_fh), av.get('rev_growth'))
    eps_growth = resolve(get_eps_growth_fh(m_fh), av.get('eps_growth'))
    eps_ttm    = resolve(gm(m_fh,'epsTTM','epsAnnual'), av.get('eps_ttm'))
    de         = resolve(get_de_fh(m_fh), av.get('de'))
    cr         = gm(m_fh,'currentRatioAnnual','currentRatioQuarterly')
    qr         = gm(m_fh,'quickRatioAnnual')
    div_yield  = resolve(gm(m_fh,'dividendYieldIndicatedAnnual','currentDividendYieldTTM'), av.get('div_yield'))
    fcf_raw    = av.get('fcf_raw') or gm(m_fh,'freeCashFlowAnnual','freeCashFlowTTM')
    fcf_str    = av.get('fcf_str')
    fcf_margin = av.get('fcf_margin')
    beta       = resolve(gm(m_fh,'beta'), av.get('beta'))
    w52h       = resolve(gm(m_fh,'52WeekHigh'), av.get('week52_high'))
    w52l       = resolve(gm(m_fh,'52WeekLow'), av.get('week52_low'))
    market_cap = gm(m_fh,'marketCapitalization') or av.get('market_cap')
    if fcf_raw and not fcf_str:
        v = float(fcf_raw)
        fcf_str = f"${v/1e9:.1f}B" if abs(v) >= 1e9 else f"${v/1e6:.0f}M"
    sc = compute_score(net_margin, op_margin, roe, roa, rev_growth, de, cr, fcf_raw, sb, b, h, se, ss, tp, price)
    z  = calc_altman(m_fh, av)
    fs = calc_piotroski(m_fh, av)
    name = profile.get('name', ticker)
    fh_industry = profile.get('finnhubIndustry','')
    av_industry = av.get('industry','')
    industry = av_industry or fh_industry or 'N/A'
    sector = av.get('sector','') or fh_industry or ''
    peers = PEERS_MAP.get(ticker, ['SPY','QQQ','IWM','GLD'])
    hist_fin = av.get('historical_financials', [])
    user_data_openai = {
        'company':{
            'ticker':ticker, 'name':name, 'sector':sector, 'industry':industry,
            'description':av.get('description','')[:600],
            'price':price, 'market_cap_m':market_cap,
            'composite_score':sc['total'],
            'pe_ttm':pe_ttm, 'pe_forward':pe_fwd, 'ev_ebitda':ev_ebitda,
            'gross_margin':gross_m, 'op_margin':op_margin, 'net_margin':net_margin,
            'roe':roe, 'roa':roa, 'roic':roic,
            'rev_growth':rev_growth, 'eps_growth':eps_growth, 'eps_ttm':eps_ttm,
            'fcf':fcf_str, 'fcf_margin':fcf_margin,
            'de':de, 'current_ratio':cr, 'div_yield':div_yield, 'beta':beta,
            'week52_high':w52h, 'week52_low':w52l,
            'analyst_strong_buy':sb, 'analyst_buy':b, 'analyst_hold':h,
            'analyst_sell':se, 'analyst_strong_sell':ss,
            'consensus_target':tp, 'consensus_upside':upside,
            'historical_financials':hist_fin[:3],
            'altman_z':z, 'piotroski_f':fs,
        },
        'macro':macro,
        'recent_news':[{'headline':n['headline'],'source':n['source']} for n in news[:4]],
    }
    user_data_str = json.dumps(user_data_openai)
    try:
        ai_a = call_openai(prompt_a(lang), user_data_str, 2000)
    except:
        ai_a = {'_error': 'timeout'}
    if ai_a.get('_error'):
        ai_a = _fallback_a(name, sc, fs, lang)
    try:
        ai_b = call_openai(prompt_b(lang), user_data_str, 2000)
    except:
        ai_b = {'_error': 'timeout'}
    if ai_b.get('_error'):
        ai_b = _fallback_b(lang)
    ai = {**ai_a, **ai_b}
    return {
        'ticker':ticker, 'name':name, 'news':news,
        'exchange':profile.get('exchange',''), 'industry':industry, 'sector':sector,
        'logo':profile.get('logo',''), 'country':av.get('country',''),
        'employees':av.get('employees',''), 'description':av.get('description','')[:400],
        'price':price, 'change':change, 'change_pct':chg_pct,
        'score':sc, 'altman':z, 'altman_zone':altman_zone(z, lang),
        'piotroski':fs, 'piotroski_label':piotroski_label(fs, lang),
        'macro':macro, 'historical_financials':hist_fin,
        'metrics':{
            'pe':pe_ttm, 'pe_forward':pe_fwd, 'pb':pb, 'ev_ebitda':ev_ebitda,
            'net_margin':net_margin, 'op_margin':op_margin, 'gross_margin':gross_m,
            'fcf_margin':fcf_margin, 'roe':roe, 'roa':roa, 'roic':roic,
            'rev_growth':rev_growth, 'eps_growth':eps_growth, 'eps':eps_ttm,
            'de':de, 'current_ratio':cr, 'quick_ratio':qr, 'div_yield':div_yield,
            'fcf':fcf_str, 'week52_high':w52h, 'week52_low':w52l, 'beta':beta,
            'market_cap_m':market_cap,
        },
        'ownership':{
            'pct_institutions':av.get('pct_institutions'),
            'pct_insiders':av.get('pct_insiders'),
            'insider_net_change':insider_net,
            'insider_mspr':round(insider_mspr, 2),
        },
        'analyst':{
            'strong_buy':sb, 'buy':b, 'hold':h, 'sell':se, 'strong_sell':ss,
            'total':sb+b+h+se+ss, 'target_price':tp, 'upside':upside,
        },
        'earnings':[{'period':e.get('period'),'actual':e.get('actual'),'estimate':e.get('estimate'),
                     'surprise':e.get('surprisePercent')} for e in earnings[:6]],
        'ai':ai, 'lang':lang,
    }
class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200); self.send_header('Access-Control-Allow-Origin','*'); self.end_headers()
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path); qs = urllib.parse.parse_qs(parsed.query)
        ticker = (qs.get('ticker',[''])[0]).upper().strip()
        lang = (qs.get('lang',['en'])[0]).lower().strip()
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
