# Quanto vale seu imóvel — BH

Site que mostra, para qualquer endereço de Belo Horizonte, todos os negócios registrados no ITBI desde 2008, uma estimativa do valor de hoje por tamanho de apartamento e um ranking de bairros. Tudo com dados públicos.

**Site:** https://gustavobianchini.github.io/quanto-vale-bh/

## Como se atualiza

Uma rotina do GitHub Actions (`.github/workflows/atualizar.yml`) roda **nos dias 10 e 20 de cada mês**:

1. baixa do Portal de Dados Abertos da PBH os meses novos do ITBI e o cadastro imobiliário mais recente das 10 regionais;
2. baixa IPCA, CDI e dólar do Banco Central;
3. confere a base (colunas, meses faltando, último mês muito pequeno). **Se algo estiver estranho, o site não é atualizado** e o GitHub manda um e-mail avisando da falha;
4. recalcula índice de preços, estimativas por prédio e ranking de bairros;
5. publica o site no GitHub Pages.

Para rodar na hora: aba **Actions → Atualizar dados → Run workflow**.

### Plano B (se o portal da PBH bloquear o download)

Coloque os CSVs baixados à mão, pelo próprio site do GitHub (**Add file → Upload files**), em:

- `dados/manual/itbi/` — arquivos `pda_itbi_relatorio_AAAAMM.csv`
- `dados/manual/cadastro/` — um arquivo por regional, com o nome `<regional>_<AAAAMMDD>.csv` (ex.: `centro-sul_20260504.csv`)

O envio dispara a rotina automaticamente.

## Fontes

| Dado | Fonte |
|---|---|
| Negócios (valor, data, endereço, área) | PBH — ITBI Relatórios (`itbi-relatorios`) |
| Unidades de cada prédio, fração ideal, lote | PBH — Cadastro Imobiliário por regional |
| IPCA (433), CDI (4391), dólar PTAX fim de mês (3696) | Banco Central — SGS |
| Fator área útil ÷ área PBH conferido | `dados/calibracao.csv` (anúncios e informações diretas) |

## Como os números são calculados

- **Área útil ≈ área PBH × fator.** A área do ITBI/cadastro é a área total do prédio × fração ideal da unidade (inclui hall, lazer e garagem). O fator é conferido em alguns prédios (`dados/calibracao.csv`); nos demais usa-se a mediana dos conferidos (0,60).
- **Estimativa de valor:** índice semestral por vendas no mesmo prédio; vendas do prédio corrigidas para hoje (as recentes pesam mais, meia-vida de 3 anos); combinação com os 8 prédios vizinhos; ajuste por padrão de acabamento e idade. Teste fora da amostra (Centro-Sul, vendas out/2025–set/2026): erro mediano de 11,4%.
- **Vendas sinalizadas:** quando a base de cálculo da PBH fica 20%+ acima do valor declarado, a venda fica fora das medianas (possível subdeclaração ou venda fora de mercado).
- **Ranking de bairros:** R$/m² útil = mediana entre prédios (cada prédio conta uma vez), para um lançamento grande não dominar o bairro.

Para melhorar o fator de área útil, acrescente linhas em `dados/calibracao.csv` (`lg,num,area_pbh,area_util,fonte`).

## Estrutura

```
pipeline/      scripts (baixar → consolidar → validar → histórico → perfis → avaliação → bairros → site)
site/          modelo da página (as datas e séries econômicas são preenchidas na montagem)
dados/         calibração, séries econômicas de reserva e uploads manuais
```

Rodar localmente: `pip install -r requirements.txt && bash pipeline/rodar.sh` (site em `_site/`).
