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
    st.error("⚠️ Erro Crítico: Configure as chaves nos Segredos do Streamlit.")
    st.stop()

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

st.set_page_config(page_title="Contourline Dual Intelligence", layout="wide")
st.title("🏛️ Contourline: Dual Intelligence")

# ==========================================
# ⚙️ FUNÇÕES AUXILIARES
# ==========================================

def buscar_perfil_por_categoria(categoria):
    try:
        response = supabase.table('perfis_icp').select("*").eq('categoria', categoria).order('created_at', desc=True).limit(1).execute()
        if response.data: return response.data[0]['texto_perfil'], response.data[0]['created_at']
        return None, None
    except: return None, None

def salvar_perfil(texto, categoria, nome_arquivo):
    try:
        supabase.table('perfis_icp').insert({"texto_perfil": texto, "origem_arquivo": nome_arquivo, "categoria": categoria}).execute()
        return True
    except: return False

def limpar_csv_seguro(arquivo):
    corpo = arquivo.read().decode('utf-8-sig')
    arquivo.seek(0)
    pular = 1 if corpo.startswith('sep=') else 0
    return pd.read_csv(io.StringIO(corpo), skiprows=pular, sep=None, engine='python', dtype=str).fillna("N/A")

def converter_valor_br(valor_str):
    try:
        if pd.isna(valor_str) or str(valor_str).strip() in ["N/A", "nan", ""]: return 0.0
        limpo = str(valor_str).replace('R$', '').strip()
        if ',' in limpo: 
            limpo = limpo.replace('.', '').replace(',', '.')
        return float(limpo)
    except: return 0.0

def treinar_ia(client, arquivos, categoria):
    df_total = pd.DataFrame()
    regras_manuais = ""
    nomes = []
    
    for arq in arquivos:
        nomes.append(arq.name)
        if arq.name.endswith('.txt'):
            conteudo = arq.read().decode('utf-8')
            regras_manuais += f"\n--- REGRAS ({arq.name}) ---\n{conteudo}\n"
            arq.seek(0)
        else:
            df_temp = limpar_csv_seguro(arq)
            df_total = pd.concat([df_total, df_temp], ignore_index=True)
    
    amostra_dados = "Apenas regras manuais."
    produtos_top = ""
    
    if not df_total.empty:
        col_prod = next((c for c in df_total.columns if any(x in c.lower() for x in ['produto', 'equipamento'])), None)
        col_val = next((c for c in df_total.columns if 'valor' in c.lower()), None)
        
        produtos_top = f"Top Produtos: {df_total[col_prod].value_counts().head(5).index.tolist()}" if col_prod else ""
        if col_val: df_total['V'] = df_total[col_val].apply(converter_valor_br)
        amostra_dados = df_total.sort_values('V', ascending=False).head(50).to_dict('records') if col_val else df_total.head(50).to_dict('records')

    prompt = f"""
    Atue como Diretor Comercial da Contourline (Linha {categoria}).
    
    DADOS: {amostra_dados}
    {produtos_top}
    
    REGRAS OBRIGATÓRIAS: {regras_manuais}
    
    MISSÃO: Crie o ICP definitivo para {categoria}.
    """
    return client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}]).choices[0].message.content, ", ".join(nomes)

def pontuar_lead(client, row, icp):
    try:
        prompt = f"ICP: {icp}. LEAD: {row}. Nota 0-100. Responda: NOTA | MOTIVO CURTO."
        res = client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}]).choices[0].message.content
        parts = res.split('|')
        score_str = re.findall(r'\d+', parts[0])
        score = int(score_str[0]) if score_str else 0
        return {"score": score, "motivo": parts[1].strip() if len(parts) > 1 else res}
    except: return {"score": 0, "motivo": "Erro IA"}

def sugerir_novo_dono(atual, lista):
    cand = [v for v in lista if v != atual and v not in ["N/A", "nan"]]
    return random.choice(cand) if cand else atual

# ==========================================
# 🖥️ INTERFACE
# ==========================================
with st.sidebar:
    st.header("⚙️ Configurações")
    filtrar_duplicados = st.checkbox("Remover Duplicidade", value=True)
    st.markdown("---")
    min_score = st.slider("Régua de Aderência (%):", 0, 100, 30)

