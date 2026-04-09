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

# ── Metric helpers ─────────────────────────────────────────────────────────
def gm(m, *keys):
    for k in keys:
        v = m.get(k)
        if v is not None:
            try:
                return float(v)
            except:
                return v
    return None

def nv(m, *keys):
    v = gm(m, *keys)
    try: return float(v) if v is not None else 0.0
    except: return 0.0

def get_de(m):
    raw = gm(m,'totalDebt/totalEquityAnnual','totalDebt/totalEquityQuarterly',
              'debtToEquityAnnual','longTermDebt/equityAnnual','debtEquityAnnual')
    if raw is None: return None
    return float(raw)/100 if float(raw) > 10 else float(raw)

def get_net_margin(m):
    return gm(m,'netMarginAnnual','netMarginTTM','netProfitMarginAnnual','netProfitMarginTTM')

def get_rev_growth(m):
    v = gm(m,'revenueGrowthTTMYoy','revenueGrowthQuarterlyYoy','revenueGrowth3Y','revenueGrowth5Y')
    if v is None: return None
    v = float(v)
    return v*100 if abs(v) < 3 else v

def get_eps_growth(m):
    v = gm(m,'epsGrowthTTMYoy','epsGrowthQuarterlyYoy','epsGrowth3Y','epsGrowth5Y')
    if v is None: return None
    v = float(v)
    return v*100 if abs(v) < 3 else v

def get_ev_ebitda(m):
    return gm(m,'evToEbitdaAnnual','evToEbitdaTTM','enterpriseValueToEBITDA',
              'ev/ebitdaAnnual','evEbitdaAnnual')

def get_fcf_margin(m):
    return gm(m,'fcfMarginAnnual','fcfMarginTTM','freeCashFlowMarginTTM',
              'freeCashFlowMarginAnnual','fcfPerShareTTM')

def get_fcf(m):
    v = gm(m,'freeCashFlowAnnual','freeCashFlowTTM','cashFlowFromOperationsAnnual')
    return v

def get_fcf_str(m):
    v = get_fcf(m)
    if v is None: return None
    v = float(v)
    return f"${v/1e9:.1f}B" if abs(v)>=1e9 else f"${v/1e6:.0f}M"

def get_roic(m):
    return gm(m,'roicAnnual','roiAnnual','roiTTM','returnOnInvestedCapitalAnnual','roicTTM')

def get_quick_ratio(m):
    return gm(m,'quickRatioAnnual','quickRatioQuarterly')

def get_div_yield(m):
    return gm(m,'dividendYieldIndicatedAnnual','currentDividendYieldTTM','dividendYieldTTM')

def get_eps(m):
    return gm(m,'epsTTM','epsAnnual','epsNormalizedAnnual','epsBasicExclExtraTTM','epsExclExtraTTM')

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

