from __future__ import annotations

import csv, json, re, sys, zipfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

EXPECTED={
0:195,1:95,2:95,3:43,4:4,5:766,6:202498,7:178698,8:198579,9:134024,
10:111180,11:158078,12:120455,13:174655,14:121833,15:181093,16:143075,17:123135,18:189117,
}
OUT=Path('out_l07_consolidated'); OUT.mkdir(exist_ok=True)

def now(): return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
def read_csv(p): return pd.read_csv(p,sep=';',decimal=',',encoding='utf-8-sig',dtype={'cod_ibge_7':str},low_memory=False)
def write_csv(df,p): df.to_csv(p,index=False,sep=';',decimal=',',encoding='utf-8-sig')

def unzip_all(root:Path):
    dest=Path('unpacked_l07'); dest.mkdir(exist_ok=True)
    for z in sorted(root.rglob('*.zip')):
        d=dest/z.stem; d.mkdir(exist_ok=True)
        try:
            with zipfile.ZipFile(z) as zz: zz.extractall(d)
        except zipfile.BadZipFile: pass
    # Some gh downloads may already be directories or contain nested zip. Iterate twice.
    for z in sorted(dest.rglob('*.zip')):
        d=z.parent/(z.stem+'_inner'); d.mkdir(exist_ok=True)
        try:
            with zipfile.ZipFile(z) as zz: zz.extractall(d)
        except zipfile.BadZipFile: pass
    return dest

def find_component(root,idx):
    audit_candidates=[]
    for p in root.rglob('auditoria_componente.json'):
        try:
            j=json.loads(p.read_text(encoding='utf-8'))
            if int(j.get('idx',-1))==idx: audit_candidates.append((p,j))
        except Exception: pass
    if not audit_candidates: raise RuntimeError(f'idx {idx}: auditoria ausente')
    # Prefer APPROVED candidate; current workflow artifact should contain one.
    audit_candidates.sort(key=lambda x: x[1].get('status')=='APROVADO',reverse=True)
    ap,a=audit_candidates[0]
    base=ap.parent
    cp=base/'contribuicao_municipal.csv'
    lp=base/'tabela_longa.csv'
    if not cp.exists(): raise RuntimeError(f'idx {idx}: contribuicao ausente')
    return a,read_csv(cp),(read_csv(lp) if lp.exists() else None),ap

def canonical_metadata_drop(df):
    return df.drop(columns=['fonte_id','lote_id','componente_idx','componente_tag','data_extracao','versao_transformacao'],errors='ignore')

