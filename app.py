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
# 🔐 AUTENTICAÇÃO
# ==========================================
try:
    OPENAI_API_KEY = st.secrets["OPENAI_API_KEY"]
    SUPABASE_URL = st.secrets["SUPABASE_URL"]
    SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
except:
    st.error("⚠️ Erro: Configure as chaves nos Segredos do Streamlit.")
    st.stop()

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

st.set_page_config(page_title="Contourline Dual Intelligence", layout="wide")
st.title("🏛️ Contourline: Dual Intelligence v59")

# ==========================================
# ⚙️ FUNÇÕES DE BANCO DE DADOS (DUAL CORE)
# ==========================================

def buscar_perfil_por_categoria(categoria):
    """Busca o perfil MED ou ESTETICO mais recente"""
    try:
        # Filtra pela coluna 'categoria'
        response = supabase.table('perfis_icp')\
            .select("*")\
            .eq('categoria', categoria)\
            .order('created_at', desc=True)\
            .limit(1).execute()
        
        if response.data and len(response.data) > 0:
            return response.data[0]['texto_perfil'], response.data[0]['created_at']
        return None, None
    except Exception as e:
        st.error(f"Erro no Banco ({categoria}): {e}")
        return None, None

def salvar_perfil(texto, categoria, nome_arquivo="Upload Manual"):
    """Salva com a etiqueta correta (MED ou ESTETICO)"""
    try:
        dados = {
            "texto_perfil": texto,
            "origem_arquivo": nome_arquivo,
            "categoria": categoria
        }
        supabase.table('perfis_icp').insert(dados).execute()
        return True
    except Exception as e:
        st.error(f"Erro ao salvar: {e}")
        return False

# ==========================================
# 🛠️ FUNÇÕES DE ENGENHARIA
# ==========================================

def limpar_csv_seguro(arquivo):
    corpo = arquivo.read().decode('utf-8-sig')
    return pd.read_csv(io.StringIO(corpo), sep=None, engine='python', dtype=str).fillna("N/A")

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
    formatos = ['%d/%m/%Y', '%d/%m/%Y %H:%M', '%Y-%m-%d']
    data_limpa = str(data_str).split('.')[0]
    for fmt in formatos:
        try: return datetime.strptime(data_limpa, fmt)
        except ValueError: continue
    return None

def calcular_dias(data_obj):
    if not data_obj: return 9999
    return (datetime.now() - data_obj).days

def treinar_ia(client, lista_arquivos, categoria_nome):
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
    Analise esta base de vendas do segmento {categoria_nome} da Contourline: {amostra}. 
    {produtos_top}
    Crie um PERFIL DE CLIENTE IDEAL (ICP) robusto para este segmento específico.
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
        prompt = f"ICP (Referência): {icp}. LEAD (Analisar): {row}. Nota 0-100 de aderência. Responda: NOTA | MOTIVO."
        res = client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}]).choices[0].message.content
        parts = res.split('|')
        return {"score": extrair_nota_segura(parts[0]), "motivo": parts[1].strip() if len(parts) > 1 else res}
    except: return {"score": 0, "motivo": "Erro"}

# ==========================================
# 🖥️ INTERFACE PRINCIPAL (AS ABAS)
# ==========================================

# Criação das abas gigantes para separar os mundos
tab_med, tab_estetico = st.tabs(["🏥 UNIVERSO MED (Médicos)", "💆‍♀️ UNIVERSO ESTÉTICO (Clínicas)"])

