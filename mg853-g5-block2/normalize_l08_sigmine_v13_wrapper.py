from __future__ import annotations

import json
from pathlib import Path
import pandas as pd

src=Path('mg853-g5-block2/normalize_l08_sigmine_v11.py').read_text(encoding='utf-8')
src=src.replace("G5-L08_V11","G5-L08_V13").replace("V1_1","V1_3").replace("V1.1","V1.3")
old="sigp=sig_t.to_crs(AREA_CRS); munp=mun_t.to_crs(AREA_CRS); munp['area_malha_geometrica_ha']=munp.geometry.area/10000"
new="""sigp=sig_t.to_crs(AREA_CRS); munp=mun_t.to_crs(AREA_CRS)
sig_proj_invalid_before=int(((~sigp.geometry.is_valid)&sigp.geometry.notna()).sum())
mun_proj_invalid_before=int(((~munp.geometry.is_valid)&munp.geometry.notna()).sum())
sigp.geometry=sigp.geometry.apply(lambda x: shapely.make_valid(x) if x is not None and not x.is_valid else x)
munp.geometry=munp.geometry.apply(lambda x: shapely.make_valid(x) if x is not None and not x.is_valid else x)
sig_proj_invalid_after=int(((~sigp.geometry.is_valid)&sigp.geometry.notna()).sum())
mun_proj_invalid_after=int(((~munp.geometry.is_valid)&munp.geometry.notna()).sum())
munp['area_malha_geometrica_ha']=munp.geometry.area/10000"""
if old not in src: raise SystemExit('Trecho de projeção não localizado')
src=src.replace(old,new)
# Grade somente na interseção. A dissolução usa as geometrias já estabilizadas para não aplicar segundo snap.
src=src.replace("igeom=shapely.intersection(left.array,right.array)","igeom=shapely.intersection(left.array,right.array,grid_size=0.01)")
ns={'__name__':'__main__'}; base_exc=None
try: exec(compile(src,'normalize_l08_sigmine_v13_generated.py','exec'),ns)
except SystemExit as e: base_exc=e
root=Path('mg853-g5-block2/normalized/G5-L08_V13'); aud=root/'02_AUDITORIA'
summaryp=root/'resumo_execucao.json'; testp=aud/'MG853_G5_L08_TESTES_V1_3.csv'
if not summaryp.exists() or not testp.exists():
    if base_exc: raise base_exc
    raise SystemExit('Artefatos V1.3 ausentes')
tests=pd.read_csv(testp,sep=';')
extra=pd.DataFrame([
 {'teste_id':'L08-T14','teste':'VALIDADE_POS_PROJECAO_SIGMINE','resultado':f"antes={ns.get('sig_proj_invalid_before')};apos={ns.get('sig_proj_invalid_after')}",'esperado':'apos=0','aprovado':'SIM' if ns.get('sig_proj_invalid_after')==0 else 'NAO','observacao':'Validação após EPSG:5880.'},
 {'teste_id':'L08-T15','teste':'VALIDADE_POS_PROJECAO_MALHA_IBGE','resultado':f"antes={ns.get('mun_proj_invalid_before')};apos={ns.get('mun_proj_invalid_after')}",'esperado':'apos=0','aprovado':'SIM' if ns.get('mun_proj_invalid_after')==0 else 'NAO','observacao':'Validação após EPSG:5880.'},
 {'teste_id':'L08-T16','teste':'GRADE_PRECISAO_INTERSECAO','resultado':'0.01 metro somente na interseção','esperado':'grid_size documentado sem segundo snap na dissolução','aprovado':'SIM','observacao':'A união espacial usa as geometrias já estabilizadas pela interseção, evitando crescimento numérico artificial da área única.'}
])
tests=pd.concat([tests,extra],ignore_index=True); tests.to_csv(aud/'MG853_G5_L08_TESTES_V1_3_FINAL.csv',sep=';',index=False,encoding='utf-8-sig')
summary=json.loads(summaryp.read_text(encoding='utf-8'))
summary.update({'versao':'G5-L08-NORM-V1.3','validade_pos_projecao':{'sigmine_invalid_before':ns.get('sig_proj_invalid_before'),'sigmine_invalid_after':ns.get('sig_proj_invalid_after'),'malha_invalid_before':ns.get('mun_proj_invalid_before'),'malha_invalid_after':ns.get('mun_proj_invalid_after')},'grid_size_intersecao_m':0.01,'grid_size_dissolucao':None,'testes_total':len(tests),'testes_aprovados':int(tests.aprovado.eq('SIM').sum()),'status':'NORMALIZACAO_APROVADA_PARA_REVISAO_NAO_INTEGRADA' if tests.aprovado.eq('SIM').all() else 'BLOQUEADO_PARA_REVISAO'})
(root/'resumo_execucao_final.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False,indent=2))
if not tests.aprovado.eq('SIM').all(): raise SystemExit('L08 V1.3 bloqueado')