def main():
    root=unzip_all(Path('normalized_inputs'))
    audits=[]; contrib={}; longs={}; errors=[]
    for idx in range(19):
        try:
            a,c,l,ap=find_component(root,idx)
            audits.append(a); contrib[idx]=c; longs[idx]=l
        except Exception as e:
            errors.append(str(e))
    if errors:
        (OUT/'erros_consolidacao.txt').write_text('\n'.join(errors),encoding='utf-8')
        raise SystemExit(2)

    # Input QA.
    audit_df=pd.DataFrame(audits).sort_values('idx')
    write_csv(audit_df,OUT/'auditoria_19_componentes.csv')
    tests=[]
    def test(name,ok,detail): tests.append({'teste':name,'resultado':'APROVADO' if ok else 'FALHOU','detalhe':detail})
    test('19_AUDITORIAS_LOCALIZADAS',len(audits)==19,f'{len(audits)}/19')
    test('19_STATUS_APROVADO',all(a.get('status')=='APROVADO' for a in audits),str({a['idx']:a.get('status') for a in audits if a.get('status')!='APROVADO'}))
    test('CARDINALIDADE_FONTE_CONGELADA',all(int(a.get('source_rows',-1))==EXPECTED[int(a['idx'])] for a in audits),str({a['idx']:(a.get('source_rows'),EXPECTED[int(a['idx'])]) for a in audits if int(a.get('source_rows',-1))!=EXPECTED[int(a['idx'])]}))
    test('FIP_TOTAL_FONTE',sum(EXPECTED[i] for i in range(6,19))==2036420,str(sum(EXPECTED[i] for i in range(6,19))))
    for idx,c in contrib.items():
        test(f'IDX{idx:02d}_853_LINHAS',len(c)==853,str(len(c)))
        test(f'IDX{idx:02d}_853_CHAVES',c.cod_ibge_7.nunique()==853,str(c.cod_ibge_7.nunique()))
        test(f'IDX{idx:02d}_PREFIXO31',c.cod_ibge_7.str.match(r'^31\d{5}$').all(),'validacao regex')
    base=canonical_metadata_drop(contrib[0]).copy()
    # Keep canonical municipality and area geometry from idx0.
    base_cols=['cod_ibge_7','municipio']+[c for c in base.columns if c not in ('cod_ibge_7','municipio')]
    base=base[base_cols]
    keys=set(base.cod_ibge_7)
    for idx in range(1,6):
        c=canonical_metadata_drop(contrib[idx]).copy()
        test(f'IDX{idx:02d}_MESMO_UNIVERSO',set(c.cod_ibge_7)==keys,'comparacao de conjunto de cod_ibge_7')
        c=c.drop(columns=['municipio','area_municipal_geom_ha'],errors='ignore')
        dup=[x for x in c.columns if x!='cod_ibge_7' and x in base.columns]
        if dup: c=c.rename(columns={x:f'idx{idx}_{x}' for x in dup})
        base=base.merge(c,on='cod_ibge_7',how='left',validate='one_to_one')

    # FIP-CAR: one logical mosaic, 13 regional components. Aggregate class areas, not 13 indicators.
    fip_longs=[]; fip_totals=[]
    for idx in range(6,19):
        l=longs[idx]
        if l is None or 'classe_' not in l.columns or 'area_ha' not in l.columns:
            test(f'IDX{idx:02d}_FIP_LONGA',False,'classe_/area_ha ausente')
            continue
        l=l[['cod_ibge_7','classe_','area_ha']].copy(); l['componente_idx']=idx; fip_longs.append(l)
        c=contrib[idx]
        area_col=next((x for x in c.columns if x.endswith('_area_mapeada_ha')),None)
        if not area_col:
            test(f'IDX{idx:02d}_FIP_AREA_COL',False,'area_mapeada_ha ausente')
        else:
            fip_totals.append(c[['cod_ibge_7',area_col]].rename(columns={area_col:'area_ha'}).assign(componente_idx=idx))
    fip=pd.concat(fip_longs,ignore_index=True)
    fip_by_class=fip.groupby(['cod_ibge_7','classe_'],dropna=False,as_index=False).area_ha.sum()
    write_csv(fip_by_class,OUT/'MG853_G5_L07_FIP_CAR_AREA_POR_CLASSE_LONGA_V1_0.csv')
    classes=sorted(str(x) for x in fip_by_class.classe_.dropna().unique())
    pivot=fip_by_class.pivot_table(index='cod_ibge_7',columns='classe_',values='area_ha',aggfunc='sum',fill_value=0).reset_index()
    pivot.columns=['cod_ibge_7']+[f'fip_area_{re.sub(r"[^a-z0-9]+","_",str(x).lower()).strip("_")}_ha' for x in pivot.columns[1:]]
    fipt=pd.concat(fip_totals,ignore_index=True).groupby('cod_ibge_7',as_index=False).area_ha.sum().rename(columns={'area_ha':'fip_area_mapeada_soma_componentes_ha'})
    fipbase=base[['cod_ibge_7','area_municipal_geom_ha']].merge(fipt,on='cod_ibge_7',how='left').merge(pivot,on='cod_ibge_7',how='left')
    fipbase['fip_area_mapeada_soma_componentes_ha']=fipbase['fip_area_mapeada_soma_componentes_ha'].fillna(0)
    fipbase['fip_pct_cobertura_geometrica_soma_componentes']=100*fipbase.fip_area_mapeada_soma_componentes_ha/fipbase.area_municipal_geom_ha
    fipbase['fip_status_cobertura']=fipbase.fip_pct_cobertura_geometrica_soma_componentes.apply(lambda x:'SOBREPOSICAO_OU_DIVERGENCIA_REVISAR' if x>100.5 else ('COM_INTERSECAO_FIP' if x>0 else 'SEM_INTERSECAO_FIP_NAO_INTERPRETAR_COMO_AUSENCIA_MATERIAL'))
    over=fipbase[fipbase.fip_pct_cobertura_geometrica_soma_componentes>100.5]
    test('FIP_SEM_SOBRECOBERTURA_RELEVANTE',len(over)==0,f'{len(over)} municipios >100,5%; max={fipbase.fip_pct_cobertura_geometrica_soma_componentes.max():.6f}')
    test('FIP_AREAS_NAO_NEGATIVAS',(fip_by_class.area_ha>=0).all(),'area_ha >= 0')
    test('FIP_13_COMPONENTES_PRESENTES',len(fip_longs)==13,str(len(fip_longs)))
    base=base.merge(fipbase.drop(columns=['area_municipal_geom_ha']),on='cod_ibge_7',how='left',validate='one_to_one')

    # Final metadata / semantic status.
    base['fonte_id_l07']='F-006'; base['lote_id_l07']='G5-L07'; base['data_extracao_l07']=now(); base['versao_transformacao_l07']='G5-L07-V1.0'
    base['natureza_l07']='CONTEXTUAL_NAO_PONTUAR_AUTOMATICAMENTE'
    base['regra_semantica_l07']='Presenca/cobertura/area ambiental nao equivale a desempenho, conformidade juridica, dano ou risco por si so.'
    test('BASE_FINAL_853',len(base)==853,str(len(base)))
    test('BASE_FINAL_853_UNICOS',base.cod_ibge_7.nunique()==853,str(base.cod_ibge_7.nunique()))
    test('BASE_FINAL_ZERO_ANTI_JOIN',set(base.cod_ibge_7)==keys,'universo preservado')
    test('NENHUMA_COLUNA_DE_SCORE',not any(re.search(r'(^|_)score($|_)|pontuacao|ranking',c,re.I) for c in base.columns),'camada contextual')
    write_csv(base,OUT/'MG853_G5_L07_BASE_MUNICIPAL_NORMALIZADA_V1_0.csv')

    # Long tables useful for audit.
    for idx in range(0,6):
        if longs[idx] is not None: write_csv(longs[idx],OUT/f'MG853_G5_L07_IDX{idx:02d}_TABELA_LONGA_V1_0.csv')

    tdf=pd.DataFrame(tests); write_csv(tdf,OUT/'MG853_G5_L07_TESTES_CONSOLIDACAO_V1_0.csv')
    critical_fail=tdf[tdf.resultado.eq('FALHOU')]
    # Overcoverage is a blocker for claiming exact FIP coverage, but other contextual groups may remain valid. For V1.0 promotion require none.
    status='APROVADO' if critical_fail.empty else 'BLOQUEADO_QA'
    summary={
      'lote_id':'G5-L07','versao':'V1.0','data_hora_utc':now(),'componentes':19,'grupos_logicos':5,
      'fip_componentes':13,'fip_source_features':2036420,'fip_classes':classes,
      'municipios':int(base.cod_ibge_7.nunique()),'colunas_base':len(base.columns),
      'testes_total':len(tdf),'testes_aprovados':int(tdf.resultado.eq('APROVADO').sum()),'testes_falhos':int(tdf.resultado.eq('FALHOU').sum()),
      'fip_municipios_sobrecobertura_gt_100_5':int(len(over)),'fip_max_pct_soma_componentes':float(fipbase.fip_pct_cobertura_geometrica_soma_componentes.max()),
      'status':status,
      'nota':'FIP-CAR e um unico mosaico logico. A soma regional somente e aceita como cobertura estadual se o QA nao identificar sobreposicao relevante; nenhuma porcentagem e truncada a 100.',
    }
    (OUT/'RESUMO_EXECUCAO_G5_L07_V1_0.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    # Dictionary.
    rows=[]
    for c in base.columns:
        rows.append({'campo':c,'tipo':'texto' if base[c].dtype=='object' else 'numerico','fonte':'F-006/IBGE malha 2025 para denominador geometrico quando aplicavel','unidade':'ha ou % conforme sufixo; categorias quando textual','natureza':'CONTEXTUAL','regra':'Nao converter cobertura/presenca em desempenho; consultar tabelas longas para classes e atributos.'})
    write_csv(pd.DataFrame(rows),OUT/'MG853_G5_L07_DICIONARIO_V1_0.csv')
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    if status!='APROVADO': sys.exit(3)

if __name__=='__main__': main()
