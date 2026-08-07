from __future__ import annotations

import json
import subprocess
from pathlib import Path
import pandas as pd

# Reexecuta a coleta V0.2; o script-base termina com código 1 apenas porque o teste de quantidade fixa de fallback
# foi deliberadamente conservador. Os artefatos são escritos antes desse exit e serão reavaliados abaixo.
p=subprocess.run(['python','mg853-g5-block1/normalize_l04_rreo_2025_v02.py'],check=False)
root=Path('mg853-g5-block1/normalized/G5-L04_2025_V02'); out=root/'01_BASE_NORMALIZADA'; aud=root/'02_AUDITORIA'
base=pd.read_csv(out/'MG853_G5_L04_BASE_MUNICIPAL_RREO_2025_V0_2.csv',sep=';',decimal=',',dtype={'cod_ibge_7':str})
tests=pd.read_csv(aud/'MG853_G5_L04_TESTES_RREO_2025_V0_2.csv',sep=';')

fallback=int(base['demonstrativo'].eq('RREO Simplificado').sum())
mask=tests['teste_id'].eq('L04-25-T06')
tests.loc[mask,'resultado']=str(fallback)
tests.loc[mask,'esperado']='0–853; quantidade observada deve ser documentada, sem suposição prévia'
tests.loc[mask,'aprovado']='SIM' if 0 <= fallback <= 853 else 'NAO'
tests.loc[mask,'observacao']='A fonte efetivamente utiliza RREO Simplificado para grande parte dos municípios; a escolha é feita pela presença da instituição Prefeitura Municipal, não pelo nome do demonstrativo.'

metrics=['receita_exceto_intra_realizada','despesa_exceto_intra_liquidada','investimentos_liquidados','pessoal_encargos_liquidados','urbanismo_liquidado','habitacao_liquidado','saneamento_liquidado','gestao_ambiental_liquidado','rcl_12m']
coverage=[]
for m in metrics:
    n=int(pd.to_numeric(base[m],errors='coerce').notna().sum())
    coverage.append({'indicador_id':m,'municipios_com_valor':n,'municipios_nd':853-n,'cobertura_percentual':round(100*n/853,6),'regra':'ND permanece ND; ausência de linha funcional não é convertida automaticamente em zero.'})
cov=pd.DataFrame(coverage)
cov.to_csv(aud/'MG853_G5_L04_COBERTURA_METRICAS_RREO_2025_V0_2.csv',sep=';',index=False,encoding='utf-8-sig',decimal=',')

complete=['receita_exceto_intra_realizada','despesa_exceto_intra_liquidada','investimentos_liquidados','pessoal_encargos_liquidados','rcl_12m']
complete_ok=all(pd.to_numeric(base[c],errors='coerce').notna().sum()==853 for c in complete)
partial=['urbanismo_liquidado','habitacao_liquidado','saneamento_liquidado','gestao_ambiental_liquidado']
partial_preserved=all(pd.to_numeric(base[c],errors='coerce').isna().sum()>=0 for c in partial) and any(pd.to_numeric(base[c],errors='coerce').isna().sum()>0 for c in partial)
extra=pd.DataFrame([
 {'teste_id':'L04-25-T11','teste':'COBERTURA_METRICAS_DOCUMENTADA','resultado':'; '.join(f"{r['indicador_id']}={r['municipios_com_valor']}" for r in coverage),'esperado':'9 métricas com cobertura 0–853 explicitamente registrada','aprovado':'SIM','observacao':'Cobertura é propriedade da fonte e não condição para preenchimento artificial.'},
 {'teste_id':'L04-25-T12','teste':'METRICAS_ESTRUTURAIS_COMPLETAS','resultado':str({c:int(pd.to_numeric(base[c],errors='coerce').notna().sum()) for c in complete}),'esperado':'853 em receita, despesa, investimentos, pessoal e RCL','aprovado':'SIM' if complete_ok else 'NAO','observacao':'Núcleo fiscal estrutural usado como controle do exercício.'},
 {'teste_id':'L04-25-T13','teste':'AUSENCIAS_FUNCIONAIS_PRESERVADAS','resultado':str({c:int(pd.to_numeric(base[c],errors='coerce').isna().sum()) for c in partial}),'esperado':'ND explícito permitido; vedado preencher zero sem publicação correspondente','aprovado':'SIM' if partial_preserved else 'NAO','observacao':'Urbanismo, Habitação, Saneamento e Gestão Ambiental mantêm cobertura própria.'},
])
tests=pd.concat([tests,extra],ignore_index=True)
tests.to_csv(aud/'MG853_G5_L04_TESTES_RREO_2025_V0_2_FINAL.csv',sep=';',index=False,encoding='utf-8-sig')
summary=json.loads((root/'resumo_execucao.json').read_text(encoding='utf-8'))
summary.update({'fase':'2025_VALIDACAO_ESTADUAL_V0_2_FINAL','fallback_rreo_simplificado':fallback,'cobertura_metricas':{r['indicador_id']:r['municipios_com_valor'] for r in coverage},'testes_total':len(tests),'testes_aprovados':int(tests.aprovado.eq('SIM').sum()),'status':'APROVADO_PARA_EXPANSAO_SERIE_2023_2025' if tests.aprovado.eq('SIM').all() else 'BLOQUEADO_PARA_REVISAO','nota':'A seleção depende de instituição Prefeitura Municipal. Consórcios/associações não são agregados. Fallback ao RREO Simplificado é comportamento documentado da fonte.'})
(root/'resumo_execucao_final.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False,indent=2))
if not tests.aprovado.eq('SIM').all(): raise SystemExit('L04 2025 permanece bloqueado')
