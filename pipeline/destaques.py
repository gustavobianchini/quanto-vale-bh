"""Destaques de cada mês (últimos 12 meses com dados).

- venda residencial mais cara e maior R$/m² útil do mês
- prédio e bairro mais negociados
- revendas da mesma unidade que mais valorizaram e desvalorizaram (ganho real, descontado o IPCA)
- bairros que mais subiram/caíram: R$/m² útil dos últimos 12 meses contra os 12 anteriores (mediana entre prédios)

Uso: python pipeline/destaques.py itbi_bh.csv calibracao.csv econ.json saida.json
"""
import json, sys
import numpy as np, pandas as pd

FU_PADRAO = 0.60
N_MESES = 12


def preparar(itbi, calib):
    i = pd.read_csv(itbi, dtype={"numero": str, "complemento": str}, keep_default_na=False, low_memory=False)
    for x in ["area_construida", "area_terreno", "valor_declarado", "valor_base"]:
        i[x] = pd.to_numeric(i[x], errors="coerce")
    i["num"] = i.numero.str.lstrip("0")
    # vaga avulsa paga no mesmo dia de um único apto entra no valor do apto
    i["isap"] = (i.tipo == "AP").astype(int)
    i["nap"] = i.groupby(["logradouro", "num", "data"]).isap.transform("sum")
    vr = i[(i.tipo == "VR") & (i.nap == 1)].groupby(["logradouro", "num", "data"])[["valor_declarado", "valor_base"]].sum()
    r = i[(i.ocupacao == "RESIDENCIAL") & (i.tipo != "VR")].copy()
    r = r.join(vr, on=["logradouro", "num", "data"], rsuffix="_vr")
    m = (r.tipo == "AP") & (r.nap == 1)
    for c in ["valor_declarado", "valor_base"]:
        r.loc[m, c] = r.loc[m, c] + r.loc[m, c + "_vr"].fillna(0)
    cal = pd.read_csv(calib); cal["f"] = cal.area_util / cal.area_pbh
    fu = {(a, str(b)): f for a, b, f in zip(cal.lg, cal.num, cal.f)}
    r["fu"] = [fu.get((a, b), FU_PADRAO) if t == "AP" else 1.0 for a, b, t in zip(r.logradouro, r.num, r.tipo)]
    r["au"] = np.where(r.tipo == "LV", r.area_terreno, r.area_construida * r.fu)
    r["mu"] = r.valor_declarado / r.au
    r["suspeita"] = r.valor_base / r.valor_declarado >= 1.2
    r["mes"] = r.data.str[:7]
    return r[r.mes.str.match(r"^\d{4}-\d{2}$")]


def item(x):
    return {"lg": x.logradouro, "num": x.num, "comp": x.complemento, "bai": x.bairro, "tipo": x.tipo,
            "data": x.data, "valor": round(float(x.valor_declarado)), "au": round(float(x.au)) if x.au == x.au else None,
            "mu": round(float(x.mu)) if x.mu == x.mu else None}