# ── OpenAI ────────────────────────────────────────────────────────────────────
def call_openai(ticker,name,industry,price,m,rsi,macd,s50,s200,sb,b,h,se,ss,tp,earnings,z,fs,sc):
    pm =nv(m,'netMarginAnnual','netMarginTTM') or 0
    om =nv(m,'operatingMarginAnnual','operatingMarginTTM') or 0
    roe=nv(m,'roeAnnual','roeTTM') or 0
    roa=nv(m,'roaAnnual','roaTTM') or 0
    de =get_de(m) or 0; cr=nv(m,'currentRatioAnnual','currentRatioQuarterly') or 0
    rg =get_rev_growth(m) or 0; eg=get_eps_growth(m) or 0; beta=nv(m,'beta') or 0
    total=sb+b+h+se+ss
    upside=round((tp-price)/price*100,1) if tp and price and price>0 else None
    trend='BULLISH(SMA50>SMA200)' if s50 and s200 and s50>s200 else 'BEARISH(SMA50<SMA200)' if s50 and s200 else 'N/A'
    eq=' | '.join([f"Q:${e.get('actual','?')}vEst${e.get('estimate','?')}({(e.get('surprise') or 0):.1f}%)" for e in (earnings or [])[:4]]) or 'N/A'
    fcf=get_fcf_str(m)
    prompt=f"""Senior Goldman Sachs equity analyst. Rigorous institutional research note.
COMPANY:{name}({ticker}) | {industry} | Price:${price} | MCap:${nv(m,'marketCapitalization'):.0f}M
FUNDAMENTALS: PE={nv(m,'peBasicExclExtraTTM','peAnnual'):.1f}x PB={nv(m,'pbAnnual'):.1f}x Beta={beta:.2f} NetMgn={pm:.1f}% OpMgn={om:.1f}% GrMgn={nv(m,'grossMarginAnnual','grossMarginTTM'):.1f}% ROE={roe:.1f}% ROA={roa:.1f}% ROIC={nv(m,'roicAnnual','roiAnnual'):.1f}% RevGrowth={rg:.1f}% EPSGrowth={eg:.1f}% EPS={get_eps(m) or 'N/A'} FCF={fcf or 'N/A'}
SOLVENCY: DE={de:.2f}x CR={cr:.2f} QR={nv(m,'quickRatioAnnual','quickRatioQuarterly'):.2f} DivYield={get_div_yield(m) or 'N/A'}% AltmanZ={z or 'N/A'}({altman_zone(z)}) PiotroskiF={fs}/9
TECHNICAL: RSI={rsi or 'N/A'} MACD={macd or 'N/A'} SMA50=${s50 or 'N/A'} SMA200=${s200 or 'N/A'} {trend}
ANALYSTS({total}): SB={sb} B={b} H={h} S={se} SS={ss} Target=${tp or 'N/A'} Upside={upside or 'N/A'}%
EARNINGS:{eq}
SCORES: {sc['total']}/100 — F:{sc['fundamental']}/35 T:{sc['technical']}/25 A:{sc['analyst']}/25 Acc:{sc['accounting']}/15
RULES: Every sentence MUST contain a specific number. Decisive analyst tone. No vague language.
Return ONLY valid JSON no markdown:
{{"verdict":"decisive CFO sentence+key number","verdict_sub":"score+key signal","verdict_color":"green|amber|red","verdict_icon":"✓|◐|✕","capital":"D/E ROE ROA CR — 3 sentences exact numbers","cashflow":"margins FCF revenue growth — 3 sentences","technical":"RSI SMA MACD — 3 sentences specific","analyst_view":"counts target upside — 3 sentences","solvency":"Altman Z Piotroski F — 3 sentences","risks":"3 specific data-backed risks","credit_decision":"credit decision with ratios","plain_debt":"2 plain sentences non-finance reader","plain_profit":"2 plain sentences","plain_lend":"2 plain sentences"}}"""
    try:
        payload=json.dumps({'model':'gpt-4o-mini','max_tokens':1600,'messages':[
            {'role':'system','content':'Financial analyst. Return ONLY valid JSON no markdown.'},
            {'role':'user','content':prompt}]}).encode()
        req=urllib.request.Request('https://api.openai.com/v1/chat/completions',data=payload,
            headers={'Content-Type':'application/json','Authorization':f'Bearer {OPENAI}'})
        with urllib.request.urlopen(req,timeout=30) as r:
            data=json.loads(r.read()); text=data['choices'][0]['message']['content']
            return json.loads(text.replace('```json','').replace('```','').strip())
    except:
        return fallback(name,pm,om,roe,roa,de,cr,rg,rsi,s50,s200,sb,b,h,se,ss,tp,z,fs,sc,upside,fcf)

def fallback(name,pm,om,roe,roa,de,cr,rg,rsi,s50,s200,sb,b,h,se,ss,tp,z,fs,sc,upside,fcf):
    sv=sc['total']; col='green' if sv>=70 else 'red' if sv<50 else 'amber'; icon='✓' if sv>=70 else '✕' if sv<50 else '◐'
    trend='bullish (SMA50>SMA200)' if s50 and s200 and s50>s200 else 'bearish (SMA50<SMA200)' if s50 and s200 else 'indeterminate'
    total=sb+b+h+se+ss
    return {
        'verdict':f"{name} scores {sv}/100 — net margin {pm:.1f}%, ROE {roe:.1f}%, D/E {de:.2f}x.",
        'verdict_sub':f"Composite {sv}/100 · {'strong fundamentals' if sv>=70 else 'mixed signals' if sv>=50 else 'elevated risk'}.",
        'verdict_color':col,'verdict_icon':icon,
        'capital':f"D/E of {de:.2f}x reflects {'conservative' if de<0.5 else 'moderate' if de<1.5 else 'elevated'} leverage. ROE {roe:.1f}% and ROA {roa:.1f}% indicate {'strong' if roe>15 else 'adequate' if roe>8 else 'weak'} capital returns. Current ratio {cr:.2f} {'supports solvency' if cr>1 else 'signals short-term pressure'}.",
        'cashflow':f"Net margin {pm:.1f}% on operating margin {om:.1f}%. Revenue growth of {rg:.1f}% {'supports' if rg>5 else 'pressures' if rg<0 else 'maintains'} cash generation. FCF of {fcf or 'N/A'} {'positive signal' if fcf and fcf[0]!= '-' else 'warrants monitoring'}.",
        'technical':f"RSI {rsi or 'N/A'} {'overbought' if rsi and rsi>70 else 'oversold' if rsi and rsi<30 else 'neutral zone'}. Trend {trend}. MACD {macd if (macd:=None) else 'N/A'} — insufficient candle data for full technical profile.",
        'analyst_view':f"{sb+b} of {total} analysts rate Buy/Strong Buy vs {se+ss} Sell. {'Target $'+str(round(tp,2))+' implies '+str(upside)+'% upside.' if upside else 'Consensus target unavailable.'} Conviction is {'high' if sb>b+h else 'mixed'}.",
        'solvency':f"Altman Z {z or 'N/A'} — {altman_zone(z)}. Piotroski F {fs}/9 — {piotroski_label(fs)}. Current ratio {cr:.2f} {'above 1.0' if cr>1 else 'below 1.0 — monitor liquidity'}.",
        'risks':f"Key risks: {'margin pressure at '+str(round(pm,1))+'% net' if pm<10 else 'revenue deceleration '+str(round(rg,1))+'%'}, {'leverage '+str(round(de,2))+'x D/E' if de>1.5 else 'sector competition'}, Beta {0:.2f} market sensitivity.",
        'credit_decision':f"{'Extend credit — metrics support debt service.' if sv>=70 else 'Maintain with quarterly covenants.' if sv>=50 else 'Reduce exposure — elevated risk.'} D/E {de:.2f}x, net margin {pm:.1f}%.",
        'plain_debt':f"{'Healthy debt' if de<1 else 'Moderate debt' if de<2 else 'High debt'} — owes ${de:.2f} for every $1 of equity. {'Very manageable.' if de<0.5 else 'Fine today but sensitive to rate changes.' if de<1.5 else 'A real risk if revenues fall.'}",
        'plain_profit':f"Keeps {pm:.1f} cents from every dollar earned. {'Excellent — well above average.' if pm>20 else 'Decent — a well-run business.' if pm>8 else 'Thin margins — little buffer.'}",
        'plain_lend':f"{'A bank would lend confidently.' if sv>=70 else 'A bank would lend with standard conditions.' if sv>=50 else 'A bank would require collateral.'} {'Strong cash flow supports repayment.' if pm>10 else 'Tight margins require monitoring.'}"
    }

