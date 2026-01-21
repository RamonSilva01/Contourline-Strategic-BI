import streamlit as st
from openai import OpenAI
import pandas as pd
import plotly.express as px
from concurrent.futures import ThreadPoolExecutor
import io
import re
from datetime import datetime
import random
from supabase import create_client, Client

# ==========================================
# 🔐 AUTENTICAÇÃO E CONEXÃO BANCO DE DADOS
# ==========================================
try:
    OPENAI_API_KEY = st.secrets["OPENAI_API_KEY"]
    SUPABASE_URL = st.secrets["SUPABASE_URL"]
    SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
except:
    st.error("⚠️ Erro Crítico: Configure OPENAI_API_KEY, SUPABASE_URL e SUPABASE_KEY nos Segredos.")
    st.stop()

# Conecta ao Supabase
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

st.set_page_config(page_title="Contourline Intelligence Hub", layout="wide")
st.title("🏛️ Contourline: Intelligence")

# --- FUNÇÕES DE BANCO DE DADOS ---

def buscar_ultimo_perfil():
    """Busca o perfil mais recente salvo no Supabase"""
    try:
        response = supabase.table('perfis_icp').select("*").order('created_at', desc=True).limit(1).execute()
        if response.data and len(response.data) > 0:
            return response.data[0]['texto_perfil'], response.data[0]['created_at']
        return None, None
    except Exception as e:
        st.error(f"Erro ao conectar no banco: {e}")
        return None, None

def salvar_novo_perfil(texto, nome_arquivo="Upload Manual"):
    """Salva um novo aprendizado no banco para o futuro"""
    try:
        dados = {
            "texto_perfil": texto,
            "origem_arquivo": nome_arquivo
        }
        supabase.table('perfis_icp').insert(dados).execute()
        st.toast("✅ Novo conhecimento salvo no banco de dados!", icon="💾")
        return True
    except Exception as e:
        st.error(f"Erro ao salvar: {e}")
        return False

# --- FUNÇÕES DE ENGENHARIA (MANTIDAS) ---
def limpar_csv_seguro(arquivo):
    corpo = arquivo.read().decode('utf-8-sig')
    arquivo.seek(0)
    pular = 1 if corpo.startswith('sep=') else 0
    return pd.read_csv(io.StringIO(corpo), skiprows=pular, sep=None, engine='python', dtype=str).fillna("N/A")

def converter_valor_br(valor_str):
    try:
        if pd.isna(valor_str) or valor_str in ["N/A", "nan", ""]: return 0.0
        limpo = str(valor_str).replace('R$', '').strip()
        if ',' in limpo:
            limpo = limpo.replace('.', '').replace(',', '.')
        return float(limpo)
    except: return 0.0

def formatar_brl(valor_float):
    return f"{valor_float:.2f}".replace('.', ',')

def processar_data(data_str):
    if pd.isna(data_str) or data_str in ["N/A", "nan", ""]: return None
    formatos = ['%d/%m/%Y', '%d/%m/%Y %H:%M', '%Y-%m-%d', '%Y-%m-%d %H:%M:%S', '%d-%m-%Y']
    data_limpa = str(data_str).split('.')[0]
    for fmt in formatos:
        try: return datetime.strptime(data_limpa, fmt)
        except ValueError: continue
    return None

def calcular_dias(data_obj):
    if not data_obj: return 9999
    delta = datetime.now() - data_obj
    return delta.days

def treinar_ia_multiarquivo(client, lista_arquivos):
    df_total = pd.DataFrame()
    nomes = []
    for arq in lista_arquivos:
        df_temp = limpar_csv_seguro(arq)
        df_total = pd.concat([df_total, df_temp], ignore_index=True)
        nomes.append(arq.name)
    
    col_prod = next((c for c in df_total.columns if any(x in c.lower() for x in ['produto', 'equipamento'])), None)
    col_val = next((c for c in df_total.columns if 'valor' in c.lower()), None)
    
    produtos_top = ""
    if col_prod:
        top = df_total[col_prod].value_counts().head(5).index.tolist()
        produtos_top = f" Produtos chave: {top}."

    if col_val:
        df_total['V_Calc'] = df_total[col_val].apply(converter_valor_br)
        amostra = df_total.sort_values(by='V_Calc', ascending=False).head(40).to_dict('records')
    else:
        amostra = df_total.head(40).to_dict('records')

    prompt = f"""
    Analise esta base unificada de vendas (Med e Não Med) da Contourline: {amostra}. 
    {produtos_top}
    Crie um PERFIL DE CLIENTE IDEAL (ICP) robusto e resumido em 1 parágrafo.
    """
    icp_gerado = client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}]).choices[0].message.content
    return icp_gerado, ", ".join(nomes)

