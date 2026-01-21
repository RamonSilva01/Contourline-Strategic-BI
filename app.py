import streamlit as st
from openai import OpenAI
import pandas as pd
import plotly.express as px
from concurrent.futures import ThreadPoolExecutor
import io
import re
from datetime import datetime

# ==========================================
# 🔐 SUA CHAVE API (Mantenha st.secrets se já configurou)
# Se estiver rodando local sem segredos, cole a chave aqui.
OPENAI_API_KEY = st.secrets["OPENAI_API_KEY"]
# ==========================================

st.set_page_config(page_title="Contourline Chrono BI", layout="wide")
st.title("🏛️ Contourline: Chrono BI")

with st.sidebar:
    st.header("⚙️ Filtros")
    filtrar_duplicados = st.checkbox("Remover Duplicidade/Testes", value=True)
    st.markdown("---")
    min_score = st.slider("Mostrar aderência acima de (%):", 0, 100, 30)

# --- ENGENHARIA DE DADOS ---

def limpar_csv_seguro(arquivo):
    """Lê garantindo texto para não quebrar datas ou números"""
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
    """Tenta entender datas do RD Station/Excel e converter para objeto Data"""
    if pd.isna(data_str) or data_str in ["N/A", "nan", ""]: return None
    
    formatos = [
        '%d/%m/%Y', '%d/%m/%Y %H:%M', '%Y-%m-%d', '%Y-%m-%d %H:%M:%S',
        '%d-%m-%Y', '%m/%d/%Y'
    ]
    
    data_limpa = str(data_str).split('.')[0] # Remove milissegundos se houver
    
    for fmt in formatos:
        try:
            return datetime.strptime(data_limpa, fmt)
        except ValueError:
            continue
    return None

def calcular_dias(data_obj):
    if not data_obj: return 9999 # Se não tiver data, joga pro fim da fila
    delta = datetime.now() - data_obj
    return delta.days

