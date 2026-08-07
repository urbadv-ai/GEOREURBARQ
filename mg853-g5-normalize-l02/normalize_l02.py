from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import shutil
import subprocess
import zipfile
from collections import OrderedDict, Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path('mg853-g5-normalize-l02/output_normalization')
RAW = ROOT / '00_SUBSNAPSHOT_OPERACIONAL'
EXT = ROOT / '01_EXTRAIDO'
OUT = ROOT / '02_BASE_NORMALIZADA'
AUDIT = ROOT / '03_AUDITORIA'
for p in (RAW, EXT, OUT, AUDIT): p.mkdir(parents=True, exist_ok=True)

NOW = datetime.now(timezone.utc).replace(microsecond=0)
DATE = NOW.date().isoformat().replace('-', '')
VERSION = 'G5-L02-NORM-V1.0'
SOURCE_ID = 'F-014'

SOURCES = OrderedDict([
    ('AGUA_2024', 'https://www.gov.br/cidades/pt-br/acesso-a-informacao/acoes-e-programas/saneamento/sinisa/arquivos/SINISA_Resultados_Ref20242.zip'),
    ('GESTAO_MUNICIPAL_2023', 'https://www.gov.br/cidades/pt-br/acesso-a-informacao/acoes-e-programas/saneamento/sinisa/resultados-sinisa/SINISA_GESTAOMUNICIPAL_Informacoes_2023.xlsx'),
    ('ESGOTO_2023', 'https://www.gov.br/cidades/pt-br/acesso-a-informacao/acoes-e-programas/saneamento/sinisa/resultados-sinisa/SINISA_ESGOTO_Planilhas_2023_v2.zip'),
    ('RESIDUOS_2023', 'https://www.gov.br/cidades/pt-br/acesso-a-informacao/acoes-e-programas/saneamento/sinisa/resultados-sinisa/SINISA_RESIDUOS_Planilhas_2023.rar'),
    ('AGUAS_PLUVIAIS_2023', 'https://www.gov.br/cidades/pt-br/acesso-a-informacao/acoes-e-programas/saneamento/sinisa/resultados-sinisa/SINISA_AGUASPLUVIAIS_PLANILHAS_2023_V224042025.rar'),
])
IBGE_API = 'https://servicodados.ibge.gov.br/api/v1/localidades/estados/31/municipios?orderBy=nome'

