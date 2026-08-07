from __future__ import annotations

import argparse, json, re, zipfile
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests
import shapely

MUN_URL='https://geoftp.ibge.gov.br/organizacao_do_territorio/malhas_territoriais/malhas_municipais/municipio_2025/UFs/MG/MG_Municipios_2025.zip'
AREA_CRS='EPSG:5880'
LAYERS=[
('L07-G1-UC','UC_AREAS_PROTEGIDAS','IDE:ide_2010_mg_unidades_conservacao_municipais_pol','municipal'),
('L07-G1-UC','UC_AREAS_PROTEGIDAS','IDE:ide_2010_mg_unidades_conservacao_estaduais_pol','estadual'),
('L07-G1-UC','UC_AREAS_PROTEGIDAS','IDE:ide_2010_mg_unidades_conservacao_federais_pol','federal'),
('L07-G2-CH','HIDROGRAFIA_RECURSOS_HIDRICOS','IDE:ide_1108_mg_circunscricoes_hidrograficas_pol','ch'),
('L07-G3-RH-REST','RESTRICOES_CONDICIONANTES','IDE:ide_2007_mg_restricao_contole_rh_sub_pol','restricao_hidrica'),
('L07-G4-ACR','AREAS_CONTAMINADAS_PASSIVOS','IDE:ide_1902_mg_areas_contaminadas_reabilitadas_pto','contaminadas'),
('L07-G5-USO','USO_COBERTURA','IDE:ide_210603_mg_uso_cobertura_mapcar_area1_pol','fip_area1'),
('L07-G5-USO','USO_COBERTURA','IDE:ide_210603_mg_uso_cobertura_mapcar_area2_pol','fip_area2'),
('L07-G5-USO','USO_COBERTURA','IDE:ide_210603_mg_uso_cobertura_mapcar_area3_pol','fip_area3'),
('L07-G5-USO','USO_COBERTURA','IDE:ide_210603_mg_uso_cobertura_mapcar_area4_pol','fip_area4'),
('L07-G5-USO','USO_COBERTURA','IDE:ide_210603_mg_uso_cobertura_mapcar_area5_pol','fip_area5'),
('L07-G5-USO','USO_COBERTURA','IDE:ide_210603_mg_uso_cobertura_mapcar_area6_pol','fip_area6'),
('L07-G5-USO','USO_COBERTURA','IDE:ide_210603_mg_uso_cobertura_mapcar_area7_pol','fip_area7'),
('L07-G5-USO','USO_COBERTURA','IDE:ide_210603_mg_uso_cobertura_mapcar_area8_pol','fip_area8'),
('L07-G5-USO','USO_COBERTURA','IDE:ide_210603_mg_uso_cobertura_mapcar_area9_pol','fip_area9'),
('L07-G5-USO','USO_COBERTURA','IDE:ide_210603_mg_uso_cobertura_mapcar_area10_pol','fip_area10'),
('L07-G5-USO','USO_COBERTURA','IDE:ide_210603_mg_uso_cobertura_mapcar_area11_pol','fip_area11'),
('L07-G5-USO','USO_COBERTURA','IDE:ide_210603_mg_uso_cobertura_mapcar_area12_pol','fip_area12'),
('L07-G5-USO','USO_COBERTURA','IDE:ide_210603_mg_uso_cobertura_mapcar_area13_pol','fip_area13'),
]

def now(): return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
def write_csv(df,p): df.to_csv(p,index=False,sep=';',encoding='utf-8-sig',decimal=',')

def extract_nested(source:Path, work:Path):
    outer=list(source.rglob('*.zip'))
    if not outer: raise RuntimeError('Artifact ZIP ausente')
    # Find the nested component package, then its raw_wfs_shape.zip.
    for z in outer:
        try:
            with zipfile.ZipFile(z) as zz:
                if any(n.endswith('raw_wfs_shape.zip') for n in zz.namelist()):
                    zz.extractall(work/'component');
                    raw=list((work/'component').rglob('raw_wfs_shape.zip'))
                    if raw: return raw[0]
        except zipfile.BadZipFile: pass
    # The downloaded artifact may itself already be extracted by gh.
    raw=list(source.rglob('raw_wfs_shape.zip'))
    if raw: return raw[0]
    raise RuntimeError('raw_wfs_shape.zip nao localizado')

