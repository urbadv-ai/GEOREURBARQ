from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pandas as pd

os.environ['LOT_ID']='G5-L09'
subprocess.run(['python','mg853-g5-block1/normalize_l05_l09.py'],check=True)
root=Path('mg853-g5-block1/normalized/G5-L09')
out=root/'01_BASE_NORMALIZADA'
aud=root/'02_AUDITORIA'
basep=out/'MG853_G5_L09_BASE_MUNICIPAL_NORMALIZADA_V1_0.csv'
base=pd.read_csv(basep,sep=';',decimal=',',dtype={'cod_ibge_7':str})
monetary=['mcmv_sub_valor_contratado','mcmv_sub_valor_desembolsado','mcmv_fgts_valor_financiamento','mcmv_fgts_valor_subsidio']
for c in monetary:
    base[c]=pd.to_numeric(base[c],errors='coerce').round(2)
# v1.1 metadata and outputs
base['versao_transformacao']='G5-L09-NORM-V1.1'
base_v11=out/'MG853_G5_L09_BASE_MUNICIPAL_NORMALIZADA_V1_1.csv'
base.to_csv(base_v11,index=False,sep=';',encoding='utf-8-sig',decimal=',')
valcols=[c for c in base.columns if c.startswith('mcmv_sub_') or c.startswith('mcmv_fgts_') or c.startswith('snhis_situacao_')]
idvars=['cod_ibge_7','municipio','uf','fonte_id']
long=base.melt(id_vars=idvars,value_vars=[c for c in valcols if c not in {'mcmv_sub_data_referencia','mcmv_fgts_data_referencia','mcmv_sub_status_cobertura','mcmv_fgts_status_cobertura'}],var_name='indicador_id',value_name='valor')
long['status_valor']=long.valor.apply(lambda x:'ND' if pd.isna(x) or str(x) in {'ND','NI','ND_CONFLITO_FONTE'} else 'OK')
long.to_csv(out/'MG853_G5_L09_INDICADORES_LONGOS_V1_1.csv',index=False,sep=';',encoding='utf-8-sig',decimal=',')
# precision audit
rows=[]; errors=0
for c in monetary:
    s=base[c].dropna()
    bad=((s*100).round(0)-(s*100)).abs()>1e-6
    n=int(bad.sum()); errors+=n; rows.append({'campo':c,'registros_numericos':len(s),'fora_centavos':n,'status':'APROVADO' if n==0 else 'FALHA'})
pd.DataFrame(rows).to_csv(aud/'MG853_G5_L09_AUDITORIA_PRECISAO_MONETARIA_V1_1.csv',index=False,sep=';',encoding='utf-8-sig')
# append test without altering v1.0 history
old=pd.read_csv(aud/'MG853_G5_L09_TESTES_V1_0.csv',sep=';')
new=pd.concat([old,pd.DataFrame([{'teste_id':'L09-T17','teste':'PRECISAO_MONETARIA_CENTAVOS','resultado':errors,'esperado':0,'aprovado':'SIM' if errors==0 else 'NAO','observacao':'Quatro campos monetários explicitamente arredondados a centavos para impedir artefatos binários/locale em exportações.'}])],ignore_index=True)
new.to_csv(aud/'MG853_G5_L09_TESTES_V1_1.csv',index=False,sep=';',encoding='utf-8-sig')
summary=json.loads((root/'resumo_execucao.json').read_text(encoding='utf-8'))
summary.update({'versao':'G5-L09-NORM-V1.1','testes_total':17,'testes_aprovados':17 if errors==0 else 16,'correcao_v1_1':'Precisão monetária explícita a centavos para exportação e Google Sheets; nenhum valor-fonte alterado além da representação centesimal correspondente à unidade monetária.','status':'NORMALIZACAO_APROVADA_PARA_REVISAO_NAO_INTEGRADA' if errors==0 else 'BLOQUEADO_POR_PRECISAO'})
(root/'resumo_execucao_v1_1.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False,indent=2))
if errors: raise SystemExit('Falha na auditoria de precisão monetária')