def main(itbi, calib, econ, saida):
    r = preparar(itbi, calib)
    e = json.load(open(econ)); ei = {m: k for k, m in enumerate(e["m"])}
    fator_ipca = np.cumprod([1 + v / 100 for v in e["ipca"]])  # índice acumulado por mês

    def ipca(m0, m1):
        a, b = ei.get(m0), ei.get(m1)
        if a is None or b is None:
            # meses além da série: usa o último disponível
            b = ei.get(m1, len(e["m"]) - 1); a = ei.get(m0, 0)
        return fator_ipca[b] / fator_ipca[a]

    ok = r[~r.suspeita & r.valor_declarado.notna() & (r.valor_declarado >= 30000)]
    aps = ok[(ok.tipo == "AP") & (ok.area_construida >= 20)]

    # revendas: mesma unidade (rua, número, complemento, mesma área) vendida antes
    u = aps[aps.complemento != ""].sort_values("data")
    u = u.assign(chave=u.logradouro + "|" + u.num + "|" + u.complemento + "|" + u.area_construida.round(1).astype(str))
    u["v_ant"] = u.groupby("chave").valor_declarado.shift()
    u["d_ant"] = u.groupby("chave").data.shift()
    rv = u.dropna(subset=["v_ant"]).copy()
    rv["anos"] = (pd.to_datetime(rv.data) - pd.to_datetime(rv.d_ant)).dt.days / 365.25
    rv = rv[(rv.anos >= 2) & (rv.valor_declarado / rv.v_ant).between(0.3, 6)]
    rv["nominal"] = rv.valor_declarado / rv.v_ant - 1
    rv["ipca"] = [ipca(a[:7], b[:7]) - 1 for a, b in zip(rv.d_ant, rv.data)]
    rv["real"] = (1 + rv.nominal) / (1 + rv.ipca) - 1
    rv["real_aa"] = (1 + rv.real) ** (1 / rv.anos) - 1

    def revenda(x):
        d = item(x)
        d.update({"d_ant": x.d_ant, "v_ant": round(float(x.v_ant)), "anos": round(float(x.anos), 1),
                  "nominal": round(float(x.nominal), 4), "ipca": round(float(x.ipca), 4), "real": round(float(x.real), 4),
                  "real_aa": round(float(x.real_aa), 4)})
        return d

    meses = sorted(r.mes.unique())[-N_MESES:]
    out = {"meses": [], "gerado": meses[-1]}
    for m in reversed(meses):
        d = ok[ok.mes == m]; dap = aps[aps.mes == m]; tudo = r[r.mes == m]
        if not len(d):
            continue
        ano_ant = f"{int(m[:4]) - 1}{m[4:]}"
        blocos = {"mes": m, "negocios": int(len(tudo)), "negocios_ano_ant": int((r.mes == ano_ant).sum()),
                  "aptos": int((tudo.tipo == "AP").sum())}
        blocos["mais_caras"] = [item(x) for x in d.sort_values("valor_declarado", ascending=False).head(5).itertuples()]
        blocos["maior_m2"] = [item(x) for x in dap[dap.au >= 30].sort_values("mu", ascending=False).head(5).itertuples()]
        pr = tudo[tudo.tipo == "AP"].groupby(["logradouro", "num"]).agg(n=("data", "size"), bai=("bairro", "first"),
                                                                          mu=("mu", "median"), ano=("ano_construcao", "first"))
        blocos["predios"] = [{"lg": a, "num": b, "n": int(x.n), "bai": x.bai, "mu": round(float(x.mu)) if x.mu == x.mu else None,
                              "ano": x.ano} for (a, b), x in pr.sort_values("n", ascending=False).head(5).iterrows()]
        bb = tudo.groupby("bairro").size().sort_values(ascending=False).head(5)
        blocos["bairros"] = [{"bai": b, "n": int(n)} for b, n in bb.items()]
        rm = rv[rv.mes == m]
        blocos["revendas_n"] = int(len(rm))
        blocos["revendas_mediana_real"] = round(float(rm.real.median()), 4) if len(rm) else None
        blocos["valorizaram"] = [revenda(x) for x in rm.sort_values("real_aa", ascending=False).head(5).itertuples()]
        blocos["desvalorizaram"] = [revenda(x) for x in rm.sort_values("real_aa").head(5).itertuples()]
        # bairros: 12 meses até m contra os 12 anteriores
        fim = pd.Period(m, "M"); j1 = [str(fim - k) for k in range(12)]; j0 = [str(fim - 12 - k) for k in range(12)]
        def med(meses_):
            z = aps[aps.mes.isin(meses_)]
            pb = z.groupby(["bairro", "logradouro", "num"]).mu.median().reset_index()
            return pb.groupby("bairro").mu.agg(["median", "size"])
        a1, a0 = med(j1), med(j0)
        bz = a1.join(a0, lsuffix="1", rsuffix="0").dropna()
        bz = bz[(bz.size1 >= 15) & (bz.size0 >= 15)]
        bz["var"] = bz.median1 / bz.median0 - 1
        ip = ipca(j0[0], j1[0]) - 1
        lst = lambda s: [{"bai": b, "var": round(float(x["var"]), 4), "m2": round(float(x.median1)), "m2_ant": round(float(x.median0)),
                          "predios": int(x.size1)} for b, x in s.iterrows()]
        blocos["bairros_ipca"] = round(float(ip), 4)
        blocos["bairros_subiram"] = lst(bz.sort_values("var", ascending=False).head(5))
        blocos["bairros_cairam"] = lst(bz.sort_values("var").head(5))
        out["meses"].append(blocos)
    with open(saida, "w") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    u0 = out["meses"][0]
    print(f"Destaques de {len(out['meses'])} meses; {u0['mes']}: {u0['negocios']} negócios, {u0['revendas_n']} revendas, "
          f"mediana real {u0['revendas_mediana_real']}")


if __name__ == "__main__":
    main(*sys.argv[1:])
