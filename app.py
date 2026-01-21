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
st.title("🏛️ Contourline: Dual Intelligence")

# ==========================================
# ⚙️ FUNÇÕES AUXILIARES (AJUSTADAS)
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
    """Lê tratando a linha sep= do RD Station/Excel"""
    corpo = arquivo.read().decode('utf-8-sig')
    arquivo.seek(0)
    pular = 1 if corpo.startswith('sep=') else 0
    return pd.read_csv(io.StringIO(corpo), skiprows=pular, sep=None, engine='python', dtype=str).fillna("N/A")

def converter_valor_br(valor_str):
    """
    Corrige o erro de 400mil virar 4milhões.
    Remove apenas os pontos de milhar e troca vírgula por ponto.
    """
    try:
        if pd.isna(valor_str) or str(valor_str).strip() in ["N/A", "nan", ""]: return 0.0
        # Limpa R$ e espaços
        limpo = str(valor_str).replace('R$', '').strip()
        
        # Lógica rigorosa BR: Se tem vírgula, assume que é decimal
        if ',' in limpo:
            limpo = limpo.replace('.', '') # Remove ponto de milhar (4.000 -> 4000)
            limpo = limpo.replace(',', '.') # Troca vírgula por ponto (4000,00 -> 4000.00)
        
        return float(limpo)
    except: return 0.0

def formatar_para_excel(valor):
    """Transforma 3.5 em '3,5' para o Excel brasileiro não ler errado"""
    if pd.isna(valor): return ""
    return str(valor).replace('.', ',')

def processar_data(data_str):
    """Tenta ler a data em vários formatos"""
    if pd.isna(data_str) or str(data_str) in ["N/A", "nan", ""]: return None
    formatos = ['%d/%m/%Y', '%d/%m/%Y %H:%M', '%Y-%m-%d', '%Y-%m-%d %H:%M:%S']
    data_limpa = str(data_str).split('.')[0] # Remove milisegundos
    for fmt in formatos:
        try: return datetime.strptime(data_limpa, fmt)
        except ValueError: continue
    return None

def treinar_ia(client, arquivos, categoria):
    df_total = pd.DataFrame()
    nomes = []
    for arq in arquivos:
        df_total = pd.concat([df_total, limpar_csv_seguro(arq)], ignore_index=True)
        nomes.append(arq.name)
    
    col_prod = next((c for c in df_total.columns if any(x in c.lower() for x in ['produto', 'equipamento'])), None)
    col_val = next((c for c in df_total.columns if 'valor' in c.lower()), None)
    
    produtos_top = f"Top Produtos: {df_total[col_prod].value_counts().head(5).index.tolist()}" if col_prod else ""
    if col_val: df_total['V'] = df_total[col_val].apply(converter_valor_br)
    
    amostra = df_total.sort_values('V', ascending=False).head(40).to_dict('records') if col_val else df_total.head(40).to_dict('records')
    
    prompt = f"Analise vendas {categoria} da Contourline: {amostra}. {produtos_top}. Crie um ICP robusto."
    return client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}]).choices[0].message.content, ", ".join(nomes)

