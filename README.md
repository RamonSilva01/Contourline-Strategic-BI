# 🏛️ Contourline Strategic BI

Um **Business Intelligence estratégico com Inteligência Artificial**, desenvolvido em **Streamlit**, para transformar dados brutos de vendas e perdas em **decisão comercial acionável**.

Este projeto cruza **vendas ganhas x vendas perdidas**, extrai automaticamente um **Perfil de Cliente Ideal (ICP)** usando IA e aplica **scoring inteligente por lead**, considerando valor potencial, motivo de perda, vendedor responsável e aderência estratégica.

---

## 🎯 Objetivo do Projeto

Ajudar times comerciais e estratégicos a responder perguntas como:

- Onde estamos **perdendo dinheiro de verdade**?
- Quais leads perdidos **valem uma retomada ativa**?
- Qual o **perfil de cliente que mais converte**?
- Quais **motivos de perda geram maior impacto financeiro**?
- Quais vendedores têm **maior capital em risco na carteira**?

Tudo isso com **visualização clara, IA aplicada e exportação pronta para ação**.

---

## 🧠 O que este BI faz

### 1. Engenharia de Dados Inteligente
- Leitura segura de CSVs com formatação brasileira
- Normalização automática de valores monetários
- Detecção dinâmica de colunas (nome, motivo, valor, produto, vendedor)
- Filtro opcional de duplicidades, testes e leads inválidos

### 2. Análise Financeira Estratégica
- Total de leads analisados
- Capital real em risco (R$)
- Ranking de gargalos por motivo de perda
- Visualização por volume e impacto financeiro

### 3. Inteligência Artificial aplicada (OpenAI)
- Extração automática do **ICP (Ideal Customer Profile)** a partir das vendas ganhas
- Scoring de cada lead perdido com nota de **0 a 100**
- Conversão do score para **nota executiva (0 a 5 estrelas)**
- Justificativa textual para cada nota

### 4. Priorização Comercial
- Filtro por nível mínimo de aderência
- Ordenação por **nota + valor potencial**
- Visão clara por:
  - Lead
  - Vendedor responsável
  - Equipamento de interesse
  - Motivo da perda

### 5. Exportação Profissional
- Download em CSV com:
  - Valores formatados em BRL
  - Notas padronizadas
  - Pronto para CRM, planejamento comercial ou reuniões de estratégia

---

## 🧩 Tecnologias Utilizadas

- **Python**
- **Streamlit**
- **Pandas**
- **Plotly**
- **OpenAI API**
- **ThreadPoolExecutor** (processamento paralelo)
- **Regex e Data Cleaning avançado**

---

## 📂 Estrutura do Projeto
├── app.py # Aplicação principal Streamlit
├── requirements.txt # Dependências do projeto
├── README.md # Documentação


---

## ▶️ Como executar localmente

### 1. Clone o repositório
```bash
git clone https://github.com/seu-usuario/contourline-strategic-bi.git
cd contourline-strategic-bi

2. Crie e ative um ambiente virtual (opcional)
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

3. Instale as dependências
pip install -r requirements.txt

4. Configure sua chave da OpenAI

No código:

OPENAI_API_KEY = "SUA_CHAVE_AQUI"


Ou, preferencialmente, via variável de ambiente:

export OPENAI_API_KEY="SUA_CHAVE_AQUI"

5. Execute a aplicação
streamlit run app.py
📊 Como usar o BI

Faça upload do CSV de Vendas Ganhas

Faça upload do CSV de Vendas Perdidas

Ajuste os filtros laterais (duplicidade e score mínimo)

Clique em “Iniciar Scoring Completo”

Analise o dashboard e exporte os dados priorizados

🔐 Segurança & Boas Práticas

O projeto não armazena dados sensíveis

Processamento ocorre em memória

Uso consciente da API com paralelização controlada

Ideal para ambientes internos, BI estratégico e squads comerciais

🚀 Casos de Uso

Planejamento comercial

Recuperação de leads perdidos

Revisão de discurso de vendas

Análise de performance por vendedor

Identificação de falhas no funil

BI estratégico para diretoria

🧠 Visão Estratégica

Este não é apenas um dashboard.
É um sistema de inteligência comercial, pensado para transformar dados em prioridade, foco e dinheiro recuperado.

📌 Autor

Ramon Silva
Estratégia, Análise de Dados, Produto, IA aplicada a Negócios e Marketing de Alta Performance.

⚠️ Aviso

Projeto em evolução contínua.
Sugestões, melhorias e forks são bem-vindos.
