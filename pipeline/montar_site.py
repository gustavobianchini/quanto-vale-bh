"""Monta a pasta final do site: página com datas e séries econômicas, índice de ruas completo.

Uso: python pipeline/montar_site.py site/index.html _site dados/work/itbi_bh.csv dados/work/valores.pkl dados/brutos/econ.json
"""
import json, sys, zlib
import pandas as pd

MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


def mes_ano(aaaa_mm):
    return f"{MESES[int(aaaa_mm[5:7]) - 1]}/{aaaa_mm[:4]}"


def cad_txt(dc):
    """'20260504-20261103' -> 'mai a nov/2026'; uma só data -> 'mai/2026'."""
    if not dc:
        return "versão mais recente"
    ds = sorted({x[:6] for x in dc.split("-")})
    a, b = mes_ano(f"{ds[0][:4]}-{ds[0][4:]}"), mes_ano(f"{ds[-1][:4]}-{ds[-1][4:]}")
    if a == b:
        return a
    return f"{a.split('/')[0]} a {b}" if a[-4:] == b[-4:] else f"{a} a {b}"


def main(modelo, saida, itbi, valores, econ, N=200):
    datas = pd.read_csv(itbi, usecols=["data"], dtype=str).data
    datas = datas[datas.str.match(r"^\d{4}-\d{2}")]
    p = pd.read_pickle(valores)
    dc = p.attrs.get("data_cadastro", "")
    e = json.load(open(econ))
    html = open(modelo).read()
    pesos = json.load(open("dados/pesos.json"))
    html = (html.replace("__ECON__", json.dumps(e, separators=(",", ":")))
                .replace("__PESOS__", json.dumps(pesos, ensure_ascii=False, separators=(",", ":")))
                .replace("__PERIODO_ITBI__", f"{mes_ano(datas.min())} a {mes_ano(datas.max())}")
                .replace("__CADASTRO__", cad_txt(dc))
                .replace("__ECON_FIM__", mes_ano(e["m"][-1])))
    assert not any(k in html for k in ("__ECON__", "__PESOS__", "__PERIODO_ITBI__", "__CADASTRO__", "__ECON_FIM__"))
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
    from datetime import datetime, timezone
    resumo = {"gerado_em": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), "itbi_de": datas.min()[:7],
              "itbi_ate": datas.max()[:7], "negocios": int(len(datas)), "cadastro": dc,
              "predios_com_estimativa": int(len(p)), "economia_ate": e["m"][-1]}
    with open("dados/ultima_atualizacao.json", "w") as o:
        json.dump(resumo, o, ensure_ascii=False, indent=1)
    print(f"Site montado em {saida}: ITBI {mes_ano(datas.min())} a {mes_ano(datas.max())}, cadastro {dc}, {len(idx)} ruas")


if __name__ == "__main__":
    main(*sys.argv[1:])
