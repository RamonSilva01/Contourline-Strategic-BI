import streamlit as st
from openai import OpenAI
import pandas as pd
import plotly.express as px
from concurrent.futures import ThreadPoolExecutor
import io
import re

# ==========================================
# 🔐 SUA CHAVE API
OPENAI_API_KEY = "OPENAI_API_KEY" 
# ==========================================

st.set_page_config(page_title="Contourline Strategic BI", layout="wide")
st.title("🏛️ Contourline Strategic BI")

with st.sidebar:
    st.header("⚙️ Filtros")
    filtrar_duplicados = st.checkbox("Remover Duplicidade/Testes", value=True)
    st.markdown("---")
    min_score = st.slider("Mostrar aderência acima de (%):", 0, 100, 30)

# --- ENGENHARIA DE DADOS ---

def limpar_csv_seguro(arquivo):
    """Lê o CSV garantindo Texto para não quebrar números"""
    corpo = arquivo.read().decode('utf-8-sig')
    arquivo.seek(0)
    pular = 1 if corpo.startswith('sep=') else 0
    return pd.read_csv(io.StringIO(corpo), skiprows=pular, sep=None, engine='python', dtype=str).fillna("N/A")

def converter_valor_br(valor_str):
    """Transforma 1.000,00 em 1000.00"""
    try:
        if pd.isna(valor_str) or valor_str in ["N/A", "nan", ""]: return 0.0
        limpo = str(valor_str).replace('R$', '').strip()
        if ',' in limpo:
            limpo = limpo.replace('.', '').replace(',', '.')
        return float(limpo)
    except:
        return 0.0

def formatar_brl(valor_float):
    """Devolve 1000.00 para 1.000,00"""
    return f"{valor_float:.2f}".replace('.', ',')

def extrair_icp(client, df):
    col_prod = next((c for c in df.columns if any(x in c.lower() for x in ['produto', 'item', 'equipamento'])), None)
    produtos_top = ""
    if col_prod:
        top3 = df[col_prod].value_counts().head(3).index.tolist()
        produtos_top = f" Produtos mais vendidos: {top3}."

    col_val = next((c for c in df.columns if 'valor' in c.lower()), None)
    df_sample = df.copy()
    if col_val:
        df_sample['V_Calc'] = df_sample[col_val].apply(converter_valor_br)
        amostra = df_sample.sort_values(by='V_Calc', ascending=False).head(20).to_dict('records')
    else:
        amostra = df_sample.head(20).to_dict('records')
        
    prompt = f"Analise vendas (GABARITO): {amostra}. {produtos_top} Crie um PERFIL DE CLIENTE IDEAL resumido."
    return client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}]).choices[0].message.content

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

c1, c2 = st.columns(2)
with c1: arq_ganhos = st.file_uploader("1. CSV VENDAS", type="csv", key="w")
with c2: arq_perdas = st.file_uploader("2. CSV PERDAS", type="csv", key="l")

