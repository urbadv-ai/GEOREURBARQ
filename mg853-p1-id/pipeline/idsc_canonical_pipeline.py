from __future__ import annotations
import hashlib,json,os,re,unicodedata
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timezone
from pathlib import Path
from typing import Any
import pandas as pd,requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROOT=Path('mg853-p1-id'); DATA=ROOT/'data'; RAW=DATA/'raw'/'current'; NORM=DATA/'normalized'; MG=DATA/'mg853'; META=DATA/'metadata'; HIST=DATA/'history'
for p in (RAW,NORM,MG,META,HIST): p.mkdir(parents=True,exist_ok=True)
NOW=datetime.now(timezone.utc); TS=NOW.replace(microsecond=0).isoformat().replace('+00:00','Z'); DAY=NOW.date().isoformat(); VERSION='1.0.0'
CFG=json.loads((ROOT/'config'/'idsc_pipeline_config_v1_0.json').read_text(encoding='utf-8'))
BASE=CFG['fontes']['idsc_api_base']; IBGE_URL=CFG['fontes']['ibge_municipios_url']; CITY=CFG['endpoints']['municipios_nacionais']; AUX=CFG['endpoints']['auxiliares_nacionais']; Q=CFG['controles_qualidade']

def norm(v:Any)->str:
    s='' if v is None else str(v); s=unicodedata.normalize('NFKD',s).encode('ascii','ignore').decode().lower(); return re.sub(r'[^a-z0-9]+',' ',s).strip()
def col(v:Any)->str: return norm(v).replace(' ','_') or 'campo'
def hbytes(b:bytes)->str: return hashlib.sha256(b).hexdigest()
def hfile(p:Path)->str:
    h=hashlib.sha256()
    with p.open('rb') as f:
        for c in iter(lambda:f.read(1024*1024),b''): h.update(c)
    return h.hexdigest()
def session():
    r=Retry(total=5,connect=5,read=5,status=5,backoff_factor=1.2,status_forcelist=(429,500,502,503,504),allowed_methods=frozenset(['GET']),respect_retry_after_header=True)
    s=requests.Session(); s.mount('https://',HTTPAdapter(max_retries=r,pool_connections=16,pool_maxsize=16)); s.headers.update({'User-Agent':'GEOREURBARQ-IDSC/1.0 public-data-research','Referer':'https://idsc.cidadessustentaveis.org.br/','Origin':'https://idsc.cidadessustentaveis.org.br','Accept':'application/json,text/plain,*/*'}); return s
S=session()
def get(url,timeout=180):
    r=S.get(url,timeout=timeout,allow_redirects=True); r.raise_for_status(); return r.json(),r.content,r.url
def flat(o,p=''):
    out={}
    if isinstance(o,dict):
        for k,v in o.items():
            q=f'{p}.{k}' if p else str(k)
            if isinstance(v,dict): out.update(flat(v,q))
            elif isinstance(v,list): out[q]=json.dumps(v,ensure_ascii=False,separators=(',',':'))
            else: out[q]=v
    return out
def lod(o,p='root'):
    out=[]
    if isinstance(o,list):
        if o and all(isinstance(x,dict) for x in o[:min(5,len(o))]): out.append((p,o))
        for i,v in enumerate(o[:20]):
            if isinstance(v,(list,dict)): out+=lod(v,f'{p}[{i}]')
    elif isinstance(o,dict):
        for k,v in o.items():
            if isinstance(v,(list,dict)): out+=lod(v,f'{p}.{k}')
    return out
def leaves(o,p='root'):
    if isinstance(o,dict):
        for k,v in o.items(): yield from leaves(v,f'{p}.{k}')
    elif isinstance(o,list):
        for i,v in enumerate(o): yield from leaves(v,f'{p}[{i}]')
    else: yield p,o
def pick(cols,patterns,exact=()):
    m={c:norm(c) for c in cols}; ex={norm(x) for x in exact}
    for c,n in m.items():
        if n in ex:return c
    for pat in patterns:
        for c,n in m.items():
            if re.search(pat,n):return c
    return None
def csv(df,p): p.parent.mkdir(parents=True,exist_ok=True); df.to_csv(p,index=False,encoding='utf-8-sig')

def raw(name,b,url,manifest):
    p=RAW/name; p.write_bytes(b); manifest.append({'arquivo':str(p.relative_to(DATA)),'fonte_url':url,'sha256':hbytes(b),'bytes':len(b),'capturado_em_utc':TS})