def read_shp_zip(zp:Path, work:Path):
    d=work/'shape'; d.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(zp) as z: z.extractall(d)
    shps=list(d.rglob('*.shp'))
    if not shps: raise RuntimeError('SHP ausente')
    return gpd.read_file(shps[0])

def get_mun(work:Path):
    z=work/'MG_Municipios_2025.zip'
    if not z.exists():
        r=requests.get(MUN_URL,timeout=(20,300)); r.raise_for_status(); z.write_bytes(r.content)
    d=work/'mun'; d.mkdir(exist_ok=True)
    if not list(d.rglob('*.shp')):
        with zipfile.ZipFile(z) as zz: zz.extractall(d)
    shp=list(d.rglob('*.shp'))[0]
    m=gpd.read_file(shp)
    if m.crs is None: raise RuntimeError('CRS malha ausente')
    if m.crs.to_epsg()!=4674: m=m.to_crs(4674)
    code=next((c for c in m.columns if c.upper() in {'CD_MUN','CD_GEOCMU','CD_MUNICIP','CD_MUNICIPIO'} or ('CD_' in c.upper() and 'MUN' in c.upper())),None)
    name=next((c for c in m.columns if c.upper() in {'NM_MUN','NM_MUNICIP','NM_MUNICIPIO'} or ('NM_' in c.upper() and 'MUN' in c.upper())),None)
    if not code: raise RuntimeError('Chave municipal ausente')
    m['cod_ibge_7']=m[code].astype(str).str.extract(r'(\d{7})',expand=False)
    m['municipio']=m[name].astype(str) if name else ''
    m=m[['cod_ibge_7','municipio','geometry']].drop_duplicates('cod_ibge_7')
    if len(m)!=853 or m.cod_ibge_7.nunique()!=853: raise RuntimeError(f'Malha invalida: {len(m)}')
    return m

def repair(g:gpd.GeoDataFrame):
    x=g.copy().reset_index(drop=True)
    x.geometry=x.geometry.apply(lambda v: shapely.force_2d(v) if v is not None else None)
    bad=(~x.geometry.is_valid)&x.geometry.notna()
    before=int(bad.sum())
    if before: x.loc[bad,'geometry']=x.loc[bad,'geometry'].apply(shapely.make_valid)
    after=int(((~x.geometry.is_valid)&x.geometry.notna()).sum())
    return x,before,after