def pontuar_lead(client, row, icp):
    try:
        prompt = f"ICP: {icp}. LEAD: {row}. Nota 0-100. Responda: NOTA | MOTIVO."
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
        with st.expander("Ver Perfil ICP"): st.write(perfil)
    else:
        st.warning(f"Cérebro {cat_nome} Vazio.")

    with st.expander(f"📚 Treinar {cat_nome}", expanded=not perfil):
        arqs = st.file_uploader(f"Vendas {cat_nome}", type="csv", accept_multiple_files=True, key=f"up_{cat_cod}")
        if arqs and st.button(f"Treinar ({cat_cod})"):
            client = OpenAI(api_key=OPENAI_API_KEY)
            with st.spinner("Treinando..."):
                novo, nomes = treinar_ia(client, arqs, cat_nome)
                if salvar_perfil(novo, cat_cod, nomes): st.rerun()

    st.markdown("---")
    st.subheader(f"🕵️ Análise de Leads ({cat_nome})")
    
    arquivo_perdas = st.file_uploader(f"Upload Perdas {cat_nome}", type="csv", key=f"loss_{cat_cod}")
    
    if perfil and arquivo_perdas:
        client = OpenAI(api_key=OPENAI_API_KEY)
        if f'run_{cat_cod}' not in st.session_state: st.session_state[f'run_{cat_cod}'] = False
        
        # 1. Leitura
        df_l = limpar_csv_seguro(arquivo_perdas)
        cols = df_l.columns
        
        # 2. Mapeamento Automático
        c_motivo = next((c for c in cols if 'motivo' in c.lower()), None)
        c_val = next((c for c in cols if 'valor' in c.lower()), None)
        c_nome = next((c for c in cols if any(x in c.lower() for x in ['nome', 'cliente', 'lead'])), cols[0])
        c_vend = next((c for c in cols if any(x in c.lower() for x in ['vendedor', 'responsável'])), None)
        # NOVO: Mapeamento de Data
        c_data = next((c for c in cols if any(x in c.lower() for x in ['data', 'date', 'criado', 'created', 'perda', 'fechamento'])), None)
        
        if not c_vend: df_l['Vend'] = "N/A"; c_vend = 'Vend'
        
        # 3. Tratamento de Dados
        df_l['Valor_Real'] = df_l[c_val].apply(converter_valor_br) if c_val else 0.0
        
        # Tratamento da Data (NOVO)
        if c_data:
            df_l['Data_Formatada'] = df_l[c_data].apply(processar_data).apply(lambda x: x.strftime('%d/%m/%Y') if x else "-")
        else:
            df_l['Data_Formatada'] = "-"

        # 4. Filtro de Duplicidade
        df_limpo = df_l.copy()
        removidos = 0
        if filtrar_duplicados and c_motivo:
            mask = df_l[c_motivo].astype(str).str.contains(r'dupli|teste|cliente|repetido|já comprei', case=False, regex=True)
            df_limpo = df_l[~mask].copy()
            removidos = len(df_l) - len(df_limpo)
        
        # Rotação
        lista_vends = df_limpo[c_vend].dropna().unique().tolist()
        df_limpo['Novo Dono'] = df_limpo[c_vend].apply(lambda x: sugerir_novo_dono(x, lista_vends))

        # 5. Dashboard
        k1, k2, k3 = st.columns(3)
        k1.metric("Leads", len(df_limpo))
        k2.metric("Lixo Removido", removidos)
        k3.metric("Risco Financeiro", f"R$ {df_limpo['Valor_Real'].sum():,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.'))

        g1, g2 = st.columns(2)
        if c_motivo:
            with g1: st.plotly_chart(px.pie(df_limpo, names=c_motivo, title="Motivos", hole=0.4), use_container_width=True)
            with g2: 
                top = df_limpo.groupby(c_motivo)['Valor_Real'].sum().nlargest(8).reset_index()
                st.plotly_chart(px.bar(top, y=c_motivo, x='Valor_Real', orientation='h', title="Gargalos Financeiros"), use_container_width=True)
        
        # 6. IA Analysis
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
            
            # Montagem da Tabela Final
            cols = [c_nome, 'Novo Dono', c_vend, 'Valor_Real', 'Nota', 'Data_Formatada', 'Justificativa']
            if c_motivo: cols.insert(3, c_motivo)
            
            # Exibição (Streamlit usa ponto normal)
            st.dataframe(show[cols].sort_values('Nota', ascending=False), column_config={
                "Nota": st.column_config.NumberColumn(format="⭐ %.1f"),
                "Valor_Real": st.column_config.NumberColumn(format="R$ %.2f"),
                "Data_Formatada": st.column_config.TextColumn("Data Perda")
            }, use_container_width=True)
            
            # --- PREPARAÇÃO PARA EXCEL (AQUI É A MÁGICA) ---
            df_export = show[cols].copy()
            
            # Força vírgula para o Excel entender como número decimal no Brasil
            df_export['Nota'] = df_export['Nota'].apply(formatar_para_excel)
            df_export['Valor_Real'] = df_export['Valor_Real'].apply(lambda x: f"{x:.2f}".replace('.', ','))
            
            csv = df_export.to_csv(sep=';', index=False, encoding='utf-8-sig')
            st.download_button(f"📥 Baixar CSV {cat_nome}", csv, f"recuperacao_{cat_cod}.csv", "text/csv")

with tab_med: renderizar_interface("MED", "MED")
with tab_estetico: renderizar_interface("ESTETICO", "ESTÉTICO")