def ibge_map(manifest):
    obj,b,url=get(IBGE_URL); raw('ibge_sidra_4714_municipios_2022.json',b,url,manifest); d=pd.DataFrame(obj[1:])
    if not {'D1C','D1N'}<=set(d.columns): raise RuntimeError('IBGE SIDRA sem D1C/D1N')
    x=d[['D1C','D1N']].drop_duplicates(); x['cod_ibge_7']=x.D1C.astype(str).str.replace(r'\.0$','',regex=True); z=x.D1N.astype(str).str.extract(r'^(.*?)(?:\s+-\s+([A-Z]{2}))?$'); x['municipio_ibge']=z[0].str.strip(); x['uf']=z[1].fillna(''); x['nome_norm']=x.municipio_ibge.map(norm); x=x[['cod_ibge_7','municipio_ibge','uf','nome_norm']].drop_duplicates('cod_ibge_7')
    if x.cod_ibge_7.nunique()<Q['ibge_nacional_minimo']: raise RuntimeError(f'IBGE incompleto: {x.cod_ibge_7.nunique()}')
    csv(x.drop(columns='nome_norm'),META/'ibge_municipios_crosswalk.csv'); return x

def city_table(records,endpoint,ibge):
    f=pd.DataFrame([flat(r) for r in records]); cols=list(f.columns)
    cc=pick(cols,[r'(cod|codigo).*ibge',r'ibge.*(cod|codigo)'],['cod_ibge_7','codigo_ibge']); nc=pick(cols,[r'nome.*(cidade|municipio)',r'(cidade|municipio).*nome'],['municipio','cidade','nome']); uc=pick(cols,[r'(^| )uf($| )',r'sigla.*(uf|estado)'],['uf','sigla_uf']); ic=pick(cols,[r'id.*(perfil|cidade|municipio)',r'(perfil|cidade|municipio).*id'],['id','id_cidade','cidade_id','id_perfil_cidade']); sc=pick(cols,[r'pontuacao.*(geral|idsc)',r'score.*(geral|idsc)'],['pontuacao','score']); rc=pick(cols,[r'classificacao.*geral',r'ranking.*geral',r'posicao.*geral'],['classificacao','ranking','posicao']); lc=pick(cols,[r'nivel.*desenvolvimento',r'desenvolvimento.*nivel'],['nivel'])
    w=f.copy(); w['cod_ibge_7']=w[cc].astype(str).str.extract(r'(\d{7})',expand=False) if cc else pd.NA
    if nc:
        rn=w[nc].astype(str).str.strip(); w['nome_idsc']=rn.str.replace(r'\s*[\(\-\/]\s*[A-Z]{2}\s*\)?\s*$','',regex=True).str.strip(); w['nome_norm']=w.nome_idsc.map(norm); w['uf_idsc']=w[uc].astype(str).str.upper().str.strip() if uc else rn.str.extract(r'(?:\(|-|/)\s*([A-Z]{2})\s*\)?\s*$',expand=False).fillna('')
    else: w['nome_idsc']=''; w['nome_norm']=''; w['uf_idsc']=w[uc].astype(str).str.upper().str.strip() if uc else ''
    ref=ibge.rename(columns={'municipio_ibge':'municipio_ref','uf':'uf_ref'}); w=w.merge(ref[['cod_ibge_7','municipio_ref','uf_ref']],on='cod_ibge_7',how='left'); w['municipio_ibge']=w.municipio_ref; w['uf']=w.uf_ref; w['status_vinculo_ibge']=w.municipio_ref.notna().map({True:'CODIGO_IBGE',False:'PENDENTE'})
    mp=ibge[['cod_ibge_7','municipio_ibge','uf','nome_norm']]
    for i in w.index[w.status_vinculo_ibge.eq('PENDENTE') & w.nome_norm.ne('')]:
        c=mp[mp.nome_norm.eq(w.at[i,'nome_norm'])]; u=str(w.at[i,'uf_idsc'] or '').upper(); cu=c[c.uf.eq(u)] if u else c
        if len(cu)==1: r=cu.iloc[0]; w.loc[i,['cod_ibge_7','municipio_ibge','uf','status_vinculo_ibge']]=[r.cod_ibge_7,r.municipio_ibge,r.uf,'NOME_UF' if u else 'NOME_UNICO']
        elif len(c)>1:w.at[i,'status_vinculo_ibge']='AMBIGUO'
        else:w.at[i,'status_vinculo_ibge']='SEM_MATCH'
    ids=w[ic].astype(str).str.replace(r'\.0$','',regex=True).str.strip() if ic else pd.Series(pd.NA,index=w.index); ids=ids.replace({'':'','nan':'','None':''}).replace('',pd.NA)
    c=pd.DataFrame({'cod_ibge_7':w.cod_ibge_7,'municipio_ibge':w.municipio_ibge,'uf':w.uf,'id_cidade_idsc':ids,'pontuacao_geral_idsc':pd.to_numeric(w[sc],errors='coerce') if sc else pd.NA,'classificacao_geral_idsc':pd.to_numeric(w[rc],errors='coerce') if rc else pd.NA,'nivel_desenvolvimento_idsc':w[lc] if lc else pd.NA,'status_vinculo_ibge':w.status_vinculo_ibge,'sistema_origem':'IDSC-BR','endpoint_origem':endpoint,'fonte':'Instituto Cidades Sustentáveis / IDSC-BR','url_fonte':BASE+endpoint,'data_extracao_utc':TS})
    c['hash_registro_origem']=[hbytes(json.dumps(r,ensure_ascii=False,sort_keys=True,default=str).encode()) for r in records]
    ren={x:f'src__{col(x)}' for x in f.columns}; sw=w.rename(columns=ren); front=['cod_ibge_7','municipio_ibge','uf','status_vinculo_ibge','nome_idsc','uf_idsc']; sw=sw[front+[ren[x] for x in f.columns if ren[x] in sw.columns]]; sw.insert(0,'endpoint_origem',endpoint); sw.insert(0,'data_extracao_utc',TS)
    return c.drop_duplicates(['cod_ibge_7','id_cidade_idsc','hash_registro_origem']),sw