def polygon_intersections(src,munp,class_col=None):
    # src and munp projected to AREA_CRS and valid.
    pairs=gpd.sjoin(src,munp[['cod_ibge_7','municipio','geometry']],how='inner',predicate='intersects')
    if pairs.empty: return pairs
    left=pairs.geometry.reset_index(drop=True)
    right=munp.geometry.reindex(pairs['index_right'].to_numpy()).reset_index(drop=True)
    geom=shapely.intersection(left.array,right.array,grid_size=0.01)
    area=shapely.area(geom)/10000
    keep=(~shapely.is_empty(geom)) & (area>0)
    p=pairs.reset_index(drop=True).loc[keep].copy()
    p['geometry']=geom[keep]; p['area_ha']=area[keep]
    return gpd.GeoDataFrame(p,geometry='geometry',crs=AREA_CRS)

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--index',type=int,required=True); ap.add_argument('--source-dir',default='source_component'); args=ap.parse_args()
    idx=args.index; logical,group,layer,tag=LAYERS[idx]
    root=Path('normalized_l07_components')/f'{idx:02d}_{tag}'; root.mkdir(parents=True,exist_ok=True)
    work=root/'work'; work.mkdir(exist_ok=True)
    raw=extract_nested(Path(args.source_dir),work)
    src=read_shp_zip(raw,work)
    source_rows=len(src); source_crs=str(src.crs); source_epsg=src.crs.to_epsg() if src.crs else None
    if src.crs is None: raise RuntimeError('CRS fonte ausente')
    if source_epsg!=4674: src=src.to_crs(4674)
    src,bad0,bad1=repair(src)
    mun=get_mun(work); mun,badm0,badm1=repair(mun)
    srcp=src.to_crs(AREA_CRS); munp=mun.to_crs(AREA_CRS)
    badproj=int(((~srcp.geometry.is_valid)&srcp.geometry.notna()).sum())
    if badproj:
        srcp.loc[(~srcp.geometry.is_valid)&srcp.geometry.notna(),'geometry']=srcp.loc[(~srcp.geometry.is_valid)&srcp.geometry.notna(),'geometry'].apply(shapely.make_valid)
    badproj_after=int(((~srcp.geometry.is_valid)&srcp.geometry.notna()).sum())
    if bad1 or badm1 or badproj_after: raise RuntimeError('Geometria invalida apos reparo')
    munp['area_municipal_geom_ha']=munp.geometry.area/10000

    contribution=None; long=None; extra={}
    if idx<=4 or idx>=6:
        class_col='classe_' if idx>=6 and 'classe_' in srcp.columns else None
        inter=polygon_intersections(srcp,munp,class_col)
        if idx in (0,1,2):
            # Unique area per municipality within each sphere; overlaps between UCs of same sphere dissolved.
            vals=[]
            for code,m in munp.set_index('cod_ibge_7').iterrows():
                g=inter[inter.cod_ibge_7.eq(code)]
                area=float(shapely.area(shapely.union_all(g.geometry.array))/10000) if len(g) else 0.0
                vals.append({'cod_ibge_7':code,'municipio':m.municipio,f'uc_{tag}_presenca':int(len(g)>0),f'uc_{tag}_feicoes':int(g.index.nunique()),f'uc_{tag}_area_unica_ha':area,'area_municipal_geom_ha':float(m.area_municipal_geom_ha)})
            contribution=pd.DataFrame(vals); contribution[f'uc_{tag}_pct_area']=100*contribution[f'uc_{tag}_area_unica_ha']/contribution.area_municipal_geom_ha
            attrs=[c for c in ['nome','nm_uc','categoria','grupo','bioma','municipio','ato_legal'] if c in inter.columns]
            if attrs:
                long=inter[['cod_ibge_7','area_ha']+attrs].copy()
        elif idx==3:
            sig=next((c for c in inter.columns if c.lower() in {'sigla','sigla_ch'}),None)
            nome=next((c for c in inter.columns if c.lower() in {'nome','nm_ch','nome_ch'}),None)
            key=sig or nome
            if key:
                lg=inter.groupby(['cod_ibge_7',key],dropna=False).area_ha.sum().reset_index()
                long=lg
                principal=lg.sort_values(['cod_ibge_7','area_ha'],ascending=[True,False]).drop_duplicates('cod_ibge_7').rename(columns={key:'ch_principal','area_ha':'ch_principal_area_ha'})
                cnt=lg.groupby('cod_ibge_7')[key].nunique(dropna=True).rename('ch_quantidade_intersectante').reset_index()
                contribution=munp[['cod_ibge_7','municipio']].drop(columns='geometry',errors='ignore').merge(cnt,on='cod_ibge_7',how='left').merge(principal[['cod_ibge_7','ch_principal','ch_principal_area_ha']],on='cod_ibge_7',how='left')
                contribution.ch_quantidade_intersectante=contribution.ch_quantidade_intersectante.fillna(0).astype(int)
                contribution['ch_presenca']=(contribution.ch_quantidade_intersectante>0).astype(int)
            else: raise RuntimeError('Campo CH nao identificado')
        elif idx==4:
            vals=[]
            for code,m in munp.set_index('cod_ibge_7').iterrows():
                g=inter[inter.cod_ibge_7.eq(code)]
                area=float(shapely.area(shapely.union_all(g.geometry.array))/10000) if len(g) else 0.0
                vals.append({'cod_ibge_7':code,'municipio':m.municipio,'restricao_hidrica_presenca':int(len(g)>0),'restricao_hidrica_area_unica_ha':area,'area_municipal_geom_ha':float(m.area_municipal_geom_ha)})
            contribution=pd.DataFrame(vals); contribution['restricao_hidrica_pct_area']=100*contribution.restricao_hidrica_area_unica_ha/contribution.area_municipal_geom_ha
            attrs=[c for c in ['setor','portigam','numdarc','nomtrecho','municipio','ch','area_km2'] if c in inter.columns]
            if attrs: long=inter[['cod_ibge_7','area_ha']+attrs].copy()
        else:
            if 'classe_' not in inter.columns: raise RuntimeError('Campo classe_ ausente no FIP-CAR')
            long=inter.groupby(['cod_ibge_7','classe_'],dropna=False).area_ha.sum().reset_index()
            tot=long.groupby('cod_ibge_7').area_ha.sum().rename(f'{tag}_area_mapeada_ha').reset_index()
            contribution=munp[['cod_ibge_7','municipio','area_municipal_geom_ha']].drop(columns='geometry',errors='ignore').merge(tot,on='cod_ibge_7',how='left')
            contribution[f'{tag}_area_mapeada_ha']=contribution[f'{tag}_area_mapeada_ha'].fillna(0.0)
            contribution[f'{tag}_pct_mapeado']=100*contribution[f'{tag}_area_mapeada_ha']/contribution.area_municipal_geom_ha
            extra['classes']=sorted([str(x) for x in long.classe_.dropna().unique()])
            extra['intersections']=len(inter)
    else:
        # Point layer: within first, intersects fallback. Points on exact border may match >1; retain ambiguity for audit.
        pts=srcp
        pairs=gpd.sjoin(pts,munp[['cod_ibge_7','municipio','geometry']],how='left',predicate='within')
        unresolved=pairs.cod_ibge_7.isna()
        if unresolved.any():
            fb=gpd.sjoin(pts.loc[unresolved.values],munp[['cod_ibge_7','municipio','geometry']],how='left',predicate='intersects')
            pairs=pairs.loc[~unresolved].copy(); pairs=pd.concat([pairs,fb],ignore_index=True)
        class_col=next((c for c in pairs.columns if c.lower() in {'classif','classificacao','classific'}),None)
        assigned=pairs[pairs.cod_ibge_7.notna()].copy()
        base=assigned.groupby('cod_ibge_7').size().rename('acr_pontos_total').reset_index()
        contribution=munp[['cod_ibge_7','municipio']].drop(columns='geometry',errors='ignore').merge(base,on='cod_ibge_7',how='left')
        contribution.acr_pontos_total=contribution.acr_pontos_total.fillna(0).astype(int); contribution['acr_presenca']=(contribution.acr_pontos_total>0).astype(int)
        if class_col:
            long=assigned.groupby(['cod_ibge_7',class_col],dropna=False).size().rename('quantidade').reset_index().rename(columns={class_col:'classificacao_oficial'})
        extra['pontos_sem_municipio']=int(pairs.cod_ibge_7.isna().sum())
        extra['pontos_duplicados_por_fronteira']=int(pairs.index.duplicated().sum())

    contribution['fonte_id']='F-006'; contribution['lote_id']='G5-L07'; contribution['componente_idx']=idx; contribution['componente_tag']=tag; contribution['data_extracao']=now(); contribution['versao_transformacao']='G5-L07-NORM-COMP-V1.0'
    write_csv(contribution,root/'contribuicao_municipal.csv')
    if long is not None: write_csv(long,root/'tabela_longa.csv')
    audit={'idx':idx,'logical_id':logical,'grupo':group,'layer_name':layer,'tag':tag,'source_rows':source_rows,'source_crs':source_crs,'source_epsg':source_epsg,'invalid_source_before':bad0,'invalid_source_after':bad1,'invalid_projected_before':badproj,'invalid_projected_after':badproj_after,'municipios':int(contribution.cod_ibge_7.nunique()),'linhas_contribuicao':len(contribution),'extra':extra,'status':'APROVADO' if contribution.cod_ibge_7.nunique()==853 and len(contribution)==853 else 'BLOQUEADO','regra_semantica':'Componente contextual; nenhuma métrica representa desempenho, regularidade jurídica, dano ou risco por si só.'}
    (root/'auditoria_componente.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(audit,ensure_ascii=False,indent=2))
    if audit['status']!='APROVADO': raise SystemExit(2)

if __name__=='__main__': main()
