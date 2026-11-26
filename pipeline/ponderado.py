"""Avaliação ponderada por componentes (R$/m² de área PBH, a valor de hoje).

Componentes por prédio:
  predio  - vendas no próprio prédio (corrigidas pelo índice; recentes pesam mais)
  ano     - prédios do mesmo bairro com ano de construção parecido (±5 anos), últimos 3 anos
  rua     - outros prédios da mesma rua no mesmo bairro, últimos 3 anos
  bairro  - prédios do bairro, últimos 3 anos
O valor final = média geométrica ponderada dos componentes disponíveis (pesos em dados/pesos.json;
se um componente falta, seu peso é redistribuído entre os demais). O ajuste de conservação/reforma é aplicado na página.

Uso:
  python pipeline/ponderado.py teste itbi_bh.csv pesos.json [corte]     -> validação fora da amostra
  python pipeline/ponderado.py gerar itbi_bh.csv pesos.json saida.pkl   -> componentes atuais de todos os prédios
"""
import itertools, json, sys
import numpy as np, pandas as pd

COMP = ["predio", "ano", "rua", "bairro"]
MEIA_VIDA = 3
JANELA_ANOS = 3
MIN_PREDIOS = 3


def vendas(itbi):
    i = pd.read_csv(itbi, dtype={"numero": str, "complemento": str}, keep_default_na=False, low_memory=False)
    for x in ["area_construida", "valor_declarado", "valor_base"]:
        i[x] = pd.to_numeric(i[x], errors="coerce")
    i["num"] = i.numero.str.lstrip("0")
    i["isap"] = (i.tipo == "AP").astype(int)
    i["nap"] = i.groupby(["logradouro", "num", "data"]).isap.transform("sum")
    vr = i[(i.tipo == "VR") & (i.nap == 1)].groupby(["logradouro", "num", "data"])[["valor_declarado", "valor_base"]].sum()
    a = i[(i.tipo == "AP") & (i.ocupacao == "RESIDENCIAL")].copy()
    a = a.join(vr, on=["logradouro", "num", "data"], rsuffix="_vr")
    m = a.nap == 1
    for c in ["valor_declarado", "valor_base"]:
        a.loc[m, c] = a.loc[m, c] + a.loc[m, c + "_vr"].fillna(0)
    a["m2"] = a.valor_declarado / a.area_construida
    ok = (a.area_construida >= 20) & a.m2.between(400, 40000) & ~(a.valor_base / a.valor_declarado >= 1.2)
    a = a[ok & (a.data >= "2012-01-01")].copy()
    a["t"] = a.data.str[:4] + np.where(a.data.str[5:7] <= "06", "S1", "S2")
    a["b"] = a.logradouro + "|" + a.num
    a["anoc"] = pd.to_numeric(a.ano_construcao, errors="coerce").where(lambda s: s.between(1900, 2030))
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


def wmed(v, w):
    o = np.argsort(v); v = np.asarray(v)[o]; w = np.asarray(w)[o]; c = np.cumsum(w)
    return v[np.searchsorted(c, c[-1] / 2)]