def sugerir_novo_dono(vendedor_atual, lista_vendedores):
    if len(lista_vendedores) <= 1: return vendedor_atual
    candidatos = [v for v in lista_vendedores if v != vendedor_atual and v not in ["N/A", "nan", ""]]
    if not candidatos: return vendedor_atual
    return random.choice(candidatos)

def extrair_nota_segura(texto_ia):
    numeros = re.findall(r'\b\d+\b', str(texto_ia))
    if not numeros: return 0
    for num in numeros:
        n = int(num)
        if 0 <= n <= 100: return n
    return 0

def pontuar_lead(client, row, icp):
    try:
        prompt = f"ICP: {icp}. LEAD: {row}. Dê nota 0-100. Responda APENAS: NOTA | MOTIVO."
        res = client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}]).choices[0].message.content
        parts = res.split('|')
        score = extrair_nota_segura(parts[0])
        motivo = parts[1].strip() if len(parts) > 1 else res
        return {"score": score, "motivo": motivo}
    except: return {"score": 0, "motivo": "Erro"}

# --- FLUXO PRINCIPAL ---

# 1. Carrega o cérebro (Busca no Supabase)
perfil_banco, data_banco = buscar_ultimo_perfil()

with st.sidebar:
    st.header("🧠 Memória Corporativa")
    if perfil_banco:
        st.success(f"Perfil Ativo (Carregado do Banco)\n\nAtualizado em: {pd.to_datetime(data_banco).strftime('%d/%m/%Y')}")
        with st.expander("Ver Perfil Atual"):
            st.write(perfil_banco)
    else:
        st.warning("Nenhum perfil encontrado no banco. Faça o upload de vendas para ensinar o sistema.")
    
    st.markdown("---")
    st.header("⚙️ Configurações")
    filtrar_duplicados = st.checkbox("Filtro Anti-Duplicidade", value=True)
    min_score = st.slider("Régua de Aderência (%):", 0, 100, 30)

# ÁREA DE APRENDIZADO (UPLOAD DE VENDAS)
with st.expander("📚 Ensinar Novo Padrão de Sucesso (Atualizar IA)", expanded=not perfil_banco):
    st.info("Suba arquivos de vendas APENAS se quiser atualizar o perfil de cliente ideal.")
    arquivos_venda = st.file_uploader("CSVs de Vendas (Med + Não Med)", type="csv", accept_multiple_files=True)
    
    if arquivos_venda:
        if st.button("Analisar e Salvar no Banco"):
            client = OpenAI(api_key=OPENAI_API_KEY)
            with st.spinner("IA analisando novos padrões de venda..."):
                novo_perfil, nomes_arqs = treinar_ia_multiarquivo(client, arquivos_venda)
                if salvar_novo_perfil(novo_perfil, nomes_arqs):
                    st.success("Cérebro Atualizado! O novo perfil já está salvo no Supabase.")
                    st.rerun()

st.markdown("---")

# ÁREA DE OPERAÇÃO (DIA A DIA)
st.header("🕵️ Recuperação de Leads")
arquivo_perdas = st.file_uploader("Upload CSV Leads Perdidos", type="csv")

# O sistema roda se tiver perfil no banco OU se acabou de subir vendas
icp_ativo = perfil_banco