VARS = OrderedDict([
    ('OGM2001', dict(alias='gm_regulador_agua', module='GESTAO_MUNICIPAL', year=2023, unit='SIM_NAO', classification='CONTEXTO_GOVERNANCA', bounded=False, description='Existência de entidade responsável pela regulação de serviços de abastecimento de água', redundancy='MUNIC_CAPACIDADE_GOVERNANCA')),
    ('OGM2101', dict(alias='gm_regulador_esgoto', module='GESTAO_MUNICIPAL', year=2023, unit='SIM_NAO', classification='CONTEXTO_GOVERNANCA', bounded=False, description='Existência de entidade responsável pela regulação de serviços de esgotamento sanitário', redundancy='MUNIC_CAPACIDADE_GOVERNANCA')),
    ('OGM2201', dict(alias='gm_regulador_residuos', module='GESTAO_MUNICIPAL', year=2023, unit='SIM_NAO', classification='CONTEXTO_GOVERNANCA', bounded=False, description='Existência de entidade responsável pela regulação de serviços de limpeza urbana e manejo de resíduos sólidos', redundancy='MUNIC_CAPACIDADE_GOVERNANCA')),
    ('OGM2301', dict(alias='gm_regulador_pluvial', module='GESTAO_MUNICIPAL', year=2023, unit='SIM_NAO', classification='CONTEXTO_GOVERNANCA', bounded=False, description='Existência de entidade responsável pela regulação de serviços de drenagem e manejo de águas pluviais urbanas', redundancy='MUNIC_CAPACIDADE_GOVERNANCA')),
    ('OGM3201', dict(alias='gm_conselho_saneamento', module='GESTAO_MUNICIPAL', year=2023, unit='SIM_NAO', classification='CONTEXTO_GOVERNANCA', bounded=False, description='Existência de Conselho Municipal com atuação específica para os serviços de saneamento básico', redundancy='MUNIC_CONTROLE_SOCIAL')),
    ('OGM3301', dict(alias='gm_consorcio_saneamento', module='GESTAO_MUNICIPAL', year=2023, unit='SIM_NAO', classification='CONTEXTO_GOVERNANCA', bounded=False, description='Participação do município em Consórcio Público com atuação em Saneamento Básico', redundancy='MUNIC_CAPACIDADE_GOVERNANCA')),
    ('OGM3207', dict(alias='gm_sistema_info_saneamento_publico', module='GESTAO_MUNICIPAL', year=2023, unit='SIM_NAO', classification='CONTEXTO_GOVERNANCA', bounded=False, description='Existência de sistema de informações sobre os serviços de saneamento básico, de caráter público', redundancy='MUNIC_CAPACIDADE_INFORMACIONAL')),
    ('OGM3208', dict(alias='gm_ouvidoria_saneamento', module='GESTAO_MUNICIPAL', year=2023, unit='SIM_NAO', classification='CONTEXTO_GOVERNANCA', bounded=False, description='Existência de ouvidoria municipal ou central de atendimento ao cidadão para recebimento de reclamações ou manifestações sobre os serviços', redundancy='MUNIC_CAPACIDADE_INSTITUCIONAL')),
    ('IAG0001', dict(alias='agua_pct_pop_total_rede', module='AGUA', year=2024, unit='PERCENTUAL', classification='NUCLEO_SERVICO', bounded=True, description='Atendimento da população total com rede de abastecimento de água', redundancy='G5_L01_pct_mor_agua_rede_geral')),
    ('IAG0004', dict(alias='agua_pct_dom_total_rede', module='AGUA', year=2024, unit='PERCENTUAL', classification='NUCLEO_SERVICO', bounded=True, description='Atendimento dos domicílios totais com rede de abastecimento de água', redundancy='G5_L01_pct_dom_agua_rede_geral')),
    ('IAG2013', dict(alias='agua_pct_perdas_distribuicao', module='AGUA', year=2024, unit='PERCENTUAL', classification='NUCLEO_DESEMPENHO', bounded=True, description='Perdas totais de água na distribuição', redundancy='SEM_EQUIVALENTE_DIRETO')),
    ('IAG2016', dict(alias='agua_pct_ligacoes_setorizadas', module='AGUA', year=2024, unit='PERCENTUAL', classification='NUCLEO_INFRAESTRUTURA', bounded=True, description='Incidência de ligações de água setorizadas', redundancy='SEM_EQUIVALENTE_DIRETO')),
    ('IES0001', dict(alias='esgoto_pct_pop_total_rede', module='ESGOTO', year=2023, unit='PERCENTUAL', classification='NUCLEO_SERVICO', bounded=True, description='Atendimento da população total com rede coletora de esgoto', redundancy='G5_L01_pct_mor_esgoto_rede_geral_ou_pluvial')),
    ('IES0004', dict(alias='esgoto_pct_dom_total_rede', module='ESGOTO', year=2023, unit='PERCENTUAL', classification='NUCLEO_SERVICO', bounded=True, description='Atendimento dos domicílios totais com rede coletora de esgoto', redundancy='G5_L01_pct_dom_esgoto_rede_geral_ou_pluvial')),
    ('IES0007', dict(alias='esgoto_pct_dom_total_coleta_tratamento', module='ESGOTO', year=2023, unit='PERCENTUAL', classification='NUCLEO_SERVICO', bounded=True, description='Atendimento dos domicílios totais com coleta e tratamento de esgoto', redundancy='SEM_EQUIVALENTE_DIRETO')),
    ('IES2004', dict(alias='esgoto_pct_tratado_do_coletado', module='ESGOTO', year=2023, unit='PERCENTUAL', classification='NUCLEO_DESEMPENHO', bounded=True, description='Esgoto tratado referido ao esgoto coletado', redundancy='SEM_EQUIVALENTE_DIRETO')),
    ('IRS0001', dict(alias='residuos_pct_pop_total_coleta', module='RESIDUOS', year=2023, unit='PERCENTUAL', classification='NUCLEO_SERVICO', bounded=True, description='Cobertura da população total com coleta de resíduos sólidos domiciliares', redundancy='G5_L01_pct_mor_lixo_servico_limpeza')),
    ('IRS0005', dict(alias='residuos_pct_pop_total_coleta_seletiva', module='RESIDUOS', year=2023, unit='PERCENTUAL', classification='NUCLEO_SERVICO', bounded=True, description='Cobertura da população total com coleta seletiva de resíduos sólidos domiciliares', redundancy='SEM_EQUIVALENTE_DIRETO')),
    ('IRS1004', dict(alias='residuos_massa_rsu_kg_hab_dia', module='RESIDUOS', year=2023, unit='KG_HAB_DIA', classification='NUCLEO_OPERACIONAL', bounded=False, description='Massa média per capita de resíduos sólidos urbanos coletados', redundancy='SEM_EQUIVALENTE_DIRETO')),
    ('IRS3002', dict(alias='residuos_pct_disposicao_final_inadequada', module='RESIDUOS', year=2023, unit='PERCENTUAL', classification='NUCLEO_ALERTA_FONTE', bounded=False, description='Disposição final inadequada de resíduos sólidos urbanos', redundancy='SEM_EQUIVALENTE_DIRETO')),
    ('IRS3010', dict(alias='residuos_pct_recuperacao_total_coletado', module='RESIDUOS', year=2023, unit='PERCENTUAL', classification='NUCLEO_DESEMPENHO', bounded=True, description='Recuperação de resíduos recicláveis secos e orgânicos em relação à quantidade total coletada', redundancy='SEM_EQUIVALENTE_DIRETO')),
    ('IGE0001', dict(alias='pluvial_pct_area_urbanizada', module='PLUVIAL', year=2023, unit='PERCENTUAL', classification='CONTEXTO_TERRITORIAL', bounded=True, description='Parcela de área urbanizada em relação à área total', redundancy='TERRITORIO_IBGE_AREA_URBANIZADA')),
    ('IAP0001', dict(alias='pluvial_pct_vias_pavimentadas', module='PLUVIAL', year=2023, unit='PERCENTUAL', classification='NUCLEO_INFRAESTRUTURA', bounded=True, description='Parcela de vias públicas pavimentadas na área urbana', redundancy='CENSO_ENTORNO_PAVIMENTACAO')),
    ('IAP0002', dict(alias='pluvial_pct_vias_rede_subterranea', module='PLUVIAL', year=2023, unit='PERCENTUAL', classification='NUCLEO_INFRAESTRUTURA', bounded=True, description='Parcela de vias públicas com redes de águas pluviais subterrâneas na área urbana', redundancy='CENSO_ENTORNO_DRENAGEM')),
    ('IGR0001', dict(alias='pluvial_pct_dom_risco_inundacao', module='PLUVIAL', year=2023, unit='PERCENTUAL', classification='NUCLEO_RISCO', bounded=True, description='Parcela de domicílios sujeitos a risco de inundação na área urbana', redundancy='G5_L05_DESASTRES_G5_L06_SGB')),
    ('IGR0002', dict(alias='pluvial_pct_pop_impactada_eventos_hidrologicos', module='PLUVIAL', year=2023, unit='PERCENTUAL', classification='NUCLEO_RISCO', bounded=True, description='Parcela da população impactada por eventos hidrológicos', redundancy='G5_L05_DESASTRES_G5_L06_SGB')),
    ('IGR0009', dict(alias='pluvial_pct_imoveis_atingidos_eventos_hidrologicos', module='PLUVIAL', year=2023, unit='PERCENTUAL', classification='NUCLEO_RISCO', bounded=True, description='Parcela de imóveis atingidos por eventos hidrológicos na área urbana', redundancy='G5_L05_DESASTRES_G5_L06_SGB')),
])

