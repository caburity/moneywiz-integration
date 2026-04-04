# Product Requirements Document (PRD)

**Product Name:** MoneyWiz Integration
**Version:** 1.0
**Last Updated:** 2026-04-04

---

## 1. Overview

### 1.1 Summary

O MoneyWiz Integration e um conjunto de ferramentas locais que expandem as capacidades do MoneyWiz (app de financas pessoais para macOS). O produto tem dois componentes:

1. **MCP Server (Fase 1):** Servidor MCP read-only que expoe dados do MoneyWiz ao Claude, permitindo consultas conversacionais sobre contas, transacoes, categorias, payees e investimentos.

2. **Sync App (Fase 2):** Aplicacao web local em Python que le extratos de cartoes de credito de dois bancos portugueses (Millennium BCP e Santander Totta), ambos em formato PDF, compara com os lancamentos existentes no MoneyWiz e permite sincronizar as transacoes em falta de forma seletiva.

O produto destina-se a um unico utilizador tecnico e executa 100% localmente. A leitura de dados utiliza acesso direto ao banco SQLite do MoneyWiz em `~/Library/Containers/com.moneywiz.personalfinance/Data/Documents/.AppData/ipadMoneyWiz.sqlite`. A escrita de novas transacoes utiliza URL Schemas do MoneyWiz (`moneywiz://expense?...`), sem acesso direto ao banco.

**Linguagem:** Python (MCP Server via FastMCP + Sync App via Flask + parsing via pdfplumber).

### 1.2 Objectives

- Consultar dados financeiros do MoneyWiz via Claude usando linguagem natural
- Eliminar o trabalho manual de comparar extratos bancarios com o MoneyWiz
- Reduzir o risco de lancamentos duplicados ou em falta nos cartoes de credito
- Permitir sincronizacao seletiva e controlada de transacoes para o MoneyWiz
- Manter toda a informacao financeira 100% local

---

## 2. Decisoes de Design (Confirmadas)

| Decisao | Escolha | Motivo |
|---------|---------|--------|
| Interface | Web local (Flask/Streamlit) | Melhor UX para selecao de transacoes |
| Escrita no MoneyWiz | URL Schemas (`moneywiz://expense?...`) | Zero risco de corrupcao; MoneyWiz gere toda a logica interna; verificacao pos-criacao via leitura do DB |
| Formato extratos | Ambos em PDF | Millennium fornece PDF nativo; Santander tambem em PDF |
| Backup | Automatico antes de cada batch de sincronizacao | Ao clicar "Sincronizar", backup + sync |
| Transacoes duplicadas | Se o extrato tem 2 iguais, cria 2 no MoneyWiz | Matching por contagem: se extrato tem 2 e MoneyWiz tem 1, falta 1 |
| Nomes das contas | Fixos: "Cartão123" (Santander), "Cartão Millennium" (Millennium) | Podem ser alterados no codigo mas nao sao configuraveis via UI |
| Payee automatico | "Automacao" | Identifica transacoes criadas pela ferramenta |

---

## 3. Analise de Formato dos Extratos (Baseada em Amostras Reais)

### 3.1 Millennium BCP (PDF)

**Seccao relevante:** "DETALHE DOS MOVIMENTOS"

**Colunas:**
| Data Movimento | Data Valor | Descritivo | Rede | Milhas | Debito | Credito |

**Caracteristicas:**
- Formato de data: `YYYY/MM/DD` (ex: 2026/03/01)
- Valores: decimais com ponto (ex: 36.43)
- Cada transacao ocupa 2 linhas: linha principal (dados) + linha secundaria (VIS + milhas)
- Descricoes comecam tipicamente com "COMPRA 0382" seguido do comerciante e localidade
- Tipos de lancamento a IGNORAR no parsing: "TAXAS POSTOS COMBUSTIVEL", "IMPOSTO DO SELO", ">PAGAMENTO CARTAO DE CREDITO"
- Tipos de lancamento a IMPORTAR: "COMPRA 0382 ..." (debitos de compras)

**Exemplo de transacao:**
```
2026/03/01  2026/03/02  COMPRA 0382 SPORT ZONE AMADORA     36.43
                                                 VIS  36.00
```

**Dados a extrair:**
- Data: Data Movimento (primeira coluna) -> 2026/03/01
- Descricao: Descritivo sem o prefixo "COMPRA 0382 " -> "SPORT ZONE AMADORA"
- Valor: coluna Debito -> 36.43

### 3.2 Santander Totta (PDF)

**Seccao relevante:** "Listagem Movimentos"

**Colunas:**
| Movimento | Data | Descricao | Estado | Montante |

**Caracteristicas:**
- Formato de data: `DD-MM-YYYY` (ex: 15-02-2026)
- Valores: decimais com virgula + " EUR" (ex: 10,99 EUR)
- D = Debito (compras), C = Credito (pagamentos/reembolsos)
- Estado: sempre "EXTRACTADO"
- Descricoes incluem identificador do cartao fisico: TPA*2681, TPA*1881, ESTRANG*2681, ESTRANG*1881
- O extrato contem transacoes de DOIS cartoes fisicos (1881 e 2681) na mesma conta "Cartao 123"
- Descricoes podem ocupar multiplas linhas no PDF
- Tipos de lancamento a IGNORAR: "PAG.TRANS.BANCARIA" (C), "COMISSAO DISPONIBILIZACAO...", "BONIF. COMISS DISPONIBILIZACAO..."
- Tipos de lancamento a IMPORTAR: "COMPRA TPA*..." e "COMPRA ESTRANG*..." (D - debitos)