def renderizar_interface(categoria_cod, categoria_nome, icone):
    """Função que desenha a tela inteira dependendo da aba escolhida"""
    
    # 1. Busca memória específica desta categoria
    perfil, data = buscar_perfil_por_categoria(categoria_cod)
    
    col_status, col_upload = st.columns([1, 2])
    
    with col_status:
        if perfil:
            st.success(f"**Cérebro {categoria_nome} Ativo**\n\nÚltimo treino: {pd.to_datetime(data).strftime('%d/%m/%Y')}")
            with st.expander(f"Ver ICP {categoria_nome}"):
                st.write(perfil)
        else:
            st.warning(f"⚠️ Cérebro {categoria_nome} Vazio. Precisa treinar!")

    # 2. Área de Treinamento (Só para essa categoria)
    with st.expander(f"📚 Treinar/Atualizar Perfil {categoria_nome}", expanded=not perfil):
        st.info(f"Suba aqui apenas as VENDAS CONCLUÍDAS de **{categoria_nome}**.")
        arquivos_venda = st.file_uploader(f"Upload Vendas {categoria_nome}", type="csv", accept_multiple_files=True, key=f"vendas_{categoria_cod}")
        
        if arquivos_venda:
            if st.button(f"Processar e Salvar ({categoria_nome})", key=f"bt_treino_{categoria_cod}"):
                client = OpenAI(api_key=OPENAI_API_KEY)
                with st.spinner(f"Criando inteligência para {categoria_nome}..."):
                    novo_perfil, nomes = treinar_ia(client, arquivos_venda, categoria_nome)
                    if salvar_perfil(novo_perfil, categoria_cod, nomes):
                        st.success("Salvo no banco com sucesso!")
                        st.rerun()

    st.markdown(f"### 🕵️ Analisar Leads Perdidos ({categoria_nome})")
    st.caption(f"Os leads que você subir aqui serão comparados EXCLUSIVAMENTE com o padrão {categoria_nome}.")
    
    arquivo_perdas = st.file_uploader(f"Upload Perdas {categoria_nome}", type="csv", key=f"perdas_{categoria_cod}")
    
    # Só libera análise se tiver perfil no banco
    if perfil and arquivo_perdas:
        client = OpenAI(api_key=OPENAI_API_KEY)
        if f'proc_{categoria_cod}' not in st.session_state: st.session_state[f'proc_{categoria_cod}'] = False
        
        # Leitura e Tratamento (Padrão para ambas as abas)
        df_l = limpar_csv_seguro(arquivo_perdas)
        col_val = next((c for c in df_l.columns if 'valor' in c.lower()), None)
        col_vend = next((c for c in df_l.columns if any(x in c.lower() for x in ['vendedor', 'responsável'])), None)
        
        if not col_vend: df_l['Vendedor_Orig'] = "N/A"; col_vend = 'Vendedor_Orig'
        df_l['Valor_Calc'] = df_l[col_val].apply(converter_valor_br) if col_val else 0.0
        
        lista_vendedores = df_l[col_vend].dropna().unique().tolist()
        df_l['Sugestão Novo Dono'] = df_l[col_vend].apply(lambda x: sugerir_novo_dono(x, lista_vendedores))

        # Dashboard rápido
        k1, k2 = st.columns(2)
        k1.metric("Leads para Recuperar", len(df_l))
        k2.metric("Valor em Risco", f"R$ {df_l['Valor_Calc'].sum():,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.'))
        
        if st.button(f"🚀 Iniciar Recuperação {categoria_nome}", key=f"bt_proc_{categoria_cod}") or st.session_state[f'proc_{categoria_cod}']:
            if not st.session_state[f'proc_{categoria_cod}']:
                with st.spinner(f"Aplicando filtro {categoria_nome}..."):
                    with ThreadPoolExecutor(max_workers=15) as executor:
                        res = list(executor.map(lambda row: pontuar_lead(client, row, perfil), df_l.to_dict('records')))
                    
                    s_scores = pd.Series([r['score'] for r in res])
                    df_l['Score_Pct'] = pd.to_numeric(s_scores, errors='coerce').fillna(0).clip(0, 100)
                    df_l['Justificativa'] = [r['motivo'] for r in res]
                    df_l['Nota'] = (df_l['Score_Pct'] / 20).round(1)
                    
                    st.session_state[f'df_{categoria_cod}'] = df_l
                    st.session_state[f'proc_{categoria_cod}'] = True
                    st.rerun()

            # Resultado
            df_final = st.session_state[f'df_{categoria_cod}']
            df_show = df_final[df_final['Score_Pct'] >= 30].copy() # Filtro padrão 30%
            
            # Exibição
            cols_show = [c for c in ['Nome', 'Lead', 'Cliente'] if c in df_show.columns]
            col_nome = cols_show[0] if cols_show else df_show.columns[0]
            
            df_export = df_show[[col_nome, 'Sugestão Novo Dono', col_vend, 'Valor_Calc', 'Nota', 'Score_Pct', 'Justificativa']].sort_values(['Nota'], ascending=False)
            
            st.dataframe(df_export, use_container_width=True)
            
            csv = df_export.to_csv(sep=';', index=False, encoding='utf-8-sig')
            st.download_button(f"📥 Baixar CSV {categoria_nome}", csv, f"recuperacao_{categoria_cod}.csv", "text/csv")

# --- EXECUÇÃO DAS ABAS ---
with tab_med:
    renderizar_interface("MED", "MED", "🏥")

with tab_estetico:
    renderizar_interface("ESTETICO", "ESTÉTICO", "💆‍♀️")