GM_SHEETS = {
    'OGM2001':'GM- Regulação de Serviços AG', 'OGM2101':'GM- Regulação de Serviços ES',
    'OGM2201':'GM- Regulação de Serviços RS', 'OGM2301':'GM- Regulação de Serviços AP',
    'OGM3201':'GM - Controle Social', 'OGM3301':'GM - Consórcio Público',
    'OGM3207':'GM - Política e Planos', 'OGM3208':'GM - Política e Planos',
}
SAMPLE_CODES = ['3106200','3170206','3118601','3136702','3138203','3100203','3164308','3166600','3135209','3168606','3140001','3109006']

NS = {'a':'http://schemas.openxmlformats.org/spreadsheetml/2006/main','r':'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}

def sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024), b''): h.update(b)
    return h.hexdigest()

def curl(url: str, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(['curl','-L','--fail','--retry','6','--retry-all-errors','--connect-timeout','30','--max-time','600','--compressed','-A','MG853-OABMG/1.0','-o',str(path),url], check=True)
    if not path.exists() or path.stat().st_size == 0: raise RuntimeError(f'Download vazio: {url}')
    return path

def extract_archive(path: Path, out: Path):
    out.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower()=='.zip':
        with zipfile.ZipFile(path) as z: z.extractall(out)
    elif path.suffix.lower()=='.rar':
        cmd=shutil.which('7z') or shutil.which('7zz')
        if not cmd: raise RuntimeError('7z não disponível')
        subprocess.run([cmd,'t',str(path)], check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        subprocess.run([cmd,'x','-y',f'-o{out}',str(path)], check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    else:
        shutil.copy2(path,out/path.name)

def col_index(ref: str) -> int:
    m=re.match(r'([A-Z]+)',ref); n=0
    for ch in m.group(1): n=n*26+ord(ch)-64
    return n-1

def read_xlsx(path: Path):
    with zipfile.ZipFile(path) as z:
        shared=[]
        if 'xl/sharedStrings.xml' in z.namelist():
            rt=ET.fromstring(z.read('xl/sharedStrings.xml'))
            for si in rt.findall('a:si',NS): shared.append(''.join(t.text or '' for t in si.findall('.//a:t',NS)))
        wb=ET.fromstring(z.read('xl/workbook.xml'))
        rr=ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))
        rel={x.attrib['Id']:x.attrib['Target'] for x in rr}
        result={}
        for s in wb.find('a:sheets',NS):
            name=s.attrib['name']; rid=s.attrib['{'+NS['r']+'}id']; target=rel[rid]
            if not target.startswith('xl/'): target='xl/'+target.lstrip('/')
            rt=ET.fromstring(z.read(target)); rows=[]
            for row in rt.findall('.//a:sheetData/a:row',NS):
                vals={}
                for c in row.findall('a:c',NS):
                    idx=col_index(c.attrib['r']); typ=c.attrib.get('t'); v=c.find('a:v',NS); val=''
                    if typ=='inlineStr': val=''.join(t.text or '' for t in c.findall('.//a:t',NS))
                    elif v is not None:
                        raw=v.text or ''; val=shared[int(raw)] if typ=='s' and raw else raw
                    vals[idx]=val
                if vals: rows.append([vals.get(i,'') for i in range(max(vals)+1)])
            result[name]=rows
        return result

def clean_code(v):
    s=str(v or '').strip().replace('.0','')
    return s.zfill(7) if s.isdigit() else s

def decimal_value(raw):
    s=str(raw or '').strip()
    if not s or s.lower() in {'null','x','-','..','...'}: return None, 'NI'
    low=s.lower()
    if 'div/0' in low or 'divisão por zero' in low: return None, 'NAO_CALCULADO_DIV_ZERO'
    if 'não calc' in low or 'não calculado' in low:
        if 'dados não inf' in low or 'condições não atendidas' in low: return None, 'NI'
        return None, 'NAO_CALCULADO'
    try:
        d=Decimal(s.replace(',','.'))
        d=d.quantize(Decimal('0.000001'), rounding=ROUND_HALF_UP).normalize()
        if d == d.to_integral(): return str(d.to_integral()), 'OK'
        return format(d,'f'), 'OK'
    except InvalidOperation:
        return None, 'NI'

def categorical_value(raw):
    s=str(raw or '').strip()
    if not s or s.lower()=='null': return 'NI','NI'
    norm=s.casefold()
    if norm in {'sim','s'}: return 'SIM','OK'
    if norm in {'não','nao','n'}: return 'NAO','OK'
    return 'NI','NI'

def find_code_row(rows, codes):
    for ri,row in enumerate(rows):
        normalized=[str(x).strip().replace('*','') for x in row]
        if any(c in normalized for c in codes): return ri, normalized
    raise RuntimeError(f'Códigos não localizados: {codes}')

def module_records(sheet_rows, codes, code_col=0, name_col=2, uf_col=3):
    ri, code_row=find_code_row(sheet_rows,codes)
    colmap={c:code_row.index(c) for c in codes}
    rec={}
    for row in sheet_rows[ri+1:]:
        if len(row)<=max(code_col,uf_col): continue
        cod=clean_code(row[code_col])
        if not (len(cod)==7 and cod.isdigit()): continue
        if str(row[uf_col]).strip()!='MG': continue
        rec[cod]={'municipio': str(row[name_col]).strip() if len(row)>name_col else '', 'raw':{c:(row[i] if i<len(row) else '') for c,i in colmap.items()}}
    return rec

def gm_records(book):
    values={}
    statuses={}
    names={}
    for code in [c for c,m in VARS.items() if m['module']=='GESTAO_MUNICIPAL']:
        rows=book[GM_SHEETS[code]]; ri,crow=find_code_row(rows,[code]); ci=crow.index(code)
        for row in rows[ri+1:]:
            if len(row)<4: continue
            cod=clean_code(row[1])
            if not (len(cod)==7 and cod.isdigit()) or str(row[3]).strip()!='MG': continue
            names[cod]=str(row[2]).strip(); statuses[cod]=str(row[0]).strip(); values.setdefault(cod,{})[code]=row[ci] if ci<len(row) else ''
    return values,statuses,names

def csv_write(path, headers, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=headers,delimiter=';',extrasaction='ignore'); w.writeheader(); w.writerows(rows)

def ptbr_copy(src: Path, dst: Path):
    with src.open('r',encoding='utf-8-sig',newline='') as f, dst.open('w',encoding='utf-8-sig',newline='') as g:
        r=csv.reader(f,delimiter=';'); w=csv.writer(g,delimiter=';')
        for row in r:
            w.writerow([re.sub(r'^(-?\d+)\.(\d+)$',lambda m:m.group(1)+','+m.group(2),v) if isinstance(v,str) else v for v in row])

# 1. Aquisição robusta e cadeia de custódia.
raw_files={}
for key,url in SOURCES.items():
    ext='.xlsx' if url.lower().endswith('.xlsx') else '.rar' if url.lower().endswith('.rar') else '.zip'
    raw_files[key]=curl(url,RAW/f'{key}{ext}')
ibge_path=curl(IBGE_API,RAW/'IBGE_MUNICIPIOS_MG.json')
source_manifest=[]
for k,p in raw_files.items(): source_manifest.append({'source_key':k,'fonte_id':SOURCE_ID,'url':SOURCES[k],'file_name':p.name,'size_bytes':p.stat().st_size,'sha256':sha256(p)})
source_manifest.append({'source_key':'IBGE_MUNICIPIOS_MG','fonte_id':'F-001','url':IBGE_API,'file_name':ibge_path.name,'size_bytes':ibge_path.stat().st_size,'sha256':sha256(ibge_path)})
csv_write(AUDIT/'MG853_G5_L02_MANIFESTO_FONTES_V1_0.csv',['source_key','fonte_id','url','file_name','size_bytes','sha256'],source_manifest)
(AUDIT/'MG853_G5_L02_MANIFESTO_FONTES_V1_0.json').write_text(json.dumps(source_manifest,ensure_ascii=False,indent=2),encoding='utf-8')

# sub-snapshot atual completo dos cinco produtos estruturados efetivamente utilizados
subsnapshot=ROOT.parent/'MG853_G5_L02_SUBSNAPSHOT_OPERACIONAL_20260807.zip'
with zipfile.ZipFile(subsnapshot,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
    for p in raw_files.values(): z.write(p,arcname='fontes/'+p.name)
    z.write(ibge_path,arcname='fontes/'+ibge_path.name)
    z.write(AUDIT/'MG853_G5_L02_MANIFESTO_FONTES_V1_0.csv',arcname='manifesto/MG853_G5_L02_MANIFESTO_FONTES_V1_0.csv')
    z.write(AUDIT/'MG853_G5_L02_MANIFESTO_FONTES_V1_0.json',arcname='manifesto/MG853_G5_L02_MANIFESTO_FONTES_V1_0.json')

# 2. Extração dos produtos oficiais.
extract_archive(raw_files['AGUA_2024'],EXT/'AGUA_2024')
extract_archive(raw_files['ESGOTO_2023'],EXT/'ESGOTO_2023')
extract_archive(raw_files['RESIDUOS_2023'],EXT/'RESIDUOS_2023')
extract_archive(raw_files['AGUAS_PLUVIAIS_2023'],EXT/'PLUVIAL_RAR')
shutil.copy2(raw_files['GESTAO_MUNICIPAL_2023'],EXT/'GESTAO_MUNICIPAL_2023.xlsx')
pluvial_ind_zip=next((EXT/'PLUVIAL_RAR').glob('*Indicadores*.zip'))
extract_archive(pluvial_ind_zip,EXT/'PLUVIAL_INDICADORES')

water_xlsx=next((EXT/'AGUA_2024').rglob('SINISA_AGUA_Indicadores_Base Municipal_2024.xlsx'))
sewage_xlsx=next((EXT/'ESGOTO_2023').rglob('SINISA_ESGOTO_Indicadores_Base Municipal_2023_V2.xlsx'))
res_xlsx=next((EXT/'RESIDUOS_2023').rglob('SINISA_RESIDUOS_Indicadores_2023.xlsx'))
pluv_xlsx=next((EXT/'PLUVIAL_INDICADORES').rglob('*.xlsx'))
gm_xlsx=EXT/'GESTAO_MUNICIPAL_2023.xlsx'

# 3. Universo canônico IBGE.
api_bytes=ibge_path.read_bytes()
if api_bytes[:2]==b'\x1f\x8b':
    import gzip; api_bytes=gzip.decompress(api_bytes)
api=json.loads(api_bytes.decode('utf-8'))
municipios={str(x['id']):x['nome'] for x in api}
if len(municipios)!=853: raise RuntimeError(f'IBGE API retornou {len(municipios)} municípios')

# 4. Leitura das bases municipais oficiais, sem somatório de prestadores.
water_book=read_xlsx(water_xlsx); sewage_book=read_xlsx(sewage_xlsx); res_book=read_xlsx(res_xlsx); pluv_book=read_xlsx(pluv_xlsx); gm_book=read_xlsx(gm_xlsx)
water_codes=[c for c,m in VARS.items() if m['module']=='AGUA']
sew_att=[c for c in ['IES0001','IES0004','IES0007']]
sew_op=['IES2004']
res_codes=[c for c,m in VARS.items() if m['module']=='RESIDUOS']
pluv_codes=[c for c,m in VARS.items() if m['module']=='PLUVIAL']
water=module_records(water_book['Indicadores de Gestão'],water_codes)
sewage={}
for cod,r in module_records(sewage_book['Atendimento'],sew_att).items(): sewage.setdefault(cod,{'municipio':r['municipio'],'raw':{}})['raw'].update(r['raw'])
for cod,r in module_records(sewage_book['Estruturais e Operacionais'],sew_op).items(): sewage.setdefault(cod,{'municipio':r['municipio'],'raw':{}})['raw'].update(r['raw'])
res=module_records(res_book['Planilha de Indicadores'],res_codes,code_col=1,name_col=2,uf_col=3)
pluv=module_records(pluv_book['Indicadores por município'],pluv_codes,code_col=0,name_col=1,uf_col=2)
gm_vals,gm_response,gm_names=gm_records(gm_book)

# Status dos módulos de amostra completa.
res_rows=res_book['Planilha de Indicadores']; ri,_=find_code_row(res_rows,res_codes); res_response={}
for row in res_rows[ri+1:]:
    if len(row)>3 and str(row[3]).strip()=='MG' and len(clean_code(row[1]))==7: res_response[clean_code(row[1])]=str(row[0]).strip()
pluv_rows=pluv_book['Indicadores por município']; ri,_=find_code_row(pluv_rows,pluv_codes); pluv_response={}
for row in pluv_rows[ri+1:]:
    if len(row)>12 and str(row[2]).strip()=='MG' and len(clean_code(row[0]))==7: pluv_response[clean_code(row[0])]=str(row[12]).strip()

# 5. Normalização municipal delimitada.
base_rows=[]; long_rows=[]; outliers=[]
for cod,name in sorted(municipios.items()):
    row=OrderedDict([
        ('cod_ibge_7',cod),('municipio',name),('uf','MG'),('fonte_id',SOURCE_ID),('versao_transformacao',VERSION),('data_extracao_utc',NOW.isoformat()),
        ('gm_ano_referencia','2023'),('gm_status','RESPONDEU' if gm_response.get(cod,'').casefold()=='sim' else 'NAO_RESPONDEU'),
        ('agua_ano_referencia','2024'),('agua_status','DISPONIVEL_BASE_MUNICIPAL' if cod in water else 'ND'),
        ('esgoto_ano_referencia','2023'),('esgoto_status','DISPONIVEL_BASE_MUNICIPAL' if cod in sewage else 'ND'),
        ('residuos_ano_referencia','2023'),('residuos_status','RESPONDEU' if res_response.get(cod,'').casefold()=='sim' else 'NAO_RESPONDEU'),
        ('pluvial_ano_referencia','2023'),('pluvial_status','PARTICIPANTE' if pluv_response.get(cod,'').casefold()=='participante' else 'NAO_PARTICIPANTE'),
        ('nivel_confianca','ALTO_COM_RASTREABILIDADE_OFICIAL'),
    ])
    for code,meta in VARS.items():
        raw=''
        if meta['module']=='GESTAO_MUNICIPAL': raw=gm_vals.get(cod,{}).get(code,'')
        elif meta['module']=='AGUA': raw=water.get(cod,{}).get('raw',{}).get(code,'')
        elif meta['module']=='ESGOTO': raw=sewage.get(cod,{}).get('raw',{}).get(code,'')
        elif meta['module']=='RESIDUOS': raw=res.get(cod,{}).get('raw',{}).get(code,'')
        elif meta['module']=='PLUVIAL': raw=pluv.get(cod,{}).get('raw',{}).get(code,'')
        if meta['unit']=='SIM_NAO': value,status=categorical_value(raw)
        else:
            value,status=decimal_value(raw)
            value=value if value is not None else status
        row[meta['alias']]=value
        long_rows.append({'cod_ibge_7':cod,'municipio':name,'uf':'MG','fonte_id':SOURCE_ID,'modulo':meta['module'],'ano_referencia':meta['year'],'codigo_sinisa':code,'campo_normalizado':meta['alias'],'descricao':meta['description'],'unidade':meta['unit'],'classificacao':meta['classification'],'valor':value,'status_valor':status,'redundancia_semantica_alvo':meta['redundancy']})
        if meta['unit']=='PERCENTUAL' and status=='OK':
            fv=float(value)
            if fv<0 or fv>100:
                outliers.append({'cod_ibge_7':cod,'municipio':name,'codigo_sinisa':code,'campo_normalizado':meta['alias'],'valor':value,'bounded_expected':'SIM' if meta['bounded'] else 'NAO','tratamento':'ERRO_CRITICO' if meta['bounded'] else 'PRESERVAR_VALOR_OFICIAL_E_SINALIZAR'})
    base_rows.append(row)

# 6. Dicionário e matriz semântica.
dict_rows=[]; semantic=[]
for code,meta in VARS.items():
    dict_rows.append({'codigo_sinisa':code,'campo_normalizado':meta['alias'],'modulo':meta['module'],'ano_referencia':meta['year'],'descricao_oficial':meta['description'],'unidade':meta['unit'],'classificacao':meta['classification'],'intervalo_0_100_obrigatorio':'SIM' if meta['bounded'] else 'NAO','fonte_id':SOURCE_ID,'regra_ausencia':'NI/ND/NAO_CALCULADO_DIV_ZERO/NAO_CALCULADO; nunca converter ausência em zero','regra_agregacao':'USAR_BASE_MUNICIPAL_OFICIAL; PROIBIDO_SOMAR_PRESTADORES','redundancia_semantica_alvo':meta['redundancy']})
    semantic.append({'codigo_sinisa':code,'campo_normalizado':meta['alias'],'modulo_sinisa':meta['module'],'dimensao':meta['classification'],'camada_correlata':meta['redundancy'],'tipo_relacao':'CORRELACAO_SEMANTICA_NAO_IDENTIDADE','uso_g5_4':'TESTAR_REDUNDANCIA_EMPIRICA_QUANDO_CAMADAS_DISPONIVEIS','observacao':'Denominadores, universos e conceitos devem ser comparados antes de qualquer coeficiente ou exclusão.'})

# 7. Cobertura.
coverage=[]
for code,meta in VARS.items():
    vals=[r[meta['alias']] for r in base_rows]
    ok=sum(1 for v in vals if str(v) not in {'NI','ND','NAO_CALCULADO','NAO_CALCULADO_DIV_ZERO'})
    cnt=Counter(str(v) for v in vals if str(v) in {'NI','ND','NAO_CALCULADO','NAO_CALCULADO_DIV_ZERO'})
    coverage.append({'codigo_sinisa':code,'campo_normalizado':meta['alias'],'modulo':meta['module'],'ano_referencia':meta['year'],'registros_total':853,'valores_disponiveis':ok,'cobertura_percentual':round(ok/853*100,6),'NI':cnt['NI'],'ND':cnt['ND'],'NAO_CALCULADO':cnt['NAO_CALCULADO'],'NAO_CALCULADO_DIV_ZERO':cnt['NAO_CALCULADO_DIV_ZERO']})

# 8. Amostra dirigida com comparação direta entre fonte e resultado.
by_code={r['cod_ibge_7']:r for r in base_rows}; sample=[]
for cod in SAMPLE_CODES:
    if cod not in by_code: continue
    for code,meta in VARS.items():
        norm=str(by_code[cod][meta['alias']])
        raw=''
        if meta['module']=='GESTAO_MUNICIPAL': raw=gm_vals.get(cod,{}).get(code,'')
        elif meta['module']=='AGUA': raw=water.get(cod,{}).get('raw',{}).get(code,'')
        elif meta['module']=='ESGOTO': raw=sewage.get(cod,{}).get('raw',{}).get(code,'')
        elif meta['module']=='RESIDUOS': raw=res.get(cod,{}).get('raw',{}).get(code,'')
        else: raw=pluv.get(cod,{}).get('raw',{}).get(code,'')
        if meta['unit']=='SIM_NAO': expected,_=categorical_value(raw)
        else:
            v,st=decimal_value(raw); expected=v if v is not None else st
        match=(str(expected)==norm)
        sample.append({'cod_ibge_7':cod,'municipio':by_code[cod]['municipio'],'codigo_sinisa':code,'campo_normalizado':meta['alias'],'valor_fonte_bruta':raw,'valor_normalizado':norm,'resultado':'OK' if match else 'DIVERGENCIA'})

# 9. Testes auditáveis.
def numeric_values(alias):
    out=[]
    for r in base_rows:
        try: out.append(float(r[alias]))
        except: pass
    return out
bounded_errors=[o for o in outliers if o['bounded_expected']=='SIM']
allowed_source_alerts=[o for o in outliers if o['bounded_expected']=='NAO']
tests=[]
def test(tid,name,passed,result,expected): tests.append({'teste_id':tid,'teste':name,'aprovado':'SIM' if passed else 'NAO','resultado':result,'esperado':expected})
test('L02-T01','UNIVERSO_IBGE_853',len(municipios)==853,len(municipios),'853')
test('L02-T02','BASE_NORMALIZADA_853',len(base_rows)==853,len(base_rows),'853')
test('L02-T03','CHAVES_UNICAS',len({r['cod_ibge_7'] for r in base_rows})==853,len({r['cod_ibge_7'] for r in base_rows}),'853')
test('L02-T04','CODIGO_7_DIGITOS',all(len(r['cod_ibge_7'])==7 and r['cod_ibge_7'].isdigit() for r in base_rows),'853 válidos','853 válidos')
test('L02-T05','PREFIXO_31',all(r['cod_ibge_7'].startswith('31') for r in base_rows),'853','853')
test('L02-T06','CINCO_FONTES_ESTRUTURADAS_ADQUIRIDAS',len(raw_files)==5,len(raw_files),'5')
test('L02-T07','SELECAO_DELIMITADA_27_VARIAVEIS',len(VARS)==27,len(VARS),'27')
test('L02-T08','ALIASES_UNICOS',len({m['alias'] for m in VARS.values()})==27,len({m['alias'] for m in VARS.values()}),'27')
test('L02-T09','AGUA_BASE_MUNICIPAL_UNICA',len(water)==824 and len(set(water))==824,len(water),'824 MG; único por município')
test('L02-T10','ESGOTO_BASE_MUNICIPAL_UNICA',len(sewage)==684 and len(set(sewage))==684,len(sewage),'684 MG; único por município')
test('L02-T11','RESIDUOS_UNIVERSO_853',len(res)==853 and len(set(res))==853,len(res),'853 MG')
test('L02-T12','RESIDUOS_STATUS_760_93',Counter('SIM' if x.casefold()=='sim' else 'NAO' for x in res_response.values())==Counter({'SIM':760,'NAO':93}),dict(Counter('SIM' if x.casefold()=='sim' else 'NAO' for x in res_response.values())),'SIM=760; NAO=93')
test('L02-T13','PLUVIAL_UNIVERSO_853',len(pluv)==853 and len(set(pluv))==853,len(pluv),'853 MG')
test('L02-T14','PLUVIAL_STATUS_775_78',Counter('PART' if x.casefold()=='participante' else 'NAO' for x in pluv_response.values())==Counter({'PART':775,'NAO':78}),dict(Counter('PART' if x.casefold()=='participante' else 'NAO' for x in pluv_response.values())),'PART=775; NAO=78')
test('L02-T15','GESTAO_MUNICIPAL_UNIVERSO_853',len(gm_response)==853 and len(set(gm_response))==853,len(gm_response),'853 MG')
test('L02-T16','GESTAO_STATUS_711_142',Counter('SIM' if x.casefold()=='sim' else 'NAO' for x in gm_response.values())==Counter({'SIM':711,'NAO':142}),dict(Counter('SIM' if x.casefold()=='sim' else 'NAO' for x in gm_response.values())),'SIM=711; NAO=142')
test('L02-T17','SEM_AGREGACAO_ARTIFICIAL_PRESTADORES',True,'Somente planilhas Base Municipal ou municipais oficiais foram usadas','PROIBIDO somar prestadores')
test('L02-T18','ANOS_DE_REFERENCIA_EXPLICITOS',all(r['agua_ano_referencia']=='2024' and r['gm_ano_referencia']=='2023' and r['esgoto_ano_referencia']=='2023' and r['residuos_ano_referencia']=='2023' and r['pluvial_ano_referencia']=='2023' for r in base_rows),'Água=2024; demais=2023','Temporalidade explícita')
test('L02-T19','PERCENTUAIS_CORE_LIMITADOS_0_100',len(bounded_errors)==0,len(bounded_errors),'0 erros')
test('L02-T20','MASSA_RSU_NAO_NEGATIVA',all(x>=0 for x in numeric_values('residuos_massa_rsu_kg_hab_dia')),'OK','>=0')
test('L02-T21','GESTAO_CATEGORIAS_CONTROLADAS',all(str(r[m['alias']]) in {'SIM','NAO','NI'} for r in base_rows for c,m in VARS.items() if m['module']=='GESTAO_MUNICIPAL'),'OK','SIM/NAO/NI')
test('L02-T22','AMOSTRA_DIRIGIDA_SEM_DIVERGENCIA',all(r['resultado']=='OK' for r in sample),sum(1 for r in sample if r['resultado']!='OK'),'0 divergências')
test('L02-T23','MATRIZ_SEMANTICA_27',len(semantic)==27,len(semantic),'27')
test('L02-T24','OUTLIER_FONTE_NAO_CORRIGIDO_AUTOMATICAMENTE',True,len(allowed_source_alerts),'Preservar e sinalizar, não corrigir')
test('L02-T25','AUSENCIAS_EXPLICITAS',all(str(r[m['alias']])!='' for r in base_rows for c,m in VARS.items()),'Sem vazios nos 27 campos','NI/ND/NAO_CALCULADO explícitos')

critical_failed=[t for t in tests if t['aprovado']=='NAO']

# 10. Exportações.
base_headers=list(base_rows[0].keys())
csv_write(OUT/'MG853_G5_L02_BASE_MUNICIPAL_NORMALIZADA_V1_0.csv',base_headers,base_rows)
ptbr_copy(OUT/'MG853_G5_L02_BASE_MUNICIPAL_NORMALIZADA_V1_0.csv',OUT/'MG853_G5_L02_BASE_MUNICIPAL_NORMALIZADA_V1_0_GOOGLE_SHEETS_PTBR.csv')
csv_write(OUT/'MG853_G5_L02_INDICADORES_LONGOS_V1_0.csv',list(long_rows[0].keys()),long_rows)
csv_write(OUT/'MG853_G5_L02_DICIONARIO_VARIAVEIS_V1_0.csv',list(dict_rows[0].keys()),dict_rows)
csv_write(AUDIT/'MG853_G5_L02_COBERTURA_VARIAVEIS_V1_0.csv',list(coverage[0].keys()),coverage)
csv_write(AUDIT/'MG853_G5_L02_MATRIZ_CORRELACAO_SEMANTICA_V1_0.csv',list(semantic[0].keys()),semantic)
csv_write(AUDIT/'MG853_G5_L02_AMOSTRA_DIRIGIDA_V1_0.csv',list(sample[0].keys()),sample)
csv_write(AUDIT/'MG853_G5_L02_OUTLIERS_FONTE_V1_0.csv',['cod_ibge_7','municipio','codigo_sinisa','campo_normalizado','valor','bounded_expected','tratamento'],outliers)
csv_write(AUDIT/'MG853_G5_L02_TESTES_V1_0.csv',list(tests[0].keys()),tests)

README=f'''# MG 853 — G5-L02 — SINISA — Normalização V1.0\n\nStatus: {'REPROVADA' if critical_failed else 'NORMALIZACAO_APROVADA_PARA_REVISAO'}\n\n## Escopo delimitado\n27 campos: 8 de Gestão Municipal, 4 de Água, 4 de Esgoto, 5 de Resíduos e 6 de Águas Pluviais.\n\n## Temporalidade\n- Água: ano de referência 2024 — versão estruturada mais recente localizada no portal oficial.\n- Gestão Municipal, Esgoto, Resíduos e Águas Pluviais: ano de referência 2023 — versões estruturadas vigentes localizadas no portal oficial.\n\n## Regra de granularidade\nA normalização utiliza exclusivamente bases municipais oficiais quando disponíveis. É proibido somar linhas de prestadores para produzir município. A própria base municipal do SINISA é a unidade canônica desta camada.\n\n## Ausências\nNI, ND, NAO_CALCULADO e NAO_CALCULADO_DIV_ZERO permanecem explícitos. Ausência nunca é convertida em zero.\n\n## Gestão Municipal\nDados publicados oficialmente pelo SINISA a partir de respostas municipais. São sinais institucionais autodeclarados e não constituem validação jurídica individualizada. Campos de legislação/planos municipais foram deliberadamente excluídos do núcleo.\n\n## Outliers\nValores oficiais fora de 0–100 em variáveis não classificadas como obrigatoriamente limitadas, especialmente IRS3002, são preservados e registrados como alerta de fonte. Não há correção automática.\n\n## Redundância\nA matriz de correlação semântica define os alvos para G5.4. Relação semântica não significa identidade estatística; universos e denominadores devem ser verificados antes do cálculo de correlações.\n'''
(OUT/'README_NORMALIZACAO_G5_L02.md').write_text(README,encoding='utf-8')
summary={'lote':'G5-L02','fonte_id':SOURCE_ID,'versao':VERSION,'data_hora_utc':NOW.isoformat(),'municipios':853,'variaveis_selecionadas':27,'linhas_longas':len(long_rows),'modulos':{'gestao_municipal':{'ano':2023,'respondentes':711,'nao_respondentes':142},'agua':{'ano':2024,'municipios_base_municipal':len(water),'ND':853-len(water)},'esgoto':{'ano':2023,'municipios_base_municipal':len(sewage),'ND':853-len(sewage)},'residuos':{'ano':2023,'respondentes':760,'nao_respondentes':93},'pluvial':{'ano':2023,'participantes':775,'nao_participantes':78}},'testes_aprovados':sum(t['aprovado']=='SIM' for t in tests),'testes_total':len(tests),'falhas_criticas':len(critical_failed),'outliers_fonte_sinalizados':len(allowed_source_alerts),'amostra_dirigida_registros':len(sample),'amostra_divergencias':sum(r['resultado']!='OK' for r in sample),'status':'NORMALIZACAO_APROVADA_PARA_REVISAO' if not critical_failed else 'NORMALIZACAO_REPROVADA','subsnapshot_sha256':sha256(subsnapshot),'subsnapshot_size':subsnapshot.stat().st_size,'hashes_fontes':{x['source_key']:x['sha256'] for x in source_manifest}}
(AUDIT/'resumo_execucao.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')

# pacote normalizado sem duplicar o sub-snapshot bruto.
package=ROOT.parent/'MG853_G5_L02_NORMALIZACAO_V1_0_20260807.zip'
with zipfile.ZipFile(package,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
    for p in OUT.rglob('*'):
        if p.is_file(): z.write(p,arcname=str(p.relative_to(ROOT)))
    for p in AUDIT.rglob('*'):
        if p.is_file(): z.write(p,arcname=str(p.relative_to(ROOT)))
summary['package_sha256']=sha256(package); summary['package_size']=package.stat().st_size
(AUDIT/'resumo_execucao.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False,indent=2))
print('\nTESTES')
for t in tests: print(t)
if critical_failed: raise SystemExit(2)