def extrair_icp(client, df):
    col_prod = next((c for c in df.columns if any(x in c.lower() for x in ['produto', 'equipamento'])), None)
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
    col_prod = next((c for c in df_l.columns if any(x in c.lower() for x in ['produto', 'equipamento', 'item'])), None)
    col_vend = next((c for c in df_l.columns if any(x in c.lower() for x in ['vendedor', 'responsável', 'owner'])), None)
    
    # NOVO: Mapeamento de Data (Perda/Fechamento)
    col_data = next((c for c in df_l.columns if any(x in c.lower() for x in ['fechamento', 'perda', 'closing', 'data fim', 'data ganho'])), None)

    # Preenche colunas faltantes
    if not col_prod: df_l['Equipamento'] = "N/A"; col_prod = 'Equipamento'
    if not col_vend: df_l['Vendedor'] = "N/A"; col_vend = 'Vendedor'
    
    # Processamento de Valor
    if col_valor: df_l['Valor_Calc'] = df_l[col_valor].apply(converter_valor_br)
    else: df_l['Valor_Calc'] = 0.0

    # Processamento de DATA (A Mágica da v54)
    if col_data:
        # Cria objeto data real
        df_l['Data_Obj'] = df_l[col_data].apply(processar_data)
        # Calcula dias passados
        df_l['Dias_Atras'] = df_l['Data_Obj'].apply(calcular_dias)
        # Formata bonito para leitura (DD/MM/AAAA)
        df_l['Data_Formatada'] = df_l['Data_Obj'].apply(lambda x: x.strftime('%d/%m/%Y') if x else "Sem Data")
    else:
        df_l['Data_Formatada'] = "N/A"
        df_l['Dias_Atras'] = 9999

    # Filtros
    total_bruto = len(df_l)
    if filtrar_duplicados:
        mask_lixo = df_l[col_motivo].astype(str).str.contains(r'dupli|teste|cliente|repetido', case=False, regex=True)
        df_limpo = df_l[~mask_lixo].copy()
    else:
        df_limpo = df_l.copy()
        
    removidos = total_bruto - len(df_limpo)

    # --- DASHBOARD ---
    st.markdown("### 🔍 Raio-X Financeiro & Temporal")
    k1, k2, k3 = st.columns(3)
    k1.metric("Leads Únicos", len(df_limpo))
    k2.metric("Removidos", removidos, delta_color="inverse")
    k3.metric("Capital em Risco", f"R$ {df_limpo['Valor_Calc'].sum():,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.'))

    g1, g2 = st.columns(2)
    with g1: st.plotly_chart(px.pie(df_limpo, names=col_motivo, title="Motivos (Volume)", hole=0.4), use_container_width=True)
    with g2: 
        # Gráfico Temporal: Perdas por Mês (Se houver data)
        if col_data and df_limpo['Data_Obj'].notnull().any():
            df_limpo['Mes_Perda'] = df_limpo['Data_Obj'].apply(lambda x: x.strftime('%Y-%m') if x else 'N/A')
            temp_data = df_limpo.groupby('Mes_Perda')['Valor_Calc'].sum().reset_index().sort_values('Mes_Perda')
            st.plotly_chart(px.bar(temp_data, x='Mes_Perda', y='Valor_Calc', title="Evolução de Perdas (Linha do Tempo)"), use_container_width=True)
        else:
            top_fin = df_limpo.groupby(col_motivo)['Valor_Calc'].sum().nlargest(8).reset_index()
            st.plotly_chart(px.bar(top_fin, y=col_motivo, x='Valor_Calc', orientation='h', title="Gargalos (R$)"), use_container_width=True)

    # --- IA ---
    st.markdown("---")
    if st.button("🚀 Iniciar Scoring Cronológico") or st.session_state.processado:
        
        if not st.session_state.processado:
            with st.spinner("Analisando perfil, datas e valores..."):
                df_w = limpar_csv_seguro(arq_ganhos)
                icp = extrair_icp(client, df_w)
                st.session_state.icp = icp
                
                with ThreadPoolExecutor(max_workers=15) as executor:
                    res = list(executor.map(lambda row: pontuar_lead(client, row, icp), df_limpo.to_dict('records')))
                
                df_limpo['Score_Pct'] = pd.to_numeric([r['score'] for r in res], errors='coerce').fillna(0).clip(0, 100)
                df_limpo['Justificativa'] = [r['motivo'] for r in res]
                df_limpo['Nota_0_5'] = (df_limpo['Score_Pct'] / 20).round(1)
                
                st.session_state.df_final = df_limpo
                st.session_state.processado = True
                st.rerun()

        # --- TELA FINAL ---
        df_final = st.session_state.df_final
        icp = st.session_state.icp
        
        st.success(f"🧠 **Perfil Ideal:** {icp}")
        
        df_show = df_final[df_final['Score_Pct'] >= min_score].copy()
        
        # Seleção de Colunas (Agora com DATA)
        cols_show = [col_nome, 'Data_Formatada', 'Dias_Atras', col_vend, col_prod, col_motivo, 'Valor_Calc', 'Nota_0_5', 'Score_Pct', 'Justificativa']
        
        df_export = df_show[cols_show].rename(columns={
            col_vend: 'Vendedor',
            col_prod: 'Equipamento',
            'Data_Formatada': 'Data Perda',
            'Dias_Atras': 'Dias Passados',
            'Valor_Calc': 'Valor Potencial',
            'Nota_0_5': 'Nota (0-5)',
            'Score_Pct': 'Aderência (%)'
        }).sort_values(['Nota (0-5)', 'Dias Passados'], ascending=[False, True]) # Ordena por Nota (Maior) e Data (Mais Recente)
        
        st.dataframe(
            df_export,
            column_config={
                "Nota (0-5)": st.column_config.NumberColumn(format="⭐ %.1f"),
                "Aderência (%)": st.column_config.ProgressColumn(format="%d%%", min_value=0, max_value=100),
                "Valor Potencial": st.column_config.NumberColumn(format="R$ %.2f"),
                "Dias Passados": st.column_config.NumberColumn(format="%d dias")
            },
            use_container_width=True
        )
        
        # --- DOWNLOAD ---
        csv_buffer = io.StringIO()
        df_csv = df_export.copy()
        
        # Formatação Final para Excel
        df_csv['Valor Potencial'] = df_csv['Valor Potencial'].apply(formatar_brl)
        df_csv['Nota (0-5)'] = df_csv['Nota (0-5)'].apply(lambda x: str(x).replace('.', ','))
        
        df_csv.to_csv(csv_buffer, index=False, sep=';', encoding='utf-8-sig')
        st.download_button("📥 Baixar CSV Cronológico (V54)", csv_buffer.getvalue(), "bi_chrono_v54.csv", "text/csv")