def fetch_detail(job):
    code,cid,templ=job; url=BASE+templ.format(city_id=cid); s=session()
    try:r=s.get(url,timeout=120); r.raise_for_status(); return code,cid,url,r.json(),None
    except Exception as e:return code,cid,url,None,repr(e)
    finally:s.close()
def long_payload(results,names):
    rows=[]; errs=[]
    for code,cid,url,obj,err in results:
        if err: errs.append({'cod_ibge_7':code,'id_cidade_idsc':cid,'url_fonte':url,'erro':err}); continue
        hh=hbytes(json.dumps(obj,ensure_ascii=False,sort_keys=True,default=str).encode())
        for p,v in leaves(obj): rows.append({'cod_ibge_7':code,'municipio_ibge':names.get(code,''),'uf':'MG','id_cidade_idsc':cid,'json_path':p,'valor':v,'hash_payload_origem':hh,'url_fonte':url,'data_extracao_utc':TS})
    return pd.DataFrame(rows),pd.DataFrame(errs)

def main():
    manifest=[]; inv=[]; ibge=ibge_map(manifest); payload={}
    for ep in list(dict.fromkeys(CITY+AUX)):
        try:o,b,u=get(BASE+ep); payload[ep]=o; raw(f'idsc_{ep}.json',b,u,manifest); ls=lod(o); inv.append({'endpoint':ep,'status':'OK','url':u,'bytes':len(b),'listas_detectadas':len(ls),'maior_lista':max((len(x[1]) for x in ls),default=0)})
        except Exception as e:inv.append({'endpoint':ep,'status':'ERRO','url':BASE+ep,'erro':repr(e)})
    cand=[]
    for pri,ep in enumerate(CITY):
        for _,records in lod(payload.get(ep,{})):cand.append((len(records),-pri,ep,records))
    if not cand:raise RuntimeError('IDSC sem lista municipal detectável')
    _,_,ep,records=max(cand,key=lambda x:(x[0],x[1])); nat,wide=city_table(records,ep,ibge); nat=nat.sort_values(['cod_ibge_7','id_cidade_idsc'],na_position='last'); csv(nat,NORM/'idsc_brasil_municipios.csv'); csv(wide,NORM/'idsc_brasil_municipios_source_wide.csv')
    for a in AUX:
        ls=lod(payload.get(a,{}))
        if ls:
            p,rs=max(ls,key=lambda x:len(x[1])); d=pd.DataFrame([flat(r) for r in rs]); d.columns=[f'src__{col(x)}' for x in d.columns]; d.insert(0,'json_path_lista',p); d.insert(0,'endpoint_origem',a); d.insert(0,'data_extracao_utc',TS); csv(d,NORM/f'idsc_brasil_{col(a)}.csv')
    img=ibge[ibge.cod_ibge_7.str.startswith('31')].copy().sort_values('cod_ibge_7'); best=nat.dropna(subset=['cod_ibge_7']).drop_duplicates('cod_ibge_7'); mg=img[['cod_ibge_7','municipio_ibge','uf']].merge(best.drop(columns=['municipio_ibge','uf'],errors='ignore'),on='cod_ibge_7',how='left'); mg['status_cobertura_idsc']=mg.id_cidade_idsc.notna().map({True:'OK',False:'SEM_IDSC'}); csv(mg,MG/'mg_853_idsc_municipios.csv')
    matched=mg.dropna(subset=['id_cidade_idsc']); jobs=[]; odse=CFG['endpoints']['detalhe_mg_ods']; sere=CFG['endpoints']['detalhe_mg_series']
    for r in matched.itertuples(index=False):
        cid=str(r.id_cidade_idsc).replace('.0',''); jobs += [(str(r.cod_ibge_7),cid,odse),(str(r.cod_ibge_7),cid,sere)]
    res=[]
    with ThreadPoolExecutor(max_workers=max(1,min(int(os.getenv('IDSC_MAX_WORKERS',CFG['concorrencia']['max_workers'])),12))) as ex:
        for f in as_completed([ex.submit(fetch_detail,j) for j in jobs]):res.append(f.result())
    names=img.set_index('cod_ibge_7').municipio_ibge.to_dict(); om=odse.split('/{')[0]; sm=sere.split('/{')[0]; ol,oe=long_payload([x for x in res if om in x[2]],names); sl,se=long_payload([x for x in res if sm in x[2]],names)
    if not ol.empty:csv(ol.sort_values(['cod_ibge_7','json_path']),MG/'mg_853_idsc_ods_long.csv')
    if not sl.empty:csv(sl.sort_values(['cod_ibge_7','json_path']),MG/'mg_853_idsc_series_long.csv')
    err=pd.concat([oe.assign(tipo='ODS'),se.assign(tipo='SERIE')],ignore_index=True) if not oe.empty or not se.empty else pd.DataFrame()
    if not err.empty:csv(err,META/'mg_853_idsc_detail_errors.csv')
    elif (META/'mg_853_idsc_detail_errors.csv').exists():(META/'mg_853_idsc_detail_errors.csv').unlink()
    checks={'pipeline_version':VERSION,'gerado_em_utc':TS,'snapshot_date':DAY,'endpoint_municipal_selecionado':ep,'registros_municipais_fonte':len(records),'municipios_nacionais_com_codigo_ibge_unico':int(nat.cod_ibge_7.dropna().nunique()),'registros_nacionais_sem_codigo_ibge':int(nat.cod_ibge_7.isna().sum()),'municipios_ibge_total':int(ibge.cod_ibge_7.nunique()),'municipios_mg_ibge':int(img.cod_ibge_7.nunique()),'municipios_mg_com_idsc':int(mg.id_cidade_idsc.notna().sum()),'municipios_mg_sem_idsc':int(mg.id_cidade_idsc.isna().sum()),'cobertura_ods_detalhada_mg':int(ol.cod_ibge_7.nunique()) if not ol.empty else 0,'cobertura_series_mg':int(sl.cod_ibge_7.nunique()) if not sl.empty else 0,'erros_detalhamento_mg':int(len(err)),'criterios_aprovacao':Q}
    checks['status_qualidade']='APROVADO' if checks['municipios_ibge_total']>=Q['ibge_nacional_minimo'] and checks['municipios_nacionais_com_codigo_ibge_unico']>=Q['idsc_nacional_minimo_codigos_unicos'] and checks['municipios_mg_ibge']==Q['mg_ibge_exato'] and checks['municipios_mg_com_idsc']==Q['mg_idsc_exato'] else 'REPROVADO'
    (META/'idsc_quality_checks.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2),encoding='utf-8'); csv(pd.DataFrame(inv),META/'idsc_source_inventory.csv'); (META/'raw_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    if checks['status_qualidade']!='APROVADO':raise RuntimeError('Carga IDSC reprovada: '+json.dumps(checks,ensure_ascii=False))
    files=[{'arquivo':str(p.relative_to(DATA)),'sha256':hfile(p),'bytes':p.stat().st_size} for p in sorted(DATA.rglob('*')) if p.is_file() and 'history' not in p.parts and p.name!='dataset_manifest.json']; dm={'pipeline_version':VERSION,'gerado_em_utc':TS,'snapshot_date':DAY,'status_qualidade':'APROVADO','chave_territorial_canonica':'cod_ibge_7','fonte_principal':'IDSC-BR / Instituto Cidades Sustentáveis','arquivos':files}; (META/'dataset_manifest.json').write_text(json.dumps(dm,ensure_ascii=False,indent=2),encoding='utf-8'); sd=HIST/DAY; sd.mkdir(parents=True,exist_ok=True); (sd/'manifest_snapshot.json').write_text(json.dumps(dm,ensure_ascii=False,indent=2),encoding='utf-8'); (sd/'quality_snapshot.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2),encoding='utf-8'); print(json.dumps(checks,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
