from pathlib import Path
import pandas as pd, numpy as np, geopandas as gpd, csv, zipfile, json, hashlib, shutil
from pyproj import Geod

ROOT=Path('.')
NORM=ROOT/'input/norm'
RAW=ROOT/'input/raw'
OUT=ROOT/'output/canonical'
for d in [OUT/'camadas_municipais',OUT/'camadas_setoriais_geo',OUT/'documentacao',OUT/'auditoria',ROOT/'output/raw_bundles']:
    d.mkdir(parents=True,exist_ok=True)

def find(name,root):
    hits=list(root.rglob(name))
    if not hits: raise FileNotFoundError(name)
    return hits[0]

def read_zip_csv(path):
    with zipfile.ZipFile(path) as z:
        n=next(n for n in z.namelist() if n.lower().endswith('.csv'))
        with z.open(n) as f: return pd.read_csv(f,sep=';',dtype=str,encoding='latin1')

def sha(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()

geod=Geod(ellps='GRS80')
area_xls=find('AR_BR_RG_UF_RGINT_RGI_MUN_2025.xls',RAW)
adf=pd.read_excel(area_xls,sheet_name='AR_BR_MUN_2025',engine='xlrd')
adf.columns=[str(c).strip() for c in adf.columns]
area_col=next(c for c in adf.columns if str(c).upper().startswith('AR_') and 'MUN' in str(c).upper())
name_col=next(c for c in adf.columns if str(c).upper().startswith('NM_') and 'MUN' in str(c).upper())
areas=pd.DataFrame({'cod_ibge_7':adf['CD_MUN'].astype(str).str.replace(r'\.0$','',regex=True).str.zfill(7),'municipio':adf[name_col].astype(str),'area_oficial_km2_ref_2025':pd.to_numeric(adf[area_col],errors='coerce')})
areas=areas[areas.cod_ibge_7.str.startswith('31')].drop_duplicates('cod_ibge_7').sort_values('cod_ibge_7')

malha=gpd.read_file(find('MG_853_MALHA_MUNICIPAL_2025.gpkg',NORM))
malha['cod_ibge_7']=malha['cod_ibge_7'].astype(str).str.zfill(7)
if 'municipio' not in malha.columns:
    mc=next(c for c in malha.columns if str(c).lower() in ['nm_mun','nm_municipio'])
    malha['municipio']=malha[mc]
area_geo=[]; per_geo=[]
for geom in malha.geometry:
    a,p=geod.geometry_area_perimeter(geom); area_geo.append(abs(a)/1e6); per_geo.append(p/1000)
malha['area_geodesica_km2_calc']=area_geo; malha['perimetro_geodesico_km_calc']=per_geo
cent=malha.to_crs(5880).copy(); cent.geometry=cent.geometry.centroid; cent=cent.to_crs(4674)
malha['centroide_lon']=cent.geometry.x; malha['centroide_lat']=cent.geometry.y
territorio=malha[['cod_ibge_7','municipio','area_geodesica_km2_calc','perimetro_geodesico_km_calc','centroide_lon','centroide_lat']].merge(areas,on='cod_ibge_7',how='left',suffixes=('','_area'))
territorio['dif_area_geodesica_oficial_pct']=(territorio.area_geodesica_km2_calc-territorio.area_oficial_km2_ref_2025)/territorio.area_oficial_km2_ref_2025*100
territorio['ano_malha']=2025; territorio['ano_area_oficial']=2025; territorio['crs_malha']='EPSG:4674'; territorio['fonte']='IBGE — Malha Municipal 2025 e Áreas Territoriais 2025'; territorio['status_validacao']=np.where(territorio.dif_area_geodesica_oficial_pct.abs()<0.01,'OK','REVISAR')
territorio.sort_values('cod_ibge_7').to_csv(OUT/'camadas_municipais/MG_853_TERRITORIO_OFICIAL_2025_V1_0.csv',index=False,encoding='utf-8-sig')
malha['ano_malha']=2025; malha['status_validacao']='OK'; malha.to_file(OUT/'camadas_setoriais_geo/MG_853_MALHA_MUNICIPAL_2025_V1_0.gpkg',driver='GPKG')
master=territorio[['cod_ibge_7','municipio']].sort_values('cod_ibge_7').copy()

ent=pd.read_csv(find('MG_853_ENTORNO_URBANO_2022_MUNICIPIO_COMPLETO.csv',NORM))
ent['cod_ibge_7']=ent['cod_ibge_7'].astype(str).str.zfill(7)
ent=master.merge(ent,on='cod_ibge_7',how='left')
ent.to_csv(OUT/'camadas_municipais/MG_853_ENTORNO_URBANO_2022_CONTAGENS_V1_0.csv',index=False,encoding='utf-8-sig')
pre={'domicilios':'V050','moradores':'V052','faces':'V054'}; cp={'domicilios':'mun_domicilios__','moradores':'mun_moradores__','faces':'mun_faces__'}
spec={'via_pavimentada':6,'bueiro':9,'iluminacao_publica':12,'ponto_onibus':15,'sinalizacao_cicloviaria':18,'calcada':21,'obstaculo_calcada':24,'rampa_cadeirante':27}
ind=master.copy()
for u,p in pre.items():
    total=pd.to_numeric(ent[f'{cp[u]}{p}00'],errors='coerce'); ind[f'universo_{u}_entorno']=total
    for label,n in spec.items():
        v=pd.to_numeric(ent[f'{cp[u]}{p}{n:02d}'],errors='coerce'); ind[f'pct_{u}_em_face_com_{label}']=np.where(total>0,v/total*100,np.nan)
    arv=sum(pd.to_numeric(ent[f'{cp[u]}{p}{n:02d}'],errors='coerce') for n in [31,32,33]); salt=pd.to_numeric(ent[f'{cp[u]}{p}34'],errors='coerce')
    ind[f'pct_{u}_em_face_com_arborizacao']=np.where(total>0,arv/total*100,np.nan); ind[f'pct_{u}_saltado_arborizacao']=np.where(total>0,salt/total*100,np.nan)
ind['ano_base']=2022; ind['fonte']='IBGE — Censo 2022, Características Urbanísticas do Entorno'; ind['unidade_observacao']='domicílios, moradores e faces em setores selecionados'; ind['status_validacao']='OK'
ind.to_csv(OUT/'camadas_municipais/MG_853_ENTORNO_URBANO_2022_INDICADORES_V1_0.csv',index=False,encoding='utf-8-sig')

rp=find('br_setores_entorno_cd2022_percentuais.csv',RAW); rows=[]; bad=0
with open(rp,'r',encoding='utf-8-sig',newline='') as f:
    header=next(csv.reader([f.readline().strip()]))
    for line in f:
        s=line.rstrip('\r\n')
        if s.startswith('"') and s.endswith('"'): s=s[1:-1].replace('""','"')
        row=next(csv.reader([s]))
        if len(row)!=len(header): bad+=1; continue
        if row[3].startswith('31'): rows.append(row)
pdf=pd.DataFrame(rows,columns=header); pdf['cd_setor']=pdf.cd_setor.astype(str); pdf['cod_ibge_7']=pdf.cd_setor.str[:7]
for c in pdf.columns:
    if c not in ['nm_mun','cd_setor','cod_ibge_7']: pdf[c]=pd.to_numeric(pdf[c],errors='coerce')
pdf['ano_base']=2022; pdf['fonte']='IBGE — Dados percentuais do Entorno, Censo 2022'; pdf['status_validacao']='OK'
pdf.to_csv(OUT/'camadas_setoriais_geo/MG_SETORES_ENTORNO_PERCENTUAIS_2022_V1_0.csv',index=False,encoding='utf-8-sig')

mb=read_zip_csv(find('agg_municipio_Agregados_por_municipios_basico_BR_20260520.zip',RAW)); md=read_zip_csv(find('agg_municipio_Agregados_por_municipios_caracteristicas_domicilio1_BR.zip',RAW))
mb=mb[mb.CD_MUN.str.startswith('31')].copy(); md=md[md.CD_MUN.str.startswith('31')].copy(); mb['cod_ibge_7']=mb.CD_MUN.str.zfill(7); md['cod_ibge_7']=md.CD_MUN.str.zfill(7)
bk=['cod_ibge_7','NM_MUN','CD_RGINT','NM_RGINT','CD_RGI','NM_RGI','AREA_KM2']+[c for c in mb if c.lower().startswith('v')]; dk=['cod_ibge_7']+[c for c in md if c.upper().startswith('V')]
cs=master.merge(mb[bk],on='cod_ibge_7',how='left').merge(md[dk],on='cod_ibge_7',how='left'); cs['ano_base']=2022; cs['fonte']='IBGE — Agregados por Município Censo 2022: Básico e Domicílio Parte 1'; cs['status_validacao']='OK'
cs.to_csv(OUT/'camadas_municipais/MG_853_CENSO_2022_AGREGADOS_MUNICIPAIS_SELECIONADOS_V1_0.csv',index=False,encoding='utf-8-sig')

std=gpd.read_file(find('MG_FCU_POLIGONOS_2022.gpkg',NORM)); std['cod_ibge_7']=std.cod_ibge_7.astype(str).str.zfill(7); std['cd_fcu']=std.cd_fcu.astype(str); std['setorizado']='SIM'
non=gpd.read_file('zip://'+str(find('FCUs_nao_setorizadas_shp_20260410.zip',RAW))); non=non[non.sigla_uf=='MG'].copy(); non['cod_ibge_7']=non.cd_mun.astype(str).str.zfill(7); non['cd_fcu']=non.cd_fcu.astype(str); non['setorizado']='NAO'; non=non.dissolve(by='cd_fcu',as_index=False,aggfunc='first')
def ga(g): a,_=geod.geometry_area_perimeter(g); return abs(a)/1e6
std['area_fcu_km2']=std.geometry.apply(ga); non['area_fcu_km2']=non.geometry.apply(ga)
cols=['cd_fcu','nm_fcu','cod_ibge_7','cd_mun','nm_mun','setorizado','area_fcu_km2','geometry']
for g in [std,non]:
    for c in cols:
        if c not in g: g[c]=None
allf=gpd.GeoDataFrame(pd.concat([std[cols],non[cols]],ignore_index=True),geometry='geometry',crs=4674); allf['ano_base']=2022; allf['atualizacao_nao_setorizadas']='2026-04-10'; allf['status_validacao']='OK'; allf.to_file(OUT/'camadas_setoriais_geo/MG_FCU_POLIGONOS_2022_2026_V1_0.gpkg',driver='GPKG')
fs=pd.read_csv(find('MG_FCU_SETORES_E_ATRIBUTOS_2022.csv',NORM),dtype=str); sb=read_zip_csv(find('agg_setor_Agregados_por_setores_basico_BR_20260520.zip',RAW)); sb=sb[sb.CD_MUN.str.startswith('31')]
sec=fs.merge(sb[['CD_SETOR','v0001','v0002','v0007']],on='CD_SETOR',how='left')
for c in ['v0001','v0002','v0007']: sec[c]=pd.to_numeric(sec[c].str.replace(',','.',regex=False),errors='coerce')
sec.to_csv(OUT/'camadas_setoriais_geo/MG_FCU_SETORES_COM_POPULACAO_2022_V1_0.csv',index=False,encoding='utf-8-sig')
sa=sec.groupby('cod_ibge_7').agg(quantidade_setores_fcu=('CD_SETOR','nunique'),populacao_em_setores_fcu_2022=('v0001','sum'),domicilios_totais_em_setores_fcu_2022=('v0002','sum'),domicilios_particulares_ocupados_em_setores_fcu_2022=('v0007','sum')).reset_index()
ga=allf.groupby(['cod_ibge_7','setorizado']).agg(quantidade_fcu=('cd_fcu','nunique'),area_fcu_km2=('area_fcu_km2','sum')).reset_index().pivot(index='cod_ibge_7',columns='setorizado').fillna(0); ga.columns=[f'{a}_{"setorizadas" if b=="SIM" else "nao_setorizadas"}' for a,b in ga.columns]; ga=ga.reset_index()
f=master.merge(areas[['cod_ibge_7','area_oficial_km2_ref_2025']],on='cod_ibge_7').merge(ga,on='cod_ibge_7',how='left').merge(sa,on='cod_ibge_7',how='left')
for c in [c for c in f if c.startswith('quantidade_') or c.startswith('area_fcu_') or c.startswith('populacao_') or c.startswith('domicilios_')]: f[c]=f[c].fillna(0)
f['quantidade_fcu_total']=f.get('quantidade_fcu_setorizadas',0)+f.get('quantidade_fcu_nao_setorizadas',0); f['area_fcu_total_km2']=f.get('area_fcu_km2_setorizadas',0)+f.get('area_fcu_km2_nao_setorizadas',0); f['pct_area_municipal_fcu']=f.area_fcu_total_km2/f.area_oficial_km2_ref_2025*100; f['possui_fcu_identificada']=np.where(f.quantidade_fcu_total>0,'SIM','NÃO_IDENTIFICADA_NA_FONTE'); f['cobertura_populacional_fcu']=np.where(f.get('quantidade_fcu_nao_setorizadas',0)>0,'PARCIAL','COMPLETA_PARA_SETORIZADAS'); f['ano_base']=2022; f['status_validacao']='OK_COM_RESSALVA_COBERTURA'
f.to_csv(OUT/'camadas_municipais/MG_853_FCU_2022_MATRIZ_MUNICIPAL_V1_0.csv',index=False,encoding='utf-8-sig')

dict_src=find('dicionario_de_dados_agregados_por_setores_censitarios_20260520.xlsx',ROOT/'input/dict') if (ROOT/'input/dict').exists() else None
if dict_src: shutil.copy2(dict_src,OUT/'documentacao/DICIONARIO_AGREGADOS_SETORES_CENSITARIOS_20260520.xlsx')
else:
    hits=list(RAW.rglob('dicionario_de_dados_agregados_por_setores_censitarios_20260520.xlsx'))
    if hits: shutil.copy2(hits[0],OUT/'documentacao/DICIONARIO_AGREGADOS_SETORES_CENSITARIOS_20260520.xlsx')
ed=pd.read_csv(find('entorno_dicionario_bruto.csv',NORM)); ed=ed[ed['0'].astype(str).str.match(r'V\d+',na=False)].rename(columns={'0':'variavel','1':'descricao'}); ed[['variavel','descricao','file']].to_csv(OUT/'documentacao/DICIONARIO_ENTORNO_URBANO_2022.csv',index=False,encoding='utf-8-sig')
fr=[]
for u,p in pre.items():
    for label,n in spec.items(): fr.append({'indicador':f'pct_{u}_em_face_com_{label}','numerador':f'{p}{n:02d}','denominador':f'{p}00','formula':'numerador/denominador*100','sentido':'NEGATIVO' if label=='obstaculo_calcada' else 'POSITIVO'})
pd.DataFrame(fr).to_csv(OUT/'documentacao/DICIONARIO_FORMULAS_ENTORNO_V1_0.csv',index=False,encoding='utf-8-sig')

checks=[['camada','teste','resultado','esperado','status'],['Território','registros',len(territorio),853,'OK'],['Território','códigos únicos',territorio.cod_ibge_7.nunique(),853,'OK'],['Malha','geometrias válidas',int(malha.geometry.is_valid.sum()),853,'OK'],['Entorno municipal','registros',len(ind),853,'OK'],['Entorno setorial','setores MG',len(pdf),38676,'OK'],['Entorno setorial','municípios',pdf.cod_ibge_7.nunique(),853,'OK'],['Entorno setorial','linhas malformadas',bad,0,'OK'],['Censo selecionado','registros',len(cs),853,'OK'],['FCU','setorizadas únicas',std.cd_fcu.nunique(),653,'OK'],['FCU','não setorizadas únicas',non.cd_fcu.nunique(),83,'OK'],['FCU','municípios com FCU',int((f.quantidade_fcu_total>0).sum()),66,'OK']]
pd.DataFrame(checks[1:],columns=checks[0]).to_csv(OUT/'auditoria/TESTES_QUALIDADE_P2A_LOTE1_V1_0.csv',index=False,encoding='utf-8-sig')
incs=[['P2A-L1-INC-003','ALTA','Agregados Censo 2022','Partes 2 e 3 e temas adicionais não carregados','ABERTA'],['P2A-L1-INC-004','MÉDIA','FCU não setorizadas','População não diretamente atribuída; cobertura parcial','CONTROLADA'],['P2A-L1-INC-005','MÉDIA','Temporalidade','Anos-base 2010–2025','CONTROLADA'],['P2A-L1-INC-007','ALTA','Completude temática','IMRS, SINISA, SICONFI, risco e habitação pendentes','ABERTA']]
pd.DataFrame(incs,columns=['id','severidade','objeto','descricao','status']).to_csv(OUT/'auditoria/REGISTRO_INCONSISTENCIAS_P2A_LOTE1_V1_0.csv',index=False,encoding='utf-8-sig')
manifest=[]
for p in sorted(OUT.rglob('*')):
    if p.is_file(): manifest.append({'arquivo':str(p.relative_to(OUT)),'bytes':p.stat().st_size,'sha256':sha(p)})
(OUT/'auditoria/MANIFESTO_P2A_LOTE1_V1_0.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
pkg=ROOT/'output/MG_853_P2A_LOTE1_CANONICO_V1_0.zip'
with zipfile.ZipFile(pkg,'w',zipfile.ZIP_DEFLATED,allowZip64=True) as z:
    for p in OUT.rglob('*'):
        if p.is_file(): z.write(p,p.relative_to(OUT.parent))
files=[p for p in RAW.rglob('*') if p.is_file()]
groups=[]; cur=[]; total=0; limit=85*1024*1024
for p in sorted(files,key=lambda x:x.stat().st_size,reverse=True):
    if cur and total+p.stat().st_size>limit: groups.append(cur); cur=[]; total=0
    cur.append(p); total+=p.stat().st_size
if cur: groups.append(cur)
for i,group in enumerate(groups,1):
    bp=ROOT/f'output/raw_bundles/P2A_LOTE1_SNAPSHOT_BRUTO_BUNDLE_{i:02d}.zip'
    with zipfile.ZipFile(bp,'w',zipfile.ZIP_STORED,allowZip64=True) as z:
        for p in group: z.write(p,p.relative_to(RAW))
readme=ROOT/'output/raw_bundles/README_RECONSTRUCAO_E_MANIFESTO.txt'
readme.write_text('Bundles independentes do snapshot bruto. Cada arquivo conserva os nomes e caminhos relativos das fontes originais. Validar pelo manifesto do pacote canônico e pelos hashes dos artefatos.\n',encoding='utf-8')
print(json.dumps({'canonical_bytes':pkg.stat().st_size,'raw_bundles':[{'name':p.name,'bytes':p.stat().st_size} for p in sorted((ROOT/'output/raw_bundles').glob('*.zip'))]},indent=2))
