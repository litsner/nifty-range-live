from fastapi import FastAPI
from fastapi.responses import FileResponse,JSONResponse
from pydantic import BaseModel
from playwright.async_api import async_playwright
import json,re,os
app=FastAPI(title='NIFTY Range Live')
class Query(BaseModel):
    url:str
    support_mode:str='Mirrored downside'
def number(v):
    if v is None:return None
    try:return float(str(v).replace(',','').replace('%','').strip())
    except:
        m=re.search(r'-?\d+(?:\.\d+)?',str(v));return float(m.group()) if m else None
def flatten(x):
    out=[]
    if isinstance(x,list):
        for v in x:out.extend(flatten(v))
    elif isinstance(x,dict):
        keys={str(k).lower().replace(' ','_') for k in x}
        if any(k in keys for k in ('strike','strikeprice','strike_price')):out.append(x)
        for v in x.values():
            if isinstance(v,(list,dict)):out.extend(flatten(v))
    return out
def normalize(rows):
    out=[]
    for row in rows:
        r={str(k).lower().replace(' ','_'):v for k,v in row.items()}
        for side in ('ce','pe','call','put'):
            if isinstance(r.get(side),dict):
                for k,v in r[side].items():r[f'{side}_{str(k).lower().replace(" ","_")}']=v
        def pick(*names):
            for n in names:
                if n in r:return r[n]
            return None
        out.append({'strike':number(pick('strike','strikeprice','strike_price')),'ce_ltp':number(pick('ce_ltp','ce_last_price','call_ltp','call_last_price')),'pe_ltp':number(pick('pe_ltp','pe_last_price','put_ltp','put_last_price')),'ce_delta':number(pick('ce_delta','ce_greeks_delta','call_delta')),'pe_delta':number(pick('pe_delta','pe_greeks_delta','put_delta')),'ce_volume':number(pick('ce_volume','call_volume','ce_vol','call_vol')),'pe_volume':number(pick('pe_volume','put_volume','pe_vol','put_vol'))})
    return [x for x in out if x['strike'] is not None]
async def scrape(url):
    captured=[]
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True)
        page=await browser.new_page(viewport={'width':1440,'height':1000},user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/140 Safari/537.36')
        async def on_response(resp):
            c=resp.headers.get('content-type','').lower();u=resp.url.lower()
            if resp.status==200 and ('json' in c or any(k in u for k in ('option','chain','greek','niftytrader'))):
                try:
                    txt=await resp.text()
                    if len(txt)<10000000:captured.append(txt)
                except:pass
        page.on('response',on_response)
        try:
            await page.goto(url,wait_until='domcontentloaded',timeout=40000);await page.wait_for_timeout(5000);await page.mouse.wheel(0,6000);await page.wait_for_timeout(1500)
        finally:await browser.close()
    rows=[]
    for text in captured:
        try:rows.extend(flatten(json.loads(text)))
        except:pass
    return normalize(rows)
@app.get('/')
async def index():
    return FileResponse(STATIC_DIR / "index.html")
@app.get('/api/health')
async def health():return {'ok':True}
@app.post('/api/range')
async def calculate(q:Query):
    try:
        data=await scrape(q.url);unique={x['strike']:x for x in data};data=list(unique.values())
        if len(data)<2:raise RuntimeError('NiftyTrader data was not extracted. The site may have changed its API or blocked automated access.')
        for x in data:x['total_volume']=(x['ce_volume'] or 0)+(x['pe_volume'] or 0)
        ranked=sorted(data,key=lambda x:(x['total_volume'],x['strike']),reverse=True);r=ranked[0];s=ranked[1]
        higher=min((x for x in data if x['strike']>r['strike']),key=lambda x:x['strike'],default=None);lower=max((x for x in data if x['strike']<s['strike']),key=lambda x:x['strike'],default=None)
        if not higher or not lower:raise RuntimeError('Required adjacent strike was not found.')
        R=r['strike']+(r['ce_ltp'] or 0)*(r['ce_delta'] or 0)+(higher['pe_ltp'] or 0)*(higher['pe_delta'] or 0)
        if q.support_mode=='Literal plus':S=s['strike']+(s['pe_ltp'] or 0)*(s['pe_delta'] or 0)+(lower['ce_ltp'] or 0)*(lower['ce_delta'] or 0);sf=f"{s['strike']:,.0f} + ({s['pe_ltp']} × {s['pe_delta']}) + ({lower['ce_ltp']} × {lower['ce_delta']})"
        else:S=s['strike']-(s['pe_ltp'] or 0)*abs(s['pe_delta'] or 0)-(lower['ce_ltp'] or 0)*abs(lower['ce_delta'] or 0);sf=f"{s['strike']:,.0f} − ({s['pe_ltp']} × |{s['pe_delta']}|) − ({lower['ce_ltp']} × |{lower['ce_delta']}|)"
        formula=f"Resistance = {r['strike']:,.0f} + ({r['ce_ltp']} × {r['ce_delta']}) + ({higher['pe_ltp']} × {higher['pe_delta']}) = <b>{R:,.2f}</b><br>Support = {sf} = <b>{S:,.2f}</b>"
        return {'support':S,'resistance':R,'highest_volume_strike':r['strike'],'second_volume_strike':s['strike'],'top':ranked[:12],'formula_html':formula,'source':'NiftyTrader browser capture'}
    except Exception as e:return JSONResponse({'error':str(e)},status_code=502)
if __name__=='__main__':
    import uvicorn;uvicorn.run(app,host='0.0.0.0',port=int(os.getenv('PORT','10000')))
