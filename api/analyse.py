from http.server import BaseHTTPRequestHandler
import json, os, urllib.parse, urllib.request, time
from concurrent.futures import ThreadPoolExecutor

FINNHUB = os.environ.get('FINNHUB_KEY', '')
OPENAI  = os.environ.get('OPENAI_KEY', '')

def fh(path, params):
    params['token'] = FINNHUB
    url = 'https://finnhub.io/api/v1/' + path + '?' + urllib.parse.urlencode(params)
    try:
        req = urllib.request.Request(url, headers={'Accept': 'application/json', 'User-Agent': 'FINscope/2.0'})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except:
        return {}

def calc_rsi(closes, p=14):
    if len(closes) < p + 1: return None
    g = l = 0
    for i in range(1, p + 1):
        d = closes[i] - closes[i - 1]
        if d >= 0: g += d
        else: l -= d
    ag, al = g / p, l / p
    for i in range(p + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        ag = (ag * (p - 1) + max(d, 0)) / p
        al = (al * (p - 1) + max(-d, 0)) / p
    if al == 0: return 100.0
    return round(100 - 100 / (1 + ag / al), 1)

def calc_ema(data, p):
    if len(data) < p: return None
    k, e = 2 / (p + 1), sum(data[:p]) / p
    for x in data[p:]: e = x * k + e * (1 - k)
    return e

def calc_macd(closes):
    if len(closes) < 35: return None
    e12 = calc_ema(closes, 12)
    e26 = calc_ema(closes, 26)
    if e12 is None or e26 is None: return None
    return round(e12 - e26, 3)

def calc_sma(closes, p):
    if len(closes) < p: return None
    return round(sum(closes[-p:]) / p, 2)

def nv(m, k, d=0.0):
    v = m.get(k)
    try: return float(v) if v is not None else d
    except: return d

def de_ratio(m):
    raw = nv(m, 'totalDebt/totalEquityAnnual') or nv(m, 'debtEquityAnnual')
    return raw / 100 if raw > 5 else raw

def rev_growth_pct(m):
    raw = nv(m, 'revenueGrowthAnnual')
    return raw * 100 if abs(raw) < 3 else raw

def compute_score(m, rsi_v, s50, s200, macd_v, sb, b, h, sells, ss, tp, price):
    pm = nv(m, 'netMarginTTM'); om = nv(m, 'operatingMarginTTM')
    roe = nv(m, 'roeTTM'); roa = nv(m, 'roaTTM')
    rg = rev_growth_pct(m); de = de_ratio(m); cr = nv(m, 'currentRatioAnnual')
    fund = 17.5
    fund += 7 if pm>25 else 5 if pm>15 else 2 if pm>8 else (-5 if pm<0 else 0)
    fund += 6 if om>30 else 4 if om>20 else 2 if om>10 else (-4 if om<0 else 0)
    fund += 6 if roe>30 else 3 if roe>15 else (-4 if roe<0 else 0)
    fund += 4 if roa>15 else 2 if roa>8 else (-2 if roa<0 else 0)
    fund += 6 if rg>20 else 3 if rg>10 else 1 if rg>0 else -4
    fund = max(0, min(35, fund))
    tech = 12.5
    if rsi_v is not None:
        tech += 6 if 40<=rsi_v<=65 else 2 if 30<=rsi_v<40 else 2 if 65<rsi_v<=75 else (-4 if rsi_v>75 else -2)
    if s50 and s200: tech += 6 if s50>s200 else -4
    if macd_v is not None: tech += 5 if macd_v>0 else -3
    tech = max(0, min(25, tech))
    anlst = 12.5
    total = sb+b+h+sells+ss
    if total > 0:
        buy_r = (sb+b)/total; sell_r = (sells+ss)/total
        anlst += 10 if buy_r>0.7 else 6 if buy_r>0.5 else 2 if buy_r>0.3 else 0
        anlst -= 8 if sell_r>0.5 else 4 if sell_r>0.3 else 0
    if tp and price and price>0:
        up = (tp-price)/price*100
        anlst += 5 if up>20 else 2 if up>10 else 1 if up>0 else (-5 if up<-10 else -2)
    anlst = max(0, min(25, anlst))
    acct = 7.5
    acct += 4 if de<0.3 else 2 if de<1 else (-4 if de>3 else -2 if de>2 else 0)
    acct += 3 if cr>2 else 1 if cr>1.2 else (-3 if 0<cr<1 else 0)
    acct = max(0, min(15, acct))
    return {'total': max(5,min(98,round(fund+tech+anlst+acct))),
            'fundamental':round(fund),'technical':round(tech),
            'analyst':round(anlst),'accounting':round(acct)}

def calc_altman(m):
    try:
        roa = nv(m,'roaTTM')/100; cr = nv(m,'currentRatioAnnual')
        de = de_ratio(m) or 1.0; at = nv(m,'assetTurnoverAnnual') or 0.8
        x1 = max(0,(cr-1)*0.25); x2 = max(0,roa*0.4); x3 = max(0,roa*1.3)
        x4 = min(5.0, 1/de) if de>0 else 3.0; x5 = at
        return round(1.2*x1+1.4*x2+3.3*x3+0.6*x4+1.0*x5, 2)
    except: return None

def altman_zone(z):
    if z is None: return 'N/A'
    return 'Safe' if z>2.99 else 'Grey' if z>1.81 else 'Distress'

def calc_piotroski(m):
    s = 0
    roa=nv(m,'roaTTM'); roa_a=nv(m,'roaAnnual'); cf=nv(m,'cashFlowPerShareTTM') or nv(m,'freeCashFlowPerShareTTM')
    de=de_ratio(m); cr=nv(m,'currentRatioAnnual'); gm=nv(m,'grossMarginTTM') or nv(m,'grossMarginAnnual'); at=nv(m,'assetTurnoverAnnual')
    if roa>0: s+=1
    if cf>0: s+=1
    if roa>=roa_a*0.9: s+=1
    if cf>roa: s+=1
    if de<1.0: s+=1
    if cr>=1.0: s+=1
    if gm>20: s+=1
    if at>0.5: s+=1
    if roa>5: s+=1
    return min(9, s)

def piotroski_label(f):
    return 'Strong' if f>=7 else 'Neutral' if f>=4 else 'Weak'

def call_openai(ticker, name, industry, price, m, rsi_v, macd_v, s50, s200,
                sb, b, h, sells, ss, tp, earnings, z, f_score, sc):
    de=de_ratio(m); cr=nv(m,'currentRatioAnnual'); pm=nv(m,'netMarginTTM'); om=nv(m,'operatingMarginTTM')
    roe=nv(m,'roeTTM'); roa=nv(m,'roaTTM'); rg=rev_growth_pct(m); beta=nv(m,'beta')
    total_an=sb+b+h+sells+ss
    upside=round((tp-price)/price*100,1) if tp and price and price>0 else None
    trend='BULLISH(SMA50>SMA200)' if s50 and s200 and s50>s200 else 'BEARISH(SMA50<SMA200)' if s50 and s200 else 'N/A'
    eq_str=' | '.join([f"Q{i+1}:${e.get('actual','?')}vsEst${e.get('estimate','?')}({(e.get('surprise') or 0):.1f}%)" for i,e in enumerate((earnings or [])[:4])]) or 'N/A'
    prompt=f"""Senior Goldman Sachs equity analyst. Data-driven institutional research note.
COMPANY:{name}({ticker}) INDUSTRY:{industry} PRICE:${price} MCAP:${nv(m,'marketCapitalization'):.0f}M
FUND: PE={nv(m,'peBasicExclExtraTTM'):.1f} PB={nv(m,'pbAnnual'):.2f} Beta={beta:.2f} NetMgn={pm:.1f}% OpMgn={om:.1f}% GrMgn={nv(m,'grossMarginTTM'):.1f}% ROE={roe:.1f}% ROA={roa:.1f}% RevGrow={rg:.1f}% EPS={nv(m,'epsBasicExclExtraTTM'):.2f} DE={de:.2f}x CR={cr:.2f} DivYld={nv(m,'dividendYieldIndicatedAnnual'):.2f}%
TECH: RSI={rsi_v or 'N/A'} MACD={macd_v or 'N/A'} SMA50=${s50 or 'N/A'} SMA200=${s200 or 'N/A'} {trend}
ANALYSTS({total_an}): StrongBuy={sb} Buy={b} Hold={h} Sell={sells} SS={ss} Target=${tp or 'N/A'} Upside={upside}%
EARNINGS:{eq_str}
SCORES: Composite={sc['total']}/100 F:{sc['fundamental']}/35 T:{sc['technical']}/25 A:{sc['analyst']}/25 Acc:{sc['accounting']}/15
AltmanZ={z or 'N/A'}({altman_zone(z)}) PiotroskiF={f_score}/9({piotroski_label(f_score)})
RULES: Every sentence needs a number. No vague adjectives. 2-3 sentences per field.
Return ONLY valid JSON no markdown:
{{"verdict":"sharp CFO boardroom sentence+key number","verdict_sub":"score+key signal","verdict_color":"green|amber|red","verdict_icon":"✓|◐|✕","capital":"D/E ROE ROA current ratio exact numbers","cashflow":"margins revenue growth exact numbers","technical_analysis":"RSI SMA MACD specific numbers interpretation","analyst_view":"buy/hold/sell counts target upside","solvency":"Altman Z Piotroski F credit risk","risks":"3 specific risks tied to metrics","credit_decision":"credit decision with numbers","strategic_position":"competitive moat sector position","plain_debt":"2 sentences no-finance reader","plain_profit":"2 sentences no-finance reader","plain_lend":"2 sentences bank lending today"}}"""
    try:
        payload=json.dumps({'model':'gpt-4o-mini','max_tokens':1600,'messages':[
            {'role':'system','content':'Financial analyst. Return ONLY valid JSON no markdown.'},
            {'role':'user','content':prompt}]}).encode()
        req=urllib.request.Request('https://api.openai.com/v1/chat/completions',data=payload,
            headers={'Content-Type':'application/json','Authorization':f'Bearer {OPENAI}'})
        with urllib.request.urlopen(req, timeout=30) as r:
            data=json.loads(r.read()); text=data['choices'][0]['message']['content']
            return json.loads(text.replace('```json','').replace('```','').strip())
    except:
        return fallback_analysis(ticker,name,industry,price,m,rsi_v,s50,s200,sb,b,h,sells,ss,tp,z,f_score,sc)

def fallback_analysis(ticker,name,industry,price,m,rsi_v,s50,s200,sb,b,h,sells,ss,tp,z,f_score,sc):
    sv=sc['total']; col='green' if sv>=70 else 'red' if sv<50 else 'amber'
    icon='✓' if sv>=70 else '✕' if sv<50 else '◐'
    pm=nv(m,'netMarginTTM'); om=nv(m,'operatingMarginTTM'); roe=nv(m,'roeTTM'); roa=nv(m,'roaTTM')
    de=de_ratio(m); cr=nv(m,'currentRatioAnnual'); rg=rev_growth_pct(m); beta=nv(m,'beta')
    total_an=sb+b+h+sells+ss; trend='bullish (SMA50>SMA200)' if s50 and s200 and s50>s200 else 'bearish (SMA50<SMA200)' if s50 and s200 else 'unclear'
    upside=round((tp-price)/price*100,1) if tp and price and price>0 else None
    return {
        'verdict':f"{name} scores {sv}/100 with {pm:.1f}% net margin, {roe:.1f}% ROE and {de:.2f}x leverage.",
        'verdict_sub':f"Composite {sv}/100 — {'solid fundamentals across all pillars' if sv>=70 else 'mixed signals require monitoring' if sv>=50 else 'multiple risk flags detected'}.",
        'verdict_color':col,'verdict_icon':icon,
        'capital':f"D/E of {de:.2f}x with ROE {roe:.1f}% and ROA {roa:.1f}%. Current ratio of {cr:.2f} {'provides adequate coverage' if cr>=1.2 else 'indicates tight liquidity'}.",
        'cashflow':f"Net margin {pm:.1f}% on operating margin {om:.1f}%. Revenue growth of {rg:.1f}% {'supports' if rg>0 else 'pressures'} FCF generation.",
        'technical_analysis':f"RSI at {rsi_v or 'N/A'} — {'neutral zone' if rsi_v and 40<=rsi_v<=65 else 'overbought' if rsi_v and rsi_v>70 else 'oversold' if rsi_v and rsi_v<30 else 'moderate'}. Price trend is {trend}.",
        'analyst_view':f"{sb+b}/{total_an} analysts rate Buy vs {sells+ss} Sell. {'Target $'+str(round(tp,2))+' implies '+str(upside)+'% upside.' if upside else 'Analyst target unavailable.'}",
        'solvency':f"Altman Z {z or 'N/A'} ({altman_zone(z)} zone). Piotroski F {f_score}/9 ({piotroski_label(f_score)} quality).",
        'risks':f"{'Revenue decline '+str(abs(round(rg,1)))+'%' if rg<0 else 'Margin pressure at '+str(round(pm,1))+'%'}, {'leverage '+str(round(de,2))+'x' if de>2 else 'sector competition'}, Beta {beta:.2f} market sensitivity.",
        'credit_decision':f"{'Extend credit — strong metrics support debt service.' if sv>=70 else 'Maintain with quarterly review.' if sv>=50 else 'Reduce exposure — risk profile warrants caution.'}",
        'strategic_position':f"{name} in {industry}. Score {sv}/100 {'leads' if sv>=70 else 'tracks' if sv>=50 else 'lags'} sector peers.",
        'plain_debt':f"{'Manageable debt' if de<1.5 else 'High debt'} — £{de:.2f} owed per £1 of equity. {'Comfortable for lenders.' if de<1 else 'Needs steady income to service interest.'}",
        'plain_profit':f"Keeps {pm:.1f}p of every £1 earned. {'Strong cash generator.' if pm>15 else 'Profitable but thin buffer.' if pm>5 else 'Barely covering costs.'}",
        'plain_lend':f"{'Bank would lend with confidence.' if sv>=70 else 'Bank would lend with conditions.' if sv>=50 else 'Bank would be cautious or decline.'} {'Strong cash flow supports repayment.' if sv>=70 else 'Mixed signals require covenants.'}"
    }

def analyse(ticker):
    now=int(time.time()); yr_ago=now-365*24*3600
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs={
            'profile': ex.submit(fh,'stock/profile2',{'symbol':ticker}),
            'quote':   ex.submit(fh,'quote',{'symbol':ticker}),
            'metrics': ex.submit(fh,'stock/metric',{'symbol':ticker,'metric':'all'}),
            'candles': ex.submit(fh,'stock/candle',{'symbol':ticker,'resolution':'D','from':yr_ago,'to':now}),
            'earnings':ex.submit(fh,'stock/earnings',{'symbol':ticker,'limit':8}),
            'recs':    ex.submit(fh,'stock/recommendation-trends',{'symbol':ticker}),
            'target':  ex.submit(fh,'stock/price-target',{'symbol':ticker}),
        }
        res={k:v.result() for k,v in futs.items()}
    profile=res['profile']; quote=res['quote']; m=res['metrics'].get('metric',{})
    candles=res['candles']; earnings=res['earnings'] if isinstance(res['earnings'],list) else []
    recs=res['recs'] if isinstance(res['recs'],list) else []; target=res['target'] if isinstance(res['target'],dict) else {}
    if not profile.get('name'): raise Exception(f'Ticker "{ticker}" not found. Try AAPL, MSFT, NVDA, JPM.')
    closes=[c for c in (candles.get('c') or []) if c is not None]
    dates=candles.get('t') or []
    rsi_v=calc_rsi(closes) if len(closes)>=15 else None
    macd_v=calc_macd(closes) if len(closes)>=35 else None
    s50=calc_sma(closes,50); s200=calc_sma(closes,200)
    price=quote.get('c'); change=quote.get('d'); chg_pct=quote.get('dp')
    rec=recs[0] if recs else {}
    sb,b,h=rec.get('strongBuy',0),rec.get('buy',0),rec.get('hold',0)
    sells,ss=rec.get('sell',0),rec.get('strongSell',0)
    tp=target.get('targetMean')
    sc=compute_score(m,rsi_v,s50,s200,macd_v,sb,b,h,sells,ss,tp,price)
    z=calc_altman(m); f_s=calc_piotroski(m)
    name=profile.get('name',ticker); industry=profile.get('finnhubIndustry','N/A')
    ai=call_openai(ticker,name,industry,price,m,rsi_v,macd_v,s50,s200,sb,b,h,sells,ss,tp,earnings,z,f_s,sc)
    upside=round((tp-price)/price*100,1) if tp and price and price>0 else None
    return {
        'ticker':ticker,'name':name,'exchange':profile.get('exchange',''),'industry':industry,
        'logo':profile.get('logo',''),'website':profile.get('weburl',''),
        'price':price,'change':change,'change_pct':chg_pct,
        'high_52w':m.get('52WeekHigh'),'low_52w':m.get('52WeekLow'),
        'metrics':{'pe':m.get('peBasicExclExtraTTM'),'pb':m.get('pbAnnual'),'beta':m.get('beta'),
            'net_margin':m.get('netMarginTTM'),'op_margin':m.get('operatingMarginTTM'),
            'gross_margin':m.get('grossMarginTTM'),'roe':m.get('roeTTM'),'roa':m.get('roaTTM'),
            'revenue_growth':rev_growth_pct(m),'eps':m.get('epsBasicExclExtraTTM'),
            'debt_equity':de_ratio(m),'current_ratio':m.get('currentRatioAnnual'),
            'dividend_yield':m.get('dividendYieldIndicatedAnnual'),'market_cap':m.get('marketCapitalization'),
            'fcf_per_share':m.get('freeCashFlowPerShareTTM'),'asset_turnover':m.get('assetTurnoverAnnual')},
        'technical':{'rsi':rsi_v,'macd':macd_v,'sma50':s50,'sma200':s200,
            'trend':'bullish' if s50 and s200 and s50>s200 else 'bearish' if s50 and s200 else None,
            'prices':closes[-90:] if len(closes)>=90 else closes,
            'dates':dates[-90:] if len(dates)>=90 else dates},
        'analysts':{'strong_buy':sb,'buy':b,'hold':h,'sell':sells,'strong_sell':ss,
            'total':sb+b+h+sells+ss,'target_price':tp,'upside':upside},
        'earnings':[{'period':e.get('period'),'actual':e.get('actual'),'estimate':e.get('estimate'),'surprise':e.get('surprisePercent')} for e in earnings[:8]],
        'scores':sc,'altman_z':z,'altman_zone':altman_zone(z),
        'piotroski_f':f_s,'piotroski_label':piotroski_label(f_s),'ai':ai
    }

class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin','*')
        self.send_header('Access-Control-Allow-Methods','GET,OPTIONS')
        self.send_header('Access-Control-Allow-Headers','Content-Type')
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