**Exemplo de transacao:**
```
602130001  11-02-2026  COMPRA TPA*2681 NORAUTO . LIMA DE F  EXTRACTADO  D  10,99 EUR
```

**Dados a extrair:**
- Data: coluna Data -> 11-02-2026
- Descricao: coluna Descricao sem prefixo "COMPRA TPA*XXXX " ou "COMPRA ESTRANG*XXXX " -> "NORAUTO . LIMA DE F"
- Valor: parte numerica do Montante -> 10.99
- Tipo: D (debito) ou C (credito) - importar D e C

---

## 4. Features & Requisitos Funcionais

### Feature 1: MCP Server Read-Only (Fase 1)

Servidor MCP que expoe dados do MoneyWiz ao Claude via protocolo stdio.

**Requisitos:**
- Consultar saldos, transacoes, categorias e payees via Claude
- Filtrar transacoes por conta, data, categoria ou payee
- Obter sumarios e agregacoes dos dados financeiros
- Apenas leitura; nenhuma operacao de escrita
- Utilizar biblioteca moneywiz-api (PyPI v1.0.6)

### Feature 2: Importacao de Extratos (Fase 2)

**Requisitos:**
- Ler ficheiros PDF de extrato do Millennium BCP e Santander Totta
- Extrair de cada lancamento: data, descricao, valor
- Associar automaticamente: Millennium -> "Cartao Millennium", Santander -> "Cartao 123"
- Suportar upload de um ou ambos os extratos na interface web
- Rejeitar e informar caso nao consiga fazer parsing de um ficheiro
- Filtrar apenas transacoes de compra (ignorar taxas, impostos, pagamentos, comissoes)

### Feature 3: Comparacao e Deteccao de Transacoes Novas (Fase 2)

**Requisitos:**
- Ler transacoes existentes nas contas "Cartao 123" e "Cartao Millennium" no MoneyWiz
- Comparar por data + valor para determinar se transacao ja existe
- Para transacoes identicas (mesma data/valor), contar ocorrencias: se extrato tem 2 e MoneyWiz tem 1, apresentar 1 como nova
- Caso existam transacoes novas: mostrar agrupadas por cartao, ordenadas por data, com Data | Descricao | Valor
- Caso todas ja existam: mostrar "Todas as transacoes ja estao sincronizadas. Nao existem novas transacoes a sincronizar."

### Feature 4: Seleccao e Sincronizacao (Fase 2)

**Requisitos:**
- Selecionar/desselecionar transacoes individualmente
- Opcao "selecionar todas" por cartao
- Botao "Sincronizar" ativo apenas quando >= 1 transacao selecionada
- Ao clicar "Sincronizar": pedir confirmacao explicita
- Se confirmado: criar backup do SQLite e depois criar transacoes
- Cada transacao criada com: data, descricao, valor, conta (cartao correto), payee "Automacao"
- Mostrar progresso em tempo real (ex: "3 de 15 transacoes sincronizadas")
- Ao concluir: informar sucesso ou erro
- Em caso de erro parcial: indicar quais criadas e quais falharam
- Nao criar duplicadas

---

## 5. Scope

### In Scope

**Fase 1:** MCP server read-only (contas, transacoes, categorias, payees, investimentos)

**Fase 2:** Parsing PDF Millennium + Santander, comparacao com MoneyWiz, seleccao interativa, sync com backup, interface web local

### Out of Scope

- Outros bancos alem de Millennium BCP e Santander Totta
- Outros tipos de conta alem dos dois cartoes
- Edicao ou remocao de transacoes existentes
- Categorizacao automatica de transacoes
- Sincronizacao automatica/agendada
- Acesso remoto ou multi-utilizador
- Aplicacao mobile ou cloud
- Integracao Open Banking
- Escrita via MCP Server

---

## 6. Riscos e Mitigacoes

| Risco | Impacto | Mitigacao |
|-------|---------|-----------|
| Formato PDF muda sem aviso | High | Parsing robusto com validacao; alertar quando formato nao reconhecido |
| Matching produz falsos positivos/negativos | High | Match por data+valor com contagem de ocorrencias |
| URL Schema nao processa corretamente | Medium | Verificacao pos-criacao via leitura do DB; backup preventivo antes do batch |
| moneywiz-api incompativel com MoneyWiz futuro | Medium | Biblioteca e simples; replicar queries se necessario |
| MoneyWiz altera schema do SQLite | Medium | Validar schema no arranque |
| Python 3.14 incompatibilidade | Low | mcp e moneywiz-api sao pure Python |

---

## 7. Stack Tecnico

- **Runtime:** Python 3.14.2
- **MCP Framework:** FastMCP (via `mcp` package)
- **MoneyWiz Access:** moneywiz-api v1.0.6 (leitura), URL Schemas (escrita via `open "moneywiz://..."` )
- **PDF Parsing:** pdfplumber (a validar com amostras reais)
- **Web Framework:** Flask ou Streamlit (a definir)
- **DB:** SQLite (MoneyWiz nativo)
