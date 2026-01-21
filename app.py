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
st.title("🏛️ Contourline: Dual Intelligence v60")

# ==========================================
# ⚙️ BARRA LATERAL (RESTAUROU OS FILTROS!)
# ==========================================
with st.sidebar:
    st.header("⚙️ Configurações Globais")
    st.info("Estes filtros aplicam-se a ambas as abas (Med e Estético).")
    
    # Filtro 1: Duplicidade
    filtrar_duplicados = st.checkbox("Remover Duplicidade/Testes", value=True, help="Remove leads marcados como teste, duplicado ou já cliente.")
    
    # Filtro 2: Régua
    st.markdown("---")
    min_score = st.slider("Régua de Aderência Mínima (%):", 0, 100, 30, help="Leads com nota abaixo disso serão ocultos na tabela final.")

# ==========================================
# ⚙️ FUNÇÕES DE BANCO DE DADOS
# ==========================================

def buscar_perfil_por_categoria(categoria):
    try:
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
    try:
        dados = {"texto_perfil": texto, "origem_arquivo": nome_arquivo, "categoria": categoria}
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
    Crie um PERFIL DE CLIENTE IDEAL (ICP) robusto para este segmento.
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
        prompt = f"ICP (Referência): {icp}. LEAD (Analisar): {row}. Nota 0-100. Responda: NOTA | MOTIVO."
        res = client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}]).choices[0].message.content
        parts = res.split('|')
        return {"score": extrair_nota_segura(parts[0]), "motivo": parts[1].strip() if len(parts) > 1 else res}
    except: return {"score": 0, "motivo": "Erro"}

# ==========================================
# 🖥️ INTERFACE PRINCIPAL
# ==========================================

tab_med, tab_estetico = st.tabs(["🏥 UNIVERSO MED", "💆‍♀️ UNIVERSO ESTÉTICO"])