if icp_ativo and arquivo_perdas:
    if OPENAI_API_KEY:
        client = OpenAI(api_key=OPENAI_API_KEY)
        
        if 'processado' not in st.session_state: st.session_state.processado = False

        # PROCESSAMENTO
        df_l = limpar_csv_seguro(arquivo_perdas)
        col_motivo = next((c for c in df_l.columns if 'motivo' in c.lower()), "Motivo")
        col_valor = next((c for c in df_l.columns if 'valor' in c.lower()), None)
        col_nome = next((c for c in df_l.columns if any(x in c.lower() for x in ['nome', 'cliente'])), "Lead")
        col_prod = next((c for c in df_l.columns if any(x in c.lower() for x in ['produto', 'equipamento', 'item'])), None)
        col_vend = next((c for c in df_l.columns if any(x in c.lower() for x in ['vendedor', 'responsável', 'owner'])), None)
        col_data = next((c for c in df_l.columns if any(x in c.lower() for x in ['fechamento', 'perda', 'closing'])), None)

        if not col_prod: df_l['Equipamento'] = "N/A"; col_prod = 'Equipamento'
        if not col_vend: df_l['Vendedor_Orig'] = "N/A"; col_vend = 'Vendedor_Orig'
        
        df_l['Valor_Calc'] = df_l[col_valor].apply(converter_valor_br) if col_valor else 0.0
        
        if col_data:
            df_l['Data_Obj'] = df_l[col_data].apply(processar_data)
            df_l['Dias_Atras'] = df_l['Data_Obj'].apply(calcular_dias)
            df_l['Data_Perda'] = df_l['Data_Obj'].apply(lambda x: x.strftime('%d/%m/%Y') if x else "Sem Data")
        else:
            df_l['Data_Perda'] = "N/A"; df_l['Dias_Atras'] = 9999

        if filtrar_duplicados:
            mask_lixo = df_l[col_motivo].astype(str).str.contains(r'dupli|teste|cliente|repetido', case=False, regex=True)
            df_limpo = df_l[~mask_lixo].copy()
        else:
            df_limpo = df_l.copy()
            
        lista_vendedores = df_limpo[col_vend].dropna().unique().tolist()
        df_limpo['Sugestão Novo Dono'] = df_limpo[col_vend].apply(lambda x: sugerir_novo_dono(x, lista_vendedores))

        # DASHBOARD
        k1, k2, k3 = st.columns(3)
        k1.metric("Leads", len(df_limpo))
        k2.metric("Equipe", len(lista_vendedores))
        k3.metric("Risco", f"R$ {df_limpo['Valor_Calc'].sum():,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.'))

        g1, g2 = st.columns(2)
        with g1: st.plotly_chart(px.pie(df_limpo, names=col_motivo, title="Motivos", hole=0.4), use_container_width=True)
        with g2: 
            top_fin = df_limpo.groupby(col_motivo)['Valor_Calc'].sum().nlargest(8).reset_index()
            st.plotly_chart(px.bar(top_fin, y=col_motivo, x='Valor_Calc', orientation='h', title="Gargalos R$"), use_container_width=True)

        if st.button("🚀 Iniciar Recuperação (Baseado na Memória do Banco)") or st.session_state.processado:
            if not st.session_state.processado:
                with st.spinner("Cruzando leads com o Perfil do Banco de Dados..."):
                    with ThreadPoolExecutor(max_workers=15) as executor:
                        res = list(executor.map(lambda row: pontuar_lead(client, row, icp_ativo), df_limpo.to_dict('records')))
                    
                    s_scores = pd.Series([r['score'] for r in res])
                    df_limpo['Score_Pct'] = pd.to_numeric(s_scores, errors='coerce').fillna(0).clip(0, 100)
                    df_limpo['Justificativa'] = [r['motivo'] for r in res]
                    df_limpo['Nota_0_5'] = (df_limpo['Score_Pct'] / 20).round(1)
                    
                    st.session_state.df_final = df_limpo
                    st.session_state.processado = True
                    st.rerun()

            df_final = st.session_state.df_final
            df_show = df_final[df_final['Score_Pct'] >= min_score].copy()
            
            cols_show = [col_nome, 'Sugestão Novo Dono', col_vend, 'Data_Perda', 'Dias_Atras', col_prod, col_motivo, 'Valor_Calc', 'Nota_0_5', 'Score_Pct', 'Justificativa']
            df_export = df_show[cols_show].rename(columns={col_vend: 'Vendedor Antigo', col_prod: 'Equipamento', 'Valor_Calc': 'Valor Potencial', 'Nota_0_5': 'Nota', 'Score_Pct': 'Aderência'}).sort_values(['Nota', 'Dias_Atras'], ascending=[False, True])
            
            st.dataframe(df_export, column_config={"Sugestão Novo Dono": st.column_config.TextColumn("✨ Novo Dono"), "Nota": st.column_config.NumberColumn(format="⭐ %.1f"), "Aderência": st.column_config.ProgressColumn(format="%d%%", min_value=0, max_value=100), "Valor Potencial": st.column_config.NumberColumn(format="R$ %.2f")}, use_container_width=True)
            
            csv_buffer = io.StringIO()
            df_csv = df_export.copy()
            df_csv['Valor Potencial'] = df_csv['Valor Potencial'].apply(formatar_brl)
            df_csv['Nota'] = df_csv['Nota'].apply(lambda x: str(x).replace('.', ','))
            df_csv.to_csv(csv_buffer, index=False, sep=';', encoding='utf-8-sig')
            st.download_button("📥 Baixar CSV", csv_buffer.getvalue(), "leads_recuperacao.csv", "text/csv")
else:
    if not icp_ativo:
        st.warning("⚠️ O sistema está 'Vazio'. Suba arquivos de vendas acima para treinar a primeira versão.")
