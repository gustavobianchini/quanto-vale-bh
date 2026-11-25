"""Estimativa de R$/m² (área PBH) por prédio.

Modelo v1:
  1) índice temporal por semestre: log(R$/m²) = efeito do prédio + efeito do semestre (vendas repetidas no mesmo prédio)
  2) R$/m² do prédio hoje = mediana das vendas do prédio trazidas a valor de hoje pelo índice
  3) encolhimento para a vizinhança (8 prédios mais próximos com vendas) quando o prédio tem poucas vendas
Uso: python3 avaliacao.py itbi_bh.csv perfil.pkl saida_dir [corte_validacao]
"""
import json, sys
import numpy as np, pandas as pd

MEIA_VIDA = 3
K0 = 3          # peso da vizinhança, em "vendas equivalentes"
KNN = 8
INICIO = "2012-01-01"


def carregar_vendas(itbi, perfil):
    i = pd.read_csv(itbi, dtype={"numero": str, "complemento": str}, keep_default_na=False, low_memory=False)
    for x in ["area_construida", "valor_declarado", "valor_base"]:
        i[x] = pd.to_numeric(i[x], errors="coerce")
    i["num"] = i.numero.str.lstrip("0")
    keys = perfil[perfil.n_ap > 0][["lg", "num"]]
    i = i.merge(keys, left_on=["logradouro", "num"], right_on=["lg", "num"])
    # junta vaga avulsa paga no mesmo dia (1 apto no dia)
    g = i.groupby(["lg", "num", "data"])
    i["nap"] = g.tipo.transform(lambda s: (s == "AP").sum())
    vr = i[(i.tipo == "VR") & (i.nap == 1)].groupby(["lg", "num", "data"])[["valor_declarado", "valor_base"]].sum()
    a = i[(i.tipo == "AP") & (i.ocupacao == "RESIDENCIAL")].copy()
    a = a.join(vr, on=["lg", "num", "data"], rsuffix="_vr")
    m = a.nap == 1
    for c in ["valor_declarado", "valor_base"]:
        a.loc[m, c] = a.loc[m, c] + a.loc[m, c + "_vr"].fillna(0)
    a["m2"] = a.valor_declarado / a.area_construida
    ok = (a.area_construida >= 20) & a.m2.between(400, 40000) & ~(a.valor_base / a.valor_declarado >= 1.2)
    a = a[ok & (a.data >= INICIO)].copy()
    a["t"] = a.data.str[:4] + np.where(a.data.str[5:7] <= "06", "S1", "S2")
    a["b"] = a.lg + "|" + a.num
    return a


def indice(a, it=60):
    y = np.log(a.m2.values)
    b = pd.factorize(a.b)[0]; t, tl = pd.factorize(a.t, sort=True)
    fb = np.zeros(b.max() + 1); ft = np.zeros(len(tl))
    for _ in range(it):
        fb = np.bincount(b, y - ft[t]) / np.bincount(b)
        ft = np.bincount(t, y - fb[b]) / np.bincount(t)
    ft -= ft[-1]
    return pd.Series(np.exp(ft), index=tl)


FAIXAS = [0, 1980, 1995, 2010, 2019, 2100]
ROT = ["até 1980", "1981-95", "1996-2010", "2011-19", "2020+"]


def anos_predios(itbi):
    i = pd.read_csv(itbi, usecols=["logradouro", "numero", "ano_construcao"], dtype=str, keep_default_na=False)
    i["ano"] = pd.to_numeric(i.ano_construcao, errors="coerce")
    i = i[i.ano.between(1900, 2030)]
    i["b"] = i.logradouro + "|" + i.numero.str.lstrip("0")
    return i.groupby("b").ano.agg(lambda s: s.mode().iat[0])


