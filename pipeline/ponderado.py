"""Avaliação ponderada por componentes (R$/m² de área PBH, a valor de hoje).

Componentes por prédio:
  predio  - vendas no próprio prédio (corrigidas pelo índice; recentes pesam mais)
  ano     - prédios do mesmo bairro com ano de construção parecido (±5 anos), últimos 3 anos
  rua     - outros prédios da mesma rua no mesmo bairro, últimos 3 anos
  bairro  - prédios do bairro, últimos 3 anos
O valor final = média geométrica ponderada dos componentes (fórmula em dados/pesos.json), projetada até a data
da avaliação pela tendência recente do índice. O ajuste de conservação/reforma é aplicado na página.

Uso:
  python pipeline/ponderado.py teste itbi_bh.csv pesos.json [corte] [fim] -> validação fora da amostra
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
                      "n_predio": g.size(), "neff": g.w.sum(), "ultima": g.data.max(),
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


def pesos(row_neff, disp, cfg):
    """Pesos de cada componente para um prédio. disp: dict componente -> disponível?"""
    f = cfg["formula"]
    wp = row_neff / (row_neff + f["k"]) if disp["predio"] else 0.0
    rest = 1 - wp
    w = {"predio": wp, "ano": rest * f["resto"]["ano"], "rua": rest * f["resto"]["rua"], "bairro": rest * f["resto"]["bairro"]}
    if not disp["ano"]:
        w["rua"] += w["ano"] / 2; w["bairro"] += w["ano"] / 2; w["ano"] = 0.0
    tot = sum(w[c] for c in COMP if disp[c])
    return {c: (w[c] / tot if disp[c] and tot else 0.0) for c in COMP}


def estimar(df, cfg, datas_aval, ref, g):
    """Estimativa (R$/m² PBH) para cada linha de df na data de avaliação."""
    out, W = [], []
    for k, r in enumerate(df.itertuples()):
        disp = {c: getattr(r, f"m2_{c}") == getattr(r, f"m2_{c}") for c in COMP}
        w = pesos(r.neff if disp["predio"] else 0, disp, cfg)
        if not any(w.values()):
            out.append(np.nan); W.append(w); continue
        lm = sum(w[c] * np.log(getattr(r, f"m2_{c}")) for c in COMP if w[c])
        h = (pd.Timestamp(datas_aval[k]) - ref).days / 365.25 if cfg["formula"].get("tendencia") else 0
        out.append(float(np.exp(lm + np.log(g) * max(h, 0)))); W.append(w)
    return np.array(out), W


def tendencia(idx, corte):
    g = float((idx.iloc[-1] / idx.iloc[-5]) ** 0.5) if len(idx) >= 5 else 1.0     # crescimento anual, últimos 2 anos
    ultimo = idx.index[-1]                                                           # ex.: '2026S2'
    ref = pd.Timestamp(f"{ultimo[:4]}-{'04' if ultimo.endswith('S1') else '10'}-01")  # meio do semestre
    return g, min(ref, pd.Timestamp(corte))


def teste(itbi, pesos_json, corte="2025-10-01", fim="2026-10-01"):
    cfg = json.load(open(pesos_json))
    a = vendas(itbi)
    tr, te = a[a.data < corte], a[(a.data >= corte) & (a.data < fim)]
    p, idx = componentes(tr)
    g, ref = tendencia(idx, tr.data.max())
    x = te.merge(p, left_on="b", right_index=True, how="inner")
    est, _ = estimar(x, cfg, x.data.values, ref, g)
    e = x.m2.values / est - 1
    print(f"Teste {corte} a {fim}: erro mediano {np.median(np.abs(e)):.2%} | ±10% {np.mean(np.abs(e) <= .1):.0%} | "
          f"±20% {np.mean(np.abs(e) <= .2):.0%} | viés {np.median(e):+.1%} | n={len(e)} | tendência anual {g - 1:+.1%}")


def gerar(itbi, pesos_json, saida):
    a = vendas(itbi)
    p, idx = componentes(a)
    g, ref = tendencia(idx, a.data.max())
    p.attrs.update({"indice_ref": idx.index[-1], "tendencia_anual": g, "ref": str(ref.date())})
    p.to_pickle(saida)
    print(f"Componentes de {len(p)} prédios (referência {idx.index[-1]})")


if __name__ == "__main__":
    modo = sys.argv[1]
    {"teste": teste, "gerar": gerar}[modo](*sys.argv[2:])