tab_med, tab_estetico = st.tabs(["🏥 UNIVERSO MED", "💆‍♀️ UNIVERSO ESTÉTICO"])

def renderizar_interface(cat_cod, cat_nome):
    perfil, data = buscar_perfil_por_categoria(cat_cod)
    
    if perfil:
        st.success(f"Cérebro {cat_nome} Ativo (Atualizado: {pd.to_datetime(data).strftime('%d/%m')})")
        with st.expander("Ver ICP"): st.write(perfil)
    else:
        st.warning(f"Cérebro {cat_nome} Vazio.")

    with st.expander(f"📚 Ensinar {cat_nome}", expanded=not perfil):
        arqs = st.file_uploader(f"Arquivos {cat_nome}", type=["csv", "txt"], accept_multiple_files=True, key=f"up_{cat_cod}")
        if arqs and st.button(f"Processar ({cat_cod})"):
            client = OpenAI(api_key=OPENAI_API_KEY)
            with st.spinner("Lendo dados..."):
                novo, nomes = treinar_ia(client, arqs, cat_nome)
                if salvar_perfil(novo, cat_cod, nomes): st.rerun()

    st.markdown("---")
    st.subheader(f"🕵️ Análise de Leads ({cat_nome})")
    
    arquivo_perdas = st.file_uploader(f"Upload Perdas {cat_nome}", type="csv", key=f"loss_{cat_cod}")
    
    if perfil and arquivo_perdas:
        client = OpenAI(api_key=OPENAI_API_KEY)
        if f'run_{cat_cod}' not in st.session_state: st.session_state[f'run_{cat_cod}'] = False
        
        # Leitura Inicial
        df_l = limpar_csv_seguro(arquivo_perdas)
        todas_colunas = list(df_l.columns)
        
        # --- MAPEAMENTO MANUAL INTELIGENTE ---
        st.info("👇 Confirme as colunas identificadas (você pode alterar se estiver errado):")
        c1, c2, c3 = st.columns(3)
        
        # Tenta adivinhar os indices iniciais
        idx_motivo = next((i for i, c in enumerate(todas_colunas) if 'motivo' in c.lower()), 0)
        idx_valor = next((i for i, c in enumerate(todas_colunas) if 'valor' in c.lower()), 0)
        # Tenta adivinhar DATA (Fechamento > Perda > Data)
        idx_data = next((i for i, c in enumerate(todas_colunas) if 'fechamento' in c.lower()), 
                   next((i for i, c in enumerate(todas_colunas) if 'perda' in c.lower()), 
                   next((i for i, c in enumerate(todas_colunas) if 'data' in c.lower()), 0)))

        with c1: c_motivo = st.selectbox("Coluna Motivo", options=todas_colunas, index=idx_motivo, key=f"s_m_{cat_cod}")
        with c2: c_val = st.selectbox("Coluna Valor", options=todas_colunas, index=idx_valor, key=f"s_v_{cat_cod}")
        with c3: c_data = st.selectbox("Coluna Data (Fechamento)", options=todas_colunas, index=idx_data, key=f"s_d_{cat_cod}")
        
        # Mapeamento Restante (Automático)
        c_nome = next((c for c in todas_colunas if any(x in c.lower() for x in ['nome', 'cliente', 'lead'])), todas_colunas[0])
        c_vend = next((c for c in todas_colunas if any(x in c.lower() for x in ['vendedor', 'responsável'])), None)
        if not c_vend: df_l['Vend'] = "N/A"; c_vend = 'Vend'
        
        # --- PROCESSAMENTO ---
        # Conversão Valor
        df_l['Valor_Real'] = df_l[c_val].apply(converter_valor_br)
        
        # Conversão Data (Blindada)
        try:
            # Tenta converter o que o usuário escolheu
            df_l[c_data] = df_l[c_data].astype(str).str.strip()
            df_l['Data_Obj'] = pd.to_datetime(df_l[c_data], dayfirst=True, errors='coerce')
            df_l['Data_Formatada'] = df_l['Data_Obj'].dt.strftime('%d/%m/%Y').fillna("-")
            
            # Mostra uma amostra para o usuário conferir
            amostra_data = df_l['Data_Formatada'].iloc[0] if len(df_l) > 0 else "-"
            st.caption(f"📅 Exemplo de data lida: {amostra_data} (Se estiver '-' verifique a coluna escolhida)")
        except:
            df_l['Data_Formatada'] = "-"

        # Filtros
        df_limpo = df_l.copy()
        removidos = 0
        if filtrar_duplicados:
            mask = df_l[c_motivo].astype(str).str.contains(r'dupli|teste|cliente|repetido|já comprei|ganho', case=False, regex=True)
            df_limpo = df_l[~mask].copy()
            removidos = len(df_l) - len(df_limpo)
        
        lista_vends = df_limpo[c_vend].dropna().unique().tolist()
        df_limpo['Novo Dono'] = df_limpo[c_vend].apply(lambda x: sugerir_novo_dono(x, lista_vends))

        # Dashboard
        k1, k2, k3 = st.columns(3)
        k1.metric("Leads Reais", len(df_limpo))
        k2.metric("Lixo Removido", removidos)
        k3.metric("Risco Financeiro", f"R$ {df_limpo['Valor_Real'].sum():,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.'))

        g1, g2 = st.columns(2)
        with g1: st.plotly_chart(px.pie(df_limpo, names=c_motivo, title="Motivos", hole=0.4), use_container_width=True)
        with g2: 
            top = df_limpo.groupby(c_motivo)['Valor_Real'].sum().nlargest(8).reset_index()
            st.plotly_chart(px.bar(top, y=c_motivo, x='Valor_Real', orientation='h', title="Gargalos Financeiros"), use_container_width=True)
        
        # IA Analysis
        if st.button(f"🚀 Analisar ({cat_nome})") or st.session_state[f'run_{cat_cod}']:
            if not st.session_state[f'run_{cat_cod}']:
                with st.spinner("IA Analisando..."):
                    with ThreadPoolExecutor(max_workers=10) as exe:
                        res = list(exe.map(lambda r: pontuar_lead(client, r, perfil), df_limpo.to_dict('records')))
                    
                    df_limpo['Score'] = [r['score'] for r in res]
                    df_limpo['Justificativa'] = [r['motivo'] for r in res]
                    s_score = pd.to_numeric(df_limpo['Score'], errors='coerce').fillna(0).clip(0, 100)
                    df_limpo['Nota'] = (s_score/20).round(1)
                    
                    st.session_state[f'data_{cat_cod}'] = df_limpo
                    st.session_state[f'run_{cat_cod}'] = True
                    st.rerun()

            final = st.session_state[f'data_{cat_cod}']
            show = final[final['Score'] >= min_score].copy()
            
            # TABELA
            cols = [c_nome, 'Novo Dono', c_vend, 'Valor_Real', 'Nota', 'Data_Formatada', 'Justificativa', c_motivo]
            # Remove duplicatas se c_motivo já estiver na lista
            cols = list(dict.fromkeys(cols))
            
            # Filtra colunas existentes
            cols_existentes = [c for c in cols if c in show.columns]

            st.dataframe(show[cols_existentes].sort_values('Nota', ascending=False), column_config={
                "Nota": st.column_config.NumberColumn(format="⭐ %.1f"),
                "Valor_Real": st.column_config.NumberColumn(format="R$ %.2f"),
                "Data_Formatada": st.column_config.TextColumn("Data")
            }, use_container_width=True)
            
            # EXCEL BRASIL
            df_export = show[cols_existentes].copy()
            df_export['Nota'] = df_export['Nota'].apply(lambda x: str(x).replace('.', ','))
            df_export['Valor_Real'] = df_export['Valor_Real'].apply(lambda x: f"{x:.2f}".replace('.', ','))
            
            csv = df_export.to_csv(sep=';', index=False, encoding='utf-8-sig')
            st.download_button(f"📥 Baixar CSV {cat_nome}", csv, f"recuperacao_{cat_cod}.csv", "text/csv")

with tab_med: renderizar_interface("MED", "MED")
with tab_estetico: renderizar_interface("ESTETICO", "ESTÉTICO")
