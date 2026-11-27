"""Agregados por bairro (BH inteira) para o ranking: negócios e R$/m² útil.
Uso: python3 bairros.py itbi_bh.csv calibracao.csv pasta_data N_SHARDS
"""
import json, sys, zlib
import numpy as np, pandas as pd

FU_PADRAO = 0.60


def serie(df, min_n=5, min_b=2, it=60):
    """Preço ano a ano de um prédio típico do grupo (bairro ou rua), comparando os mesmos prédios entre anos
    (efeito fixo de prédio + efeito de ano), para lançamentos e prédios caros não distorcerem a curva.
    Devolve [[ano, mes_de_referencia, R$/m² útil, n_vendas], ...]; anos com menos de min_n vendas ficam fora."""
    d = df.dropna(subset=["m2u"])
    c = d.groupby("ano").agg(n=("m2u", "size"), nb=("b", "nunique"))
    d = d[d.ano.isin(c[(c.n >= min_n) & (c.nb >= min_b)].index)]
    if d.ano.nunique() < 2:
        return []
    y = np.log(d.m2u.values); b, bl = pd.factorize(d.b); t, tl = pd.factorize(d.ano, sort=True)
    fb = np.zeros(len(bl)); ft = np.zeros(len(tl))
    for _ in range(it):
        fb = np.bincount(b, y - ft[t]) / np.bincount(b)
        ft = np.bincount(t, y - fb[b]) / np.bincount(t)
    fim = d.data.max(); f24 = str(int(fim[:4]) - 2) + fim[4:]
    rec = pd.unique(b[d.data.values > f24]); base = np.median(fb[rec] if len(rec) else fb)   # prédio típico de hoje
    lastm = int(fim[5:7]); n = np.bincount(t)
    return [[a, f"{a}-{'07' if a != fim[:4] else f'{(1 + lastm) // 2:02d}'}", round(float(np.exp(base + ft[k]))), int(n[k])]
            for k, a in enumerate(tl)]


def m_ref(a, fim):
    return f"{a}-{'07' if a != fim[:4] else f'{(1 + int(fim[5:7])) // 2:02d}'}"


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
    # curva de preço por bairro e valorização em 5 anos
    ap_ok = r[(r.tipo == "AP") & r.m2u.notna()]
    series = {bai: serie(d) for bai, d in ap_ok.groupby("bairro")}
    a1 = fim[:4]; a0 = str(int(a1) - 5); val5 = {}
    for bai, sr in series.items():
        m = {x[0]: x for x in sr}
        if a0 in m and a1 in m and m[a0][3] >= 20 and m[a1][3] >= 20:
            val5[bai] = round(m[a1][2] / m[a0][2] - 1, 4)
    meta = {"periodos": list(per.keys()), "fim": fim, "ini12": f12, "ini24": f24, "fu": FU_PADRAO,
            "val_de": m_ref(a0, fim), "val_ate": m_ref(a1, fim)}
    with open(f"{outdir}/bairros.json", "w") as o:
        json.dump({"meta": meta, "dados": res, "val5": val5}, o, ensure_ascii=False, separators=(",", ":"))
    # por bairro: prédios, ruas e curva de preço
    rows, ruas = {}, {}
    for (bai, b), d in r.groupby(["bairro", "b"]):
        d24 = d[d.data > f24]; mu = d24.m2u.dropna(); ma = d.m2u.dropna()
        lg, num = b.split("|")
        anos = pd.to_numeric(d.ano_construcao, errors="coerce")
        anos = anos[anos.between(1900, 2030)]
        rows.setdefault(bai, []).append([lg, num, int(len(d24)), round(float(mu.median())) if len(mu) else None, int(len(d)),
                                         round(float(ma.median())) if len(ma) else None, int(anos.mode().iat[0]) if len(anos) else None,
                                         d.tipo.mode().iat[0], int(len(mu))])
    for bai, lst in rows.items():
        g = {}
        for x in lst:
            if x[7] == "LV":
                continue
            e = g.setdefault(x[0], [x[0], 0, 0, [], 0])
            e[1] += 1; e[2] += x[2]; e[4] += x[4]
            if x[3]:
                e[3].append(x[3])
        ruas[bai] = sorted([[k, v[1], v[2], round(float(np.median(v[3]))) if v[3] else None, v[4], len(v[3])] for k, v in g.items()],
                           key=lambda z: (-z[2], -z[4]))
    sh = {s: {} for s in range(N)}
    for bai, lst in rows.items():
        lst.sort(key=lambda x: (-x[2], -x[4]))
        sh[zlib.crc32(bai.encode()) % N][bai] = {"p": lst, "r": ruas.get(bai, []), "s": series.get(bai, [])}
    for s, d in sh.items():
        with open(f"{outdir}/b{s}.json", "w") as o:
            json.dump(d, o, ensure_ascii=False, separators=(",", ":"))
    print(len(series), "bairros;", sum(1 for v in series.values() if v), "com curva de preço;", len(val5), "com valorização em 5 anos")
    print(len(res["12m"]), "bairros com negócios nos últimos 12 meses; período", f12, "a", fim)
    t = pd.DataFrame(res["12m"], index=["neg", "ap", "m2u", "n_predios", "ticket", "pct_novos"]).T
    print(t.sort_values("neg", ascending=False).head(10)); print(t[t.n_predios >= 10].sort_values("m2u", ascending=False).head(10))


if __name__ == "__main__":
    main(*sys.argv[1:])
