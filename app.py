import streamlit as st
from openai import OpenAI
import pandas as pd
import plotly.express as px
from concurrent.futures import ThreadPoolExecutor
import io
import re
from datetime import datetime
import random

# ==========================================
# 🔐 AUTENTICAÇÃO INVISÍVEL
# O sistema busca a chave nos segredos. O usuário final não vê nada.
try:
    OPENAI_API_KEY = st.secrets["OPENAI_API_KEY"]
except FileNotFoundError:
    st.error("⚠️ Erro de Configuração: Chave de API não encontrada nos Segredos do servidor.")
    st.stop()
# ==========================================

st.set_page_config(page_title="Contourline Intelligence Hub", layout="wide")
st.title("🏛️ Contourline: Intelligence")

# --- BARRA LATERAL (CONFIGURAÇÕES) ---
with st.sidebar:
    st.header("🧠 Memória do Sistema")
    
    # OPÇÃO DE MEMÓRIA PERSISTENTE
    perfil_salvo = st.text_area(
        "Perfil Aprendido (Cole aqui para pular uploads):", 
        height=150,
        help="Cole o texto do Perfil Ideal aqui para não precisar subir os CSVs de venda toda vez."
    )
    
    st.markdown("---")
    st.header("⚙️ Filtros da Análise")
    filtrar_duplicados = st.checkbox("Remover Duplicidade/Testes", value=True)
    min_score = st.slider("Aderência Mínima (%):", 0, 100, 30)

# --- FUNÇÕES DE ENGENHARIA ---

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

# --- TREINAMENTO COM MÚLTIPLOS ARQUIVOS ---
def treinar_ia_multiarquivo(client, lista_arquivos):
    df_total = pd.DataFrame()
    for arq in lista_arquivos:
        df_temp = limpar_csv_seguro(arq)
        df_total = pd.concat([df_total, df_temp], ignore_index=True)
    
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
    return client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}]).choices[0].message.content

# --- ROTAÇÃO DE VENDEDORES ---
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

# Se já tem memória colada, esconde o upload de vendas
if not perfil_salvo:
    st.info("💡 Para criar a memória da IA, suba os CSVs de Vendas (Med + Não Med).")
    arquivos_venda = st.file_uploader("1. CSVs de VENDAS", type="csv", accept_multiple_files=True)
else:
    st.success("🧠 Memória Ativa! (Upload de vendas oculto)")
    arquivos_venda = None

arquivo_perdas = st.file_uploader("2. CSV de PERDAS (Leads Perdidos)", type="csv")

if (arquivos_venda or perfil_salvo) and arquivo_perdas:
    client = OpenAI(api_key=OPENAI_API_KEY)
    
    if 'processado' not in st.session_state: st.session_state.processado = False

    # --- PROCESSAMENTO DO CSV DE PERDAS ---
    df_l = limpar_csv_seguro(arquivo_perdas)
    
    # Mapeamento
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
        
    # --- ROTAÇÃO DE VENDEDORES ---
    lista_vendedores = df_limpo[col_vend].dropna().unique().tolist()
    df_limpo['Sugestão Novo Dono'] = df_limpo[col_vend].apply(lambda x: sugerir_novo_dono(x, lista_vendedores))

    # --- DASHBOARD ---
    st.markdown("### 🔍 Raio-X da Recuperação")
    k1, k2, k3 = st.columns(3)
    k1.metric("Leads Únicos", len(df_limpo))
    k2.metric("Equipe", f"{len(lista_vendedores)} Vendedores")
    k3.metric("Capital", f"R$ {df_limpo['Valor_Calc'].sum():,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.'))

    # --- IA ---
    st.markdown("---")
    if st.button("🚀 Iniciar Análise e Redistribuição") or st.session_state.processado:
        
        if not st.session_state.processado:
            with st.spinner("Analisando perfil, valores e redistribuindo carteira..."):
                if perfil_salvo:
                    icp = perfil_salvo
                else:
                    icp = treinar_ia_multiarquivo(client, arquivos_venda)
                
                st.session_state.icp = icp
                
                with ThreadPoolExecutor(max_workers=15) as executor:
                    res = list(executor.map(lambda row: pontuar_lead(client, row, icp), df_limpo.to_dict('records')))
                
                # Conversão segura para lista pandas series antes de numérico
                s_scores = pd.Series([r['score'] for r in res])
                df_limpo['Score_Pct'] = pd.to_numeric(s_scores, errors='coerce').fillna(0).clip(0, 100)
                
                df_limpo['Justificativa'] = [r['motivo'] for r in res]
                df_limpo['Nota_0_5'] = (df_limpo['Score_Pct'] / 20).round(1)
                
                st.session_state.df_final = df_limpo
                st.session_state.processado = True
                st.rerun()

        # --- TELA FINAL ---
        df_final = st.session_state.df_final
        icp = st.session_state.icp
        
        st.info(f"🧠 **Perfil Ativo:** {icp}")
        if not perfil_salvo:
            st.warning("⚠️ **Dica:** Copie o texto acima e cole no campo 'Memória' na barra lateral para pular uploads futuros!")
        
        df_show = df_final[df_final['Score_Pct'] >= min_score].copy()
        
        cols_show = [col_nome, 'Sugestão Novo Dono', col_vend, 'Data_Perda', 'Dias_Atras', col_prod, col_motivo, 'Valor_Calc', 'Nota_0_5', 'Score_Pct', 'Justificativa']
        
        df_export = df_show[cols_show].rename(columns={
            col_vend: 'Vendedor Antigo',
            col_prod: 'Equipamento',
            'Valor_Calc': 'Valor Potencial',
            'Nota_0_5': 'Nota (0-5)',
            'Score_Pct': 'Aderência (%)'
        }).sort_values(['Nota (0-5)', 'Dias_Atras'], ascending=[False, True])
        
        st.dataframe(
            df_export,
            column_config={
                "Sugestão Novo Dono": st.column_config.TextColumn("✨ Novo Dono", help="Sugestão para rodízio"),
                "Nota (0-5)": st.column_config.NumberColumn(format="⭐ %.1f"),
                "Aderência (%)": st.column_config.ProgressColumn(format="%d%%", min_value=0, max_value=100),
                "Valor Potencial": st.column_config.NumberColumn(format="R$ %.2f")
            },
            use_container_width=True
        )
        
        # --- DOWNLOAD ---
        csv_buffer = io.StringIO()
        df_csv = df_export.copy()
        df_csv['Valor Potencial'] = df_csv['Valor Potencial'].apply(formatar_brl)
        df_csv['Nota (0-5)'] = df_csv['Nota (0-5)'].apply(lambda x: str(x).replace('.', ','))
        
        df_csv.to_csv(csv_buffer, index=False, sep=';', encoding='utf-8-sig')
        st.download_button("📥 Baixar CSV (Pronto p/ Distribuição)", csv_buffer.getvalue(), "contourline_bi_final.csv", "text/csv")