def valores(a, perfil, idx, ref, anos=None):
    a = a.copy()
    I = idx.reindex(a.t).values
    a["m2h"] = a.m2 / I * idx[ref]
    # vendas recentes pesam mais: meia-vida de MEIA_VIDA anos
    tref = pd.to_datetime(a.data).max()
    a["w"] = 0.5 ** ((tref - pd.to_datetime(a.data)).dt.days / 365.25 / MEIA_VIDA)
    def wmed(d):
        o = np.argsort(d.m2h.values); v = d.m2h.values[o]; w = d.w.values[o]; c = np.cumsum(w)
        return v[np.searchsorted(c, c[-1] / 2)]
    wm = a.groupby("b")[["m2h", "w"]].apply(wmed).rename("m2w")
    b = a.groupby("b").agg(m2b=("m2h", "median"), n=("m2h", "size"), disp=("m2h", lambda s: np.std(np.log(s)) if len(s) > 1 else np.nan),
                           ultima=("data", "max"), bairro=("bairro", lambda s: s.mode().iat[0]))
    p = perfil[perfil.n_ap > 0].copy()
    p["b"] = p.lg + "|" + p.num
    b["m2b"] = wm
    p = p.join(b, on="b")
    p["n"] = p.n.fillna(0).astype(int)
    com = p[p.n > 0]
    X = np.radians(com[["lat", "lon"]].values); Y = np.radians(p[["lat", "lon"]].values)
    # distâncias aproximadas (km) — equiretangular basta numa regional
    kx = np.cos(np.radians(-19.93)) * 6371; ky = 6371
    viz, dist = [], []
    cm2 = com.m2b.values; cn = com.n.values; cb = com.b.values
    for k, (la, lo) in enumerate(Y):
        d = np.hypot((X[:, 1] - lo) * kx, (X[:, 0] - la) * ky)
        d[cb == p.b.iat[k]] = np.inf
        o = np.argpartition(d, KNN)[:KNN]
        w = np.sqrt(cn[o]) / (0.15 + d[o])
        viz.append(np.exp(np.sum(w * np.log(cm2[o])) / w.sum())); dist.append(np.median(d[o]))
    p["m2viz"] = viz; p["dviz"] = dist
    # ajuste por padrão de acabamento: quanto prédios de cada padrão ficam acima/abaixo da vizinhança
    r = p[p.n >= 3]
    off = (np.log(r.m2b) - np.log(r.m2viz)).groupby(r.padrao).median()
    p["adj_padrao"] = np.exp(p.padrao.map(off).fillna(0))
    p["m2viz"] = p.m2viz * p.adj_padrao
    # ajuste por idade do prédio (quando conhecida): vizinhos têm idade média; prédio novo vale mais
    if anos is not None:
        p["ano"] = p.b.map(anos)
        p["faixa"] = pd.cut(p.ano, FAIXAS, labels=ROT)
        r = p[(p.n >= 3) & p.faixa.notna()]
        offa = (np.log(r.m2b) - np.log(r.m2viz)).groupby(r.faixa, observed=True).median()
        p["adj_idade"] = np.exp(p.faixa.map(offa).astype(float).fillna(0))
        p["m2viz"] = p.m2viz * p.adj_idade
    p["m2est"] = np.exp((p.n * np.log(p.m2b.fillna(1)) + K0 * np.log(p.m2viz)) / (p.n + K0))
    return p, a


def anos_predios_ate(itbi, corte):
    i = pd.read_csv(itbi, usecols=["logradouro", "numero", "ano_construcao", "data"], dtype=str, keep_default_na=False)
    i = i[i.data < corte]
    i["ano"] = pd.to_numeric(i.ano_construcao, errors="coerce")
    i = i[i.ano.between(1900, 2030)]
    i["b"] = i.logradouro + "|" + i.numero.str.lstrip("0")
    return i.groupby("b").ano.agg(lambda s: s.mode().iat[0])


def main(itbi, perfil_pkl, out, corte=None):
    perfil = pd.read_pickle(perfil_pkl)
    a = carregar_vendas(itbi, perfil)
    print("vendas usadas:", len(a), "prédios com venda:", a.b.nunique())
    if corte:
        tr, te = a[a.data < corte], a[a.data >= corte]
        idx = indice(tr); ref = idx.index[-1]
        anos_tr = anos_predios_ate(itbi, corte)
        p, _ = valores(tr, perfil, idx, ref, anos_tr)
        x = te.merge(p[["b", "m2est", "m2viz", "n"]], on="b")
        x["pred"] = x.m2est * x.area_construida; x["err"] = x.pred / x.valor_declarado - 1
        # base de comparação: mediana do bairro (últimos 2 anos do treino, sem índice)
        bm = tr[tr.data >= str(int(corte[:4]) - 2) + corte[4:]].groupby("bairro").m2.median()
        x["errb"] = x.bairro.map(bm) * x.area_construida / x.valor_declarado - 1
        def rel(e):
            e = e.dropna(); return f"erro mediano {np.median(np.abs(e)):.1%} | dentro de ±10%: {(e.abs()<=.1).mean():.0%} | ±20%: {(e.abs()<=.2).mean():.0%} | viés {np.median(e):+.1%} | n={len(e)}"
        print("VALIDAÇÃO (vendas a partir de", corte, ")")
        print("  modelo v1     :", rel(x.err))
        print("  mediana bairro:", rel(x.errb))
        # simulação: se soubéssemos o ano de todos os prédios (o que a base de Projetos Licenciados daria)
        p2, _ = valores(tr, perfil, idx, ref, anos_predios(itbi))
        x2 = te.merge(p2[["b", "m2est", "n"]], on="b"); x2["err"] = x2.m2est * x2.area_construida / x2.valor_declarado - 1
        print("  com ano de todos os prédios:", rel(x2.err), "| só prédios sem venda:", rel(x2.err[x2.n == 0]))
        for lab, msk in [("prédio com 0 vendas antes", x.n == 0), ("1-2 vendas", x.n.between(1, 2)), ("3-9", x.n.between(3, 9)), ("10+", x.n >= 10)]:
            print(f"  {lab:26s}:", rel(x.err[msk]))
        return
    idx = indice(a); ref = idx.index[-1]
    p, a2 = valores(a, perfil, idx, ref, anos_predios(itbi))
    p.attrs["data_cadastro"] = perfil.attrs.get("data_cadastro", ""); p.to_pickle(f"{out}/valores.pkl"); idx.to_csv(f"{out}/indice.csv", header=["indice"])
    print("índice (último = 1):"); print(idx.round(3).to_string())
    print(p[["n", "m2b", "m2viz", "m2est"]].describe().round(0))


if __name__ == "__main__":
    main(*sys.argv[1:])
