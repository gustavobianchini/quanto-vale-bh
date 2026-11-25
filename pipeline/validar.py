"""Confere a base consolidada antes de publicar. Sai com erro (e o site não é publicado) se algo estiver estranho.

Uso: python pipeline/validar.py dados/work/itbi_bh.csv
"""
import sys
import pandas as pd

COLUNAS = ["data", "logradouro", "numero", "complemento", "bairro", "cep", "ano_construcao", "area_terreno",
           "area_construida", "area_somada", "padrao", "fracao_ideal", "tipo", "ocupacao", "valor_declarado",
           "valor_base", "zona", "arquivo"]


def main(arq):
    d = pd.read_csv(arq, dtype=str, keep_default_na=False, usecols=lambda c: True)
    erros, avisos = [], []
    if list(d.columns) != COLUNAS:
        erros.append(f"colunas diferentes do esperado: {list(d.columns)}")
    if len(d) < 400_000:
        erros.append(f"base pequena demais: {len(d)} linhas")
    d = d[d.data.str.match(r"^\d{4}-\d{2}-\d{2}$")]
    mes = d.data.str[:7].value_counts().sort_index()
    todos = pd.period_range("2008-01", mes.index.max(), freq="M").astype(str)
    faltando = [m for m in todos if m not in mes.index]
    if faltando:
        erros.append(f"meses sem nenhum negócio: {faltando}")
    ult = mes.index.max()
    ref = mes.iloc[-13:-1].median()
    if mes.iloc[-1] < 0.3 * ref:
        erros.append(f"último mês ({ult}) com só {mes.iloc[-1]} negócios, contra mediana de {ref:.0f} nos 12 anteriores")
    vd = pd.to_numeric(d.valor_declarado, errors="coerce")
    if vd.isna().mean() > 0.02:
        erros.append(f"{vd.isna().mean():.1%} dos valores declarados ilegíveis")
    dup = d.duplicated().mean()
    if dup > 0.01:
        avisos.append(f"{dup:.2%} de linhas duplicadas")
    print(f"Base: {len(d):,} negócios de {mes.index.min()} a {ult}; último mês com {mes.iloc[-1]:,} negócios")
    for a in avisos:
        print("AVISO:", a)
    if erros:
        for e in erros:
            print("ERRO:", e)
        sys.exit(1)
    print("Validação OK")


if __name__ == "__main__":
    main(sys.argv[1])