if arq_ganhos and arq_perdas:
    client = OpenAI(api_key=OPENAI_API_KEY)
    
    if 'processado' not in st.session_state: st.session_state.processado = False

    # --- PRÉ-PROCESSAMENTO ---
    df_l = limpar_csv_seguro(arq_perdas)
    
    # Mapeamento Inteligente
    col_motivo = next((c for c in df_l.columns if 'motivo' in c.lower()), "Motivo")
    col_valor = next((c for c in df_l.columns if 'valor' in c.lower()), None)
    col_nome = next((c for c in df_l.columns if any(x in c.lower() for x in ['nome', 'cliente'])), "Lead")
    col_prod = next((c for c in df_l.columns if any(x in c.lower() for x in ['produto', 'equipamento', 'item', 'tecnologia'])), None)
    
    # NOVO: Mapeamento de Vendedor
    col_vend = next((c for c in df_l.columns if any(x in c.lower() for x in ['vendedor', 'responsável', 'responsavel', 'owner', 'proprietário'])), None)

    if not col_prod:
        df_l['Equipamento_Interesse'] = "N/A"
        col_prod = 'Equipamento_Interesse'
    
    if not col_vend:
        df_l['Vendedor_Resp'] = "N/A"
        col_vend = 'Vendedor_Resp'

    # Conversão de Valor
    if col_valor:
        df_l['Valor_Calc'] = df_l[col_valor].apply(converter_valor_br)
    else:
        df_l['Valor_Calc'] = 0.0

    # Filtros
    total_bruto = len(df_l)
    if filtrar_duplicados:
        mask_lixo = df_l[col_motivo].astype(str).str.contains(r'dupli|teste|cliente|repetido', case=False, regex=True)
        df_limpo = df_l[~mask_lixo].copy()
    else:
        df_limpo = df_l.copy()
        
    total_limpo = len(df_limpo)
    removidos = total_bruto - total_limpo

    # --- DASHBOARD ---
    st.markdown("### 🔍 Raio-X Financeiro")
    k1, k2, k3 = st.columns(3)
    k1.metric("Total de Leads", total_bruto)
    k2.metric("Removidos (Lixo)", removidos, delta_color="inverse")
    k3.metric("Capital Real em Risco", f"R$ {df_limpo['Valor_Calc'].sum():,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.'))

    g1, g2 = st.columns(2)
    with g1: st.plotly_chart(px.pie(df_limpo, names=col_motivo, title="Motivos (Volume)", hole=0.4), use_container_width=True)
    with g2: 
        top_fin = df_limpo.groupby(col_motivo)['Valor_Calc'].sum().nlargest(8).reset_index()
        st.plotly_chart(px.bar(top_fin, y=col_motivo, x='Valor_Calc', orientation='h', title="Gargalos (R$)"), use_container_width=True)

    # --- IA ---
    st.markdown("---")
    if st.button("🚀 Iniciar Scoring Completo") or st.session_state.processado:
        
        if not st.session_state.processado:
            with st.spinner("Analisando perfil, valores e vendedores..."):
                df_w = limpar_csv_seguro(arq_ganhos)
                icp = extrair_icp(client, df_w)
                st.session_state.icp = icp
                
                with ThreadPoolExecutor(max_workers=15) as executor:
                    res = list(executor.map(lambda row: pontuar_lead(client, row, icp), df_limpo.to_dict('records')))
                
                df_limpo['Score_Pct'] = [r['score'] for r in res]
                df_limpo['Justificativa'] = [r['motivo'] for r in res]
                
                # Trava de Segurança
                df_limpo['Score_Pct'] = pd.to_numeric(df_limpo['Score_Pct'], errors='coerce').fillna(0).clip(0, 100)
                df_limpo['Nota_0_5'] = (df_limpo['Score_Pct'] / 20).round(1)
                
                st.session_state.df_final = df_limpo
                st.session_state.processado = True
                st.rerun()

        # --- TELA FINAL ---
        df_final = st.session_state.df_final
        icp = st.session_state.icp
        
        st.success(f"🧠 **Perfil Ideal:** {icp}")
        
        df_show = df_final[df_final['Score_Pct'] >= min_score].copy()
        
        # Seleção de Colunas (Agora com Vendedor)
        cols_show = [col_nome, col_vend, col_prod, col_motivo, 'Valor_Calc', 'Nota_0_5', 'Score_Pct', 'Justificativa']
        
        df_export = df_show[cols_show].rename(columns={
            col_vend: 'Vendedor',
            col_prod: 'Equipamento', 
            'Valor_Calc': 'Valor Potencial',
            'Nota_0_5': 'Nota (0-5)',
            'Score_Pct': 'Aderência (%)'
        }).sort_values(['Nota (0-5)', 'Valor Potencial'], ascending=False)
        
        st.dataframe(
            df_export,
            column_config={
                "Nota (0-5)": st.column_config.NumberColumn(format="⭐ %.1f"),
                "Aderência (%)": st.column_config.ProgressColumn(format="%d%%", min_value=0, max_value=100),
                "Valor Potencial": st.column_config.NumberColumn(format="R$ %.2f")
            },
            use_container_width=True
        )
        
        # --- DOWNLOAD ---
        csv_buffer = io.StringIO()
        df_csv = df_export.copy()
        
        # Formatação BRL Final
        df_csv['Valor Potencial'] = df_csv['Valor Potencial'].apply(formatar_brl)
        df_csv['Nota (0-5)'] = df_csv['Nota (0-5)'].apply(lambda x: str(x).replace('.', ','))
        
        df_csv.to_csv(csv_buffer, index=False, sep=';', encoding='utf-8-sig')
        st.download_button("📥 Baixar CSV Completo (Vendedor + Equipamento)", csv_buffer.getvalue(), "bi_vendedor_v53.csv", "text/csv")