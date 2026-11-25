"""Agregados por bairro (BH inteira) para o ranking: negócios e R$/m² útil.
Uso: python3 bairros.py itbi_bh.csv calibracao.csv pasta_data N_SHARDS
"""
import json, sys, zlib
import numpy as np, pandas as pd

FU_PADRAO = 0.60


def main(itbi, calib, outdir, N):
    N = int(N)
    i = pd.read_csv(itbi, dtype={"numero": str, "complemento": str}, keep_default_na=False, low_memory=False)
    for x in ["area_construida", "valor_declarado", "valor_base"]:
        i[x] = pd.to_numeric(i[x], errors="coerce")
    i = i[i.bairro != ""]
    i["num"] = i.numero.str.lstrip("0")
    # junta vaga avulsa paga no mesmo dia a um único apto
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
    r["fu"] = [fu.get((a, b), FU_PADRAO) for a, b in zip(r.logradouro, r.num)]
    ap = r.tipo == "AP"
    r["m2u"] = np.where(ap, r.valor_declarado / (r.area_construida * r.fu), np.nan)
    ok = ap & (r.area_construida >= 20) & ~(r.valor_base / r.valor_declarado >= 1.2)
    r.loc[~ok, "m2u"] = np.nan
    r.loc[(r.m2u < 700) | (r.m2u > 60000), "m2u"] = np.nan
    r["ano"] = r.data.str[:4]
    fim = r.data.max(); f12 = str(int(fim[:4]) - 1) + fim[4:]; f24 = str(int(fim[:4]) - 2) + fim[4:]
    per = {"12m": r.data > f12, "24m": r.data > f24}
    for y in sorted(r.ano.unique()):
        per[y] = r.ano == y

    r["anoc"] = pd.to_numeric(r.ano_construcao, errors="coerce")
    r["b"] = r.logradouro + "|" + r.num
    def agg(d, novo_corte):
        apd = d[d.tipo == "AP"]
        mb = apd.dropna(subset=["m2u"]).groupby("b").m2u.median()   # mediana de cada prédio
        nb = len(mb)
        novos = (apd.anoc >= novo_corte).mean() if len(apd) else 0
        return [int(len(d)), int(len(apd)), round(float(mb.median())) if nb >= 3 else None, int(nb),
                round(float(apd.valor_declarado.median())) if len(apd) >= 3 else None, round(float(novos) * 100)]

    res = {}
    for k, msk in per.items():
        d = r[msk]
        corte = (int(k) if k.isdigit() else int(fim[:4])) - 3
        res[k] = {b: agg(x, corte) for b, x in d.groupby("bairro")}
    meta = {"periodos": list(per.keys()), "fim": fim, "ini12": f12, "ini24": f24, "fu": FU_PADRAO}
    with open(f"{outdir}/bairros.json", "w") as o:
        json.dump({"meta": meta, "dados": res}, o, ensure_ascii=False, separators=(",", ":"))
    # prédios por bairro (24 meses e histórico)
    rows = {}
    for (bai, b), d in r.groupby(["bairro", "b"]):
        d24 = d[d.data > f24]; mu = d24.m2u.dropna(); ma = d.m2u.dropna()
        lg, num = b.split("|")
        anos = pd.to_numeric(d.ano_construcao, errors="coerce")
        anos = anos[anos.between(1900, 2030)]
        rows.setdefault(bai, []).append([lg, num, int(len(d24)), round(float(mu.median())) if len(mu) else None, int(len(d)),
                                         round(float(ma.median())) if len(ma) else None, int(anos.mode().iat[0]) if len(anos) else None,
                                         d.tipo.mode().iat[0]])
    sh = {s: {} for s in range(N)}
    for bai, lst in rows.items():
        lst.sort(key=lambda x: (-x[2], -x[4]))
        sh[zlib.crc32(bai.encode()) % N][bai] = lst
    for s, d in sh.items():
        with open(f"{outdir}/b{s}.json", "w") as o:
            json.dump(d, o, ensure_ascii=False, separators=(",", ":"))
    print(len(res["12m"]), "bairros com negócios nos últimos 12 meses; período", f12, "a", fim)
    t = pd.DataFrame(res["12m"], index=["neg", "ap", "m2u", "n_predios", "ticket", "pct_novos"]).T
    print(t.sort_values("neg", ascending=False).head(10)); print(t[t.n_predios >= 10].sort_values("m2u", ascending=False).head(10))


if __name__ == "__main__":
    main(*sys.argv[1:])
