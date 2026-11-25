"""Monta a pasta final do site: página com datas e séries econômicas, índice de ruas completo.

Uso: python pipeline/montar_site.py site/index.html _site dados/work/itbi_bh.csv dados/work/valores.pkl dados/brutos/econ.json
"""
import json, sys, zlib
import pandas as pd

MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


def mes_ano(aaaa_mm):
    return f"{MESES[int(aaaa_mm[5:7]) - 1]}/{aaaa_mm[:4]}"


def main(modelo, saida, itbi, valores, econ, N=200):
    datas = pd.read_csv(itbi, usecols=["data"], dtype=str).data
    datas = datas[datas.str.match(r"^\d{4}-\d{2}")]
    p = pd.read_pickle(valores)
    dc = p.attrs.get("data_cadastro", "")
    e = json.load(open(econ))
    html = open(modelo).read()
    html = (html.replace("__ECON__", json.dumps(e, separators=(",", ":")))
                .replace("__PERIODO_ITBI__", f"{mes_ano(datas.min())} a {mes_ano(datas.max())}")
                .replace("__CADASTRO__", mes_ano(f"{dc[:4]}-{dc[4:6]}") if dc else "versão mais recente")
                .replace("__ECON_FIM__", mes_ano(e["m"][-1])))
    assert not any(k in html for k in ("__ECON__", "__PERIODO_ITBI__", "__CADASTRO__", "__ECON_FIM__"))
    open(f"{saida}/index.html", "w").write(html)
    # ruas que só existem no cadastro (prédios sem nenhuma venda) também precisam ser encontradas na busca
    idx = json.load(open(f"{saida}/data/idx.json"))
    nomes = {x[0] for x in idx}
    for lg in sorted(set(p.lg) - nomes):
        idx.append([lg, zlib.crc32(lg.encode()) % N, 0, []])
    idx.sort(key=lambda x: x[0])
    with open(f"{saida}/data/idx.json", "w") as o:
        o.write("[\n" + ",\n".join(json.dumps(x, ensure_ascii=False, separators=(",", ":")) for x in idx) + "\n]")
    open(f"{saida}/.nojekyll", "w").close()
    print(f"Site montado em {saida}: ITBI {mes_ano(datas.min())} a {mes_ano(datas.max())}, cadastro {dc}, {len(idx)} ruas")


if __name__ == "__main__":
    main(*sys.argv[1:])