def componentes(a):
    """a: vendas até a data de referência. Devolve um DataFrame por prédio com os 4 componentes (R$/m² PBH, hoje)."""
    idx = indice(a)
    a = a.assign(m2h=a.m2 / idx.reindex(a.t).values)          # a valor do último semestre
    tref = pd.to_datetime(a.data).max()
    a["w"] = 0.5 ** ((tref - pd.to_datetime(a.data)).dt.days / 365.25 / MEIA_VIDA)
    # prédio
    g = a.groupby("b")
    p = pd.DataFrame({"m2_predio": g[["m2h", "w"]].apply(lambda d: wmed(d.m2h.values, d.w.values)),
                      "n_predio": g.size(), "ultima": g.data.max(),
                      "bairro": g.bairro.agg(lambda s: s.mode().iat[0]), "lg": g.logradouro.first(), "num": g.num.first(),
                      "anoc": g.anoc.agg(lambda s: s.mode().iat[0] if s.notna().any() else np.nan)})
    # janelas recentes: mediana de cada prédio nos últimos 3 anos
    rec = a[pd.to_datetime(a.data) > tref - pd.Timedelta(days=365 * JANELA_ANOS)]
    pb = rec.groupby("b").agg(m2=("m2h", "median"), bairro=("bairro", lambda s: s.mode().iat[0]), lg=("logradouro", "first"),
                              anoc=("anoc", lambda s: s.mode().iat[0] if s.notna().any() else np.nan))
    # bairro: mediana entre prédios
    bai = pb.groupby("bairro").m2.agg(["median", "size"])
    p["m2_bairro"] = p.bairro.map(bai["median"].where(bai["size"] >= MIN_PREDIOS))
    p["np_bairro"] = p.bairro.map(bai["size"]).fillna(0).astype(int)
    # rua (mesmo bairro), sem o próprio prédio
    rua_m, rua_n = [], []
    grp = {k: d for k, d in pb.groupby(["lg", "bairro"])}
    for b, r in p.iterrows():
        d = grp.get((r.lg, r.bairro))
        v = d.m2[d.index != b] if d is not None else pd.Series(dtype=float)
        rua_m.append(v.median() if len(v) >= 2 else np.nan); rua_n.append(len(v))
    p["m2_rua"] = rua_m; p["np_rua"] = rua_n
    # ano de construção: prédios do mesmo bairro com ano ±5 (sem o próprio)
    ano_m, ano_n = [], []
    gb = {k: d for k, d in pb.dropna(subset=["anoc"]).groupby("bairro")}
    for b, r in p.iterrows():
        d = gb.get(r.bairro)
        if d is None or np.isnan(r.anoc):
            ano_m.append(np.nan); ano_n.append(0); continue
        v = d.m2[(d.anoc - r.anoc).abs().le(5) & (d.index != b)]
        ano_m.append(v.median() if len(v) >= MIN_PREDIOS else np.nan); ano_n.append(len(v))
    p["m2_ano"] = ano_m; p["np_ano"] = ano_n
    return p, idx


def combinar(p, pesos):
    W = np.array([pesos[c] for c in COMP], dtype=float)
    M = np.log(p[[f"m2_{c}" for c in COMP]].values)
    disp = ~np.isnan(M)
    w = np.where(disp, W, 0.0)
    s = w.sum(1)
    est = np.exp(np.nansum(np.where(disp, M, 0) * w, 1) / np.where(s > 0, s, np.nan))
    return est


def teste(itbi, pesos_json, corte="2025-10-01"):
    pesos = json.load(open(pesos_json))["componentes"]
    a = vendas(itbi)
    tr, te = a[a.data < corte], a[a.data >= corte]
    p, idx = componentes(tr)
    x = te.merge(p, left_on="b", right_index=True, how="inner")
    y = np.log(x.m2.values)

    def erro(est, msk=None):
        e = np.exp(y - np.log(est)) - 1
        if msk is not None:
            e = e[msk]
        e = e[~np.isnan(e)]
        return np.median(np.abs(e)), np.mean(np.abs(e) <= .1), np.mean(np.abs(e) <= .2), len(e)

    fmt = lambda r: f"erro mediano {r[0]:.1%} | ±10%: {r[1]:.0%} | ±20%: {r[2]:.0%} | n={r[3]}"
    print(f"Teste: vendas de {corte} em diante, previstas só com dados anteriores")
    print("  seus pesos        :", fmt(erro(combinar(x, pesos))), "|", pesos)
    for c in COMP:
        print(f"  só {c:13s}  :", fmt(erro(x[f'm2_{c}'].values)))
    # melhores pesos (grade de 10 em 10%)
    melhor = None
    for comb in itertools.product(range(11), repeat=len(COMP)):
        if sum(comb) != 10:
            continue
        pw = {c: v / 10 for c, v in zip(COMP, comb)}
        r = erro(combinar(x, pw))
        if melhor is None or r[0] < melhor[0][0]:
            melhor = (r, pw)
    print("  melhores pesos    :", fmt(melhor[0]), "|", melhor[1])
    tem = x.n_predio > 0
    for nome, pw in [("seus pesos", pesos), ("melhores", melhor[1])]:
        est = combinar(x, pw)
        print(f"  {nome:10s} prédio com 1-2 vendas:", fmt(erro(est, (x.n_predio <= 2).values)),
              "| 10+ vendas:", fmt(erro(est, (x.n_predio >= 10).values)))
    # cobertura: % de vendas cujo prédio não tem nenhum componente
    print("  componentes disponíveis (% das vendas):", {c: f"{x[f'm2_{c}'].notna().mean():.0%}" for c in COMP})


def gerar(itbi, pesos_json, saida):
    a = vendas(itbi)
    p, idx = componentes(a)
    p.attrs["indice_ref"] = idx.index[-1]
    p.to_pickle(saida)
    print(f"Componentes de {len(p)} prédios (referência {idx.index[-1]})")


if __name__ == "__main__":
    modo = sys.argv[1]
    {"teste": teste, "gerar": gerar}[modo](*sys.argv[2:])