def renderizar_interface(categoria_cod, categoria_nome):
    
    # 1. Busca memória
    perfil, data = buscar_perfil_por_categoria(categoria_cod)
    
    col_status, col_upload = st.columns([1, 2])
    with col_status:
        if perfil:
            st.success(f"**Cérebro {categoria_nome} Ativo**\n\n📅 {pd.to_datetime(data).strftime('%d/%m/%Y')}")
            with st.expander("Ver ICP"): st.write(perfil)
        else:
            st.warning(f"⚠️ Cérebro Vazio.")

    # 2. Treinamento
    with st.expander(f"📚 Treinar Perfil {categoria_nome}", expanded=not perfil):
        st.info(f"Suba vendas de **{categoria_nome}**.")
        arquivos_venda = st.file_uploader(f"Vendas {categoria_nome}", type="csv", accept_multiple_files=True, key=f"v_{categoria_cod}")
        if arquivos_venda and st.button(f"Treinar IA ({categoria_nome})", key=f"bt_tr_{categoria_cod}"):
            client = OpenAI(api_key=OPENAI_API_KEY)
            with st.spinner("Treinando..."):
                novo, nomes = treinar_ia(client, arquivos_venda, categoria_nome)
                if salvar_perfil(novo, categoria_cod, nomes):
                    st.success("Salvo!"); st.rerun()

    st.markdown("---")
    st.subheader(f"🕵️ Recuperação de Leads ({categoria_nome})")
    
    arquivo_perdas = st.file_uploader(f"Upload Leads Perdidos {categoria_nome}", type="csv", key=f"p_{categoria_cod}")
    
    if perfil and arquivo_perdas:
        client = OpenAI(api_key=OPENAI_API_KEY)
        if f'proc_{categoria_cod}' not in st.session_state: st.session_state[f'proc_{categoria_cod}'] = False
        
        # --- PROCESSAMENTO E LIMPEZA (AQUI ESTAVA O PROBLEMA) ---
        df_l = limpar_csv_seguro(arquivo_perdas)
        
        # Mapeamento
        col_motivo = next((c for c in df_l.columns if 'motivo' in c.lower()), "Motivo")
        col_val = next((c for c in df_l.columns if 'valor' in c.lower()), None)
        col_nome = next((c for c in df_l.columns if any(x in c.lower() for x in ['nome', 'cliente'])), "Lead")
        col_vend = next((c for c in df_l.columns if any(x in c.lower() for x in ['vendedor', 'responsável'])), None)
        
        if not col_vend: df_l['Vendedor_Orig'] = "N/A"; col_vend = 'Vendedor_Orig'
        
        # Conversão de Valor
        df_l['Valor_Calc'] = df_l[col_val].apply(converter_valor_br) if col_val else 0.0
        
        # --- APLICAÇÃO DO FILTRO DE DUPLICIDADE (RESTAURADO) ---
        if filtrar_duplicados:
            mask_lixo = df_l[col_motivo].astype(str).str.contains(r'dupli|teste|cliente|repetido|já comprei', case=False, regex=True)
            df_limpo = df_l[~mask_lixo].copy()
            removidos = len(df_l) - len(df_limpo)
        else:
            df_limpo = df_l.copy()
            removidos = 0
            
        # Rotação
        lista_vendedores = df_limpo[col_vend].dropna().unique().tolist()
        df_limpo['Sugestão Novo Dono'] = df_limpo[col_vend].apply(lambda x: sugerir_novo_dono(x, lista_vendedores))

        # --- DASHBOARD (RESTAURADO) ---
        k1, k2, k3 = st.columns(3)
        k1.metric("Leads Únicos", len(df_limpo))
        k2.metric("Removidos (Duplicados)", removidos, delta_color="inverse")
        k3.metric("Valor em Risco", f"R$ {df_limpo['Valor_Calc'].sum():,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.'))
        
        g1, g2 = st.columns(2)
        with g1: st.plotly_chart(px.pie(df_limpo, names=col_motivo, title="Motivos", hole=0.4), use_container_width=True)
        with g2: 
            top_fin = df_limpo.groupby(col_motivo)['Valor_Calc'].sum().nlargest(8).reset_index()
            st.plotly_chart(px.bar(top_fin, y=col_motivo, x='Valor_Calc', orientation='h', title="Gargalos Financeiros"), use_container_width=True)
        
        # --- BOTÃO DE AÇÃO ---
        if st.button(f"🚀 Analisar Leads ({categoria_nome})", key=f"bt_go_{categoria_cod}") or st.session_state[f'proc_{categoria_cod}']:
            if not st.session_state[f'proc_{categoria_cod}']:
                with st.spinner(f"Comparando com Perfil {categoria_nome}..."):
                    with ThreadPoolExecutor(max_workers=15) as executor:
                        res = list(executor.map(lambda row: pontuar_lead(client, row, perfil), df_limpo.to_dict('records')))
                    
                    s_scores = pd.Series([r['score'] for r in res])
                    df_limpo['Score_Pct'] = pd.to_numeric(s_scores, errors='coerce').fillna(0).clip(0, 100)
                    df_limpo['Justificativa'] = [r['motivo'] for r in res]
                    df_limpo['Nota'] = (df_limpo['Score_Pct'] / 20).round(1)
                    
                    st.session_state[f'df_{categoria_cod}'] = df_limpo
                    st.session_state[f'proc_{categoria_cod}'] = True
                    st.rerun()

            # Resultado
            df_final = st.session_state[f'df_{categoria_cod}']
            
            # --- APLICAÇÃO DO FILTRO DA RÉGUA (RESTAURADO) ---
            df_show = df_final[df_final['Score_Pct'] >= min_score].copy()
            ocultos = len(df_final) - len(df_show)
            if ocultos > 0: st.warning(f"⚠️ {ocultos} leads ocultos pela régua (<{min_score}%).")
            
            # Tabela
            cols_show = [c for c in [col_nome, 'Sugestão Novo Dono', col_vend, 'Valor_Calc', 'Nota', 'Score_Pct', 'Justificativa'] if c in df_show.columns]
            df_export = df_show[cols_show].sort_values(['Nota'], ascending=False)
            
            st.dataframe(df_export, column_config={
                "Nota": st.column_config.NumberColumn(format="⭐ %.1f"),
                "Score_Pct": st.column_config.ProgressColumn(format="%d%%", min_value=0, max_value=100),
                "Valor_Calc": st.column_config.NumberColumn(format="R$ %.2f")
            }, use_container_width=True)
            
            csv = df_export.to_csv(sep=';', index=False, encoding='utf-8-sig')
            st.download_button(f"📥 Baixar CSV {categoria_nome}", csv, f"recuperacao_{categoria_cod}.csv", "text/csv")

# --- EXECUÇÃO ---
with tab_med: renderizar_interface("MED", "MED")
with tab_estetico: renderizar_interface("ESTETICO", "ESTÉTICO")
