from __future__ import annotations

import csv
import json
import os
import re
import subprocess
from pathlib import Path

import pandas as pd

os.environ['LOT_ID']='G5-L09'
subprocess.run(['python','mg853-g5-block1/normalize_l05_l09.py'],check=True)
root=Path('mg853-g5-block1/normalized/G5-L09'); out=root/'01_BASE_NORMALIZADA'; aud=root/'02_AUDITORIA'
basep=out/'MG853_G5_L09_BASE_MUNICIPAL_NORMALIZADA_V1_0.csv'
base=pd.read_csv(basep,sep=';',decimal=',',dtype={'cod_ibge_7':str})
monetary=['mcmv_sub_valor_contratado','mcmv_sub_valor_desembolsado','mcmv_fgts_valor_financiamento','mcmv_fgts_valor_subsidio']
for c in monetary: base[c]=pd.to_numeric(base[c],errors='coerce').round(2)
base['versao_transformacao']='G5-L09-NORM-V1.1'
v11=out/'MG853_G5_L09_BASE_MUNICIPAL_NORMALIZADA_V1_1.csv'
base.to_csv(v11,index=False,sep=';',encoding='utf-8-sig',decimal=',')
# Validate the serialized CSV representation, which is the chain-of-custody object promoted to Drive/Sheets.
raw=pd.read_csv(v11,sep=';',dtype=str,encoding='utf-8-sig')
audit=[]; bad_total=0
for c in monetary:
    vals=raw[c].fillna('').astype(str).str.strip()
    bad=vals[(vals!='') & ~vals.str.fullmatch(r'-?\d+(?:,\d{1,2})?')]
    bad_total += len(bad)
    audit.append({'campo':c,'registros':len(vals),'representacao_fora_centavos':len(bad),'status':'APROVADO' if len(bad)==0 else 'FALHA'})
pd.DataFrame(audit).to_csv(aud/'MG853_G5_L09_AUDITORIA_PRECISAO_MONETARIA_V1_1.csv',index=False,sep=';',encoding='utf-8-sig')
# Rebuild long table from final base.
valcols=[c for c in base.columns if c.startswith('mcmv_sub_') or c.startswith('mcmv_fgts_') or c.startswith('snhis_situacao_')]
exclude={'mcmv_sub_data_referencia','mcmv_fgts_data_referencia','mcmv_sub_status_cobertura','mcmv_fgts_status_cobertura'}
long=base.melt(id_vars=['cod_ibge_7','municipio','uf','fonte_id'],value_vars=[c for c in valcols if c not in exclude],var_name='indicador_id',value_name='valor')
long['status_valor']=long.valor.apply(lambda x:'ND' if pd.isna(x) or str(x) in {'ND','NI','ND_CONFLITO_FONTE'} else 'OK')
long.to_csv(out/'MG853_G5_L09_INDICADORES_LONGOS_V1_1.csv',index=False,sep=';',encoding='utf-8-sig',decimal=',')
old=pd.read_csv(aud/'MG853_G5_L09_TESTES_V1_0.csv',sep=';')
newrow={'teste_id':'L09-T17','teste':'PRECISAO_MONETARIA_SERIALIZADA','resultado':bad_total,'esperado':0,'aprovado':'SIM' if bad_total==0 else 'NAO','observacao':'Validação da representação CSV final: quatro campos monetários com no máximo duas casas decimais; evita falso positivo de ponto flutuante.'}
new=pd.concat([old,pd.DataFrame([newrow])],ignore_index=True)
new.to_csv(aud/'MG853_G5_L09_TESTES_V1_1.csv',index=False,sep=';',encoding='utf-8-sig')
summary=json.loads((root/'resumo_execucao.json').read_text(encoding='utf-8'))
summary.update({'versao':'G5-L09-NORM-V1.1','testes_total':17,'testes_aprovados':17 if bad_total==0 else 16,'correcao_v1_1':'Precisão monetária serializada a centavos; teste baseado no artefato CSV final, sem falso positivo de representação binária.','status':'NORMALIZACAO_APROVADA_PARA_REVISAO_NAO_INTEGRADA' if bad_total==0 else 'BLOQUEADO_POR_PRECISAO'})
(root/'resumo_execucao_v1_1.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False,indent=2))
if bad_total: raise SystemExit('Falha na representação monetária serializada')