# ── Main ──────────────────────────────────────────────────────────────────────
def analyse(ticker):
    now=int(time.time()); yr_ago=now-366*24*3600

    # Batch 1: fast endpoints in parallel
    with ThreadPoolExecutor(max_workers=5) as ex:
        futs={
            'profile': ex.submit(fh,'stock/profile2',{'symbol':ticker}),
            'quote':   ex.submit(fh,'quote',{'symbol':ticker}),
            'metrics': ex.submit(fh,'stock/metric',{'symbol':ticker,'metric':'all'}),
            'recs':    ex.submit(fh,'stock/recommendation-trends',{'symbol':ticker}),
            'target':  ex.submit(fh,'stock/price-target',{'symbol':ticker}),
        }
        res={k:v.result() for k,v in futs.items()}

    profile=res['profile']
    if not profile.get('name'):
        raise Exception(f'Ticker "{ticker}" not found. Try AAPL, NVDA, MSFT, JPM.')

    # Batch 2: heavier endpoints sequentially to avoid rate limiting
    time.sleep(0.3)
    candles = fh('stock/candle',{'symbol':ticker,'resolution':'D','from':yr_ago,'to':now}, timeout=15)
    time.sleep(0.2)
    earnings_raw = fh('stock/earnings',{'symbol':ticker}, timeout=10)

    quote=res['quote']; m=res['metrics'].get('metric',{})
    earnings=earnings_raw if isinstance(earnings_raw,list) else []
    recs=res['recs'] if isinstance(res['recs'],list) else []
    target=res['target'] if isinstance(res['target'],dict) else {}

    # Technical from candles
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
    ai=call_openai(ticker,name,industry,price,m,rsi,macd,s50,s200,sb,b,h,se,ss,tp,earnings,z,fs,sc)

    return {
        'ticker':ticker,'name':name,'exchange':profile.get('exchange',''),
        'industry':industry,'logo':profile.get('logo',''),
        'price':price,'change':change,'change_pct':chg_pct,
        'score':sc,'altman':z,'altman_zone':altman_zone(z),
        'piotroski':fs,'piotroski_label':piotroski_label(fs),
        'metrics':{
            'pe':         gm(m,'peBasicExclExtraTTM','peAnnual','peExclExtraAnnual'),
            'pb':         gm(m,'pbAnnual','pbQuarterly'),
            'ps':         gm(m,'psTTM','psAnnual'),
            'ev_ebitda':  get_ev_ebitda(m),
            'net_margin': get_net_margin(m),
            'op_margin':  gm(m,'operatingMarginAnnual','operatingMarginTTM'),
            'gross_margin':gm(m,'grossMarginAnnual','grossMarginTTM'),
            'fcf_margin': get_fcf_margin(m),
            'roe':        gm(m,'roeAnnual','roeTTM'),
            'roa':        gm(m,'roaAnnual','roaTTM'),
            'roic':       get_roic(m),
            'rev_growth': get_rev_growth(m),
            'eps_growth': get_eps_growth(m),
            'eps':        get_eps(m),
            'de':         get_de(m),
            'current_ratio': gm(m,'currentRatioAnnual','currentRatioQuarterly'),
            'quick_ratio':   get_quick_ratio(m),
            'div_yield':     get_div_yield(m),
            'fcf':           get_fcf_str(m),
            'week52_high':   gm(m,'52WeekHigh'),
            'week52_low':    gm(m,'52WeekLow'),
            'beta':          gm(m,'beta'),
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
