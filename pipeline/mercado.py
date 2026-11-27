"""Termômetro do mercado: liquidez, preço e oferta nova em BH.

Gera mercado.json com:
- mensal: vendas de apartamentos e casas por mês, separando prédios novos (até 2 anos de construção) e usados
- anual: vendas, volume em R$, ticket mediano e R$/m² útil de novos e usados
- preco: índice trimestral de preço de BH comparando os mesmos prédios (efeito fixo de prédio + trimestre), nominal e real (IPCA)
- giro: % dos apartamentos de BH que trocaram de dono nos últimos 12 meses
- mix: bairros cuja mediana caiu (ou subiu) só porque mudou o tipo de prédio negociado, comparado com a variação nos mesmos prédios
- oferta: unidades residenciais licenciadas, com obra iniciada e com baixa de construção (habite-se) por ano, e os maiores projetos recentes
- sinais: os indicadores do termômetro

Uso: python pipeline/mercado.py itbi_bh.csv calibracao.csv econ.json perfil.pkl pasta_alvaras saida.json
"""
import glob, json, os, re, sys
import numpy as np, pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
from destaques import preparar  # noqa: E402

NOVO_ANOS = 2                  # prédio "novo": venda até 2 anos depois do ano de construção
LACUNA = ("2014-05", "2015-07")  # meses em que a base da PBH está incompleta (vendas represadas lançadas em ago/2015)


def janela(fim, n=12, desloc=0):
    p = pd.Period(fim, "M")
    return [str(p - desloc - k) for k in range(n)]


def var_mesmos(aps, j1, j0, chave="bairro", min_predios=8):
    """Variação de R$/m² útil entre duas janelas comparando os mesmos prédios (mediana das variações por prédio),
    ao lado da variação aparente (mediana entre prédios) e da fatia de vendas em prédios novos em cada janela."""
    z1, z0 = aps[aps.mes.isin(j1)], aps[aps.mes.isin(j0)]
    b1 = z1.groupby([chave, "logradouro", "num"]).mu.median(); b0 = z0.groupby([chave, "logradouro", "num"]).mu.median()
    par = pd.concat([b1.rename("m1"), b0.rename("m0")], axis=1).dropna()
    par["lr"] = np.log(par.m1 / par.m0)
    mesmos = par.groupby(level=0).lr.agg(["median", "size"])
    ap1 = b1.groupby(level=0).agg(["median", "size"]); ap0 = b0.groupby(level=0).agg(["median", "size"])
    nv1 = z1.groupby(chave).novo.mean(); nv0 = z0.groupby(chave).novo.mean()
    t = pd.DataFrame({"mesmos": np.exp(mesmos["median"]) - 1, "n_mesmos": mesmos["size"],
                      "aparente": ap1["median"] / ap0["median"] - 1, "m2": ap1["median"], "m2_ant": ap0["median"],
                      "n1": ap1["size"], "n0": ap0["size"], "novo1": nv1, "novo0": nv0}).dropna(subset=["mesmos", "aparente"])
    return t[t.n_mesmos >= min_predios]


def indice_trimestral(aps, it=80):
    d = aps[~aps.mes.between(*LACUNA)].dropna(subset=["mu"])
    d = d[d.mu.between(500, 80000)]
    tri = pd.PeriodIndex(d.mes, freq="M").asfreq("Q").astype(str)
    y = np.log(d.mu.values); b, _ = pd.factorize(d.logradouro + "|" + d.num); t, tl = pd.factorize(tri, sort=True)
    fb = np.zeros(b.max() + 1); ft = np.zeros(len(tl)); nb = np.bincount(b); nt = np.bincount(t)
    for _ in range(it):
        fb = np.bincount(b, y - ft[t]) / nb
        ft = np.bincount(t, y - fb[b]) / nt
    ft -= ft[-1]
    return [[q, round(float(np.exp(v)), 4), int(n)] for q, v, n in zip(tl, ft, nt)]


COLS_ALV = ["NUMERO_PROCESSO", "TITULO_PROJETO", "TIPO", "USO_GERAL", "QTD_UND_RESIDENCIAL", "DATA_APROVACAO",
            "DT_CONCESSAO_ULTIMO_ALVARA", "DATA_COMUNICADO_INICIO_OBRA", "DATA_ULTIMA_BAIXA", "TIPO_ULTIMA_BAIXA",
            "ENDERECO", "QTDE_PAVIMENTOS"]


def ler_alvaras(pasta):
    fs = sorted(glob.glob(os.path.join(pasta, "alvaras_*.csv*")))
    if not fs:
        return None
    f = fs[-1]
    d = None
    for enc in ("utf-8", "latin-1"):
        try:
            d = pd.read_csv(f, sep=";", encoding=enc, dtype=str, usecols=lambda c: c.strip().upper() in COLS_ALV)
            break
        except UnicodeDecodeError:
            continue
    d.columns = [c.strip().upper() for c in d.columns]
    d = d[d.TIPO.eq("LICENCIAMENTO") & d.USO_GERAL.isin(["RESIDENCIAL", "MISTO"])]   # projetos novos (sem regularizações)
    m = re.search(r"(\d{8})", os.path.basename(f))
    d.attrs["versao"] = m.group(1) if m else ""
    return d


def _data(s, fmt):
    t = pd.to_datetime(s.fillna("").astype(str).str[:10], format=fmt, errors="coerce")
    return t.where((t >= "1900-01-01") & (t <= "2035-12-31"))


def oferta(alv, fim, end_bairro):
    """Oferta nova a partir dos projetos licenciados da PBH, um registro por processo (projeto inicial + modificações):
    unidades residenciais aprovadas, com início de obra comunicado e com baixa de construção (habite-se), por ano."""
    if alv is None or not len(alv):
        return None
    d = alv.copy()
    d["und"] = pd.to_numeric(d.QTD_UND_RESIDENCIAL, errors="coerce").fillna(0)
    d["aprov"] = _data(d.DATA_APROVACAO, "%d-%m-%Y")
    d["alvara"] = _data(d.DT_CONCESSAO_ULTIMO_ALVARA, "%Y-%m-%d")
    d["inicio"] = _data(d.DATA_COMUNICADO_INICIO_OBRA, "%Y-%m-%d")
    d["baixa"] = _data(d.DATA_ULTIMA_BAIXA, "%Y-%m-%d").where(d.TIPO_ULTIMA_BAIXA.notna())
    d["ini"] = d.TITULO_PROJETO.eq("APROVACAO INICIAL")
    d = d.sort_values("aprov")
    g = d.groupby("NUMERO_PROCESSO")
    p = pd.DataFrame({"und": g.und.last(),                                   # unidades do projeto aprovado mais recente
                      "aprov": d[d.ini].groupby("NUMERO_PROCESSO").aprov.min().reindex(g.size().index).fillna(g.aprov.min()),
                      "alvara": g.alvara.min(), "inicio": g.inicio.min(), "baixa": g.baixa.min(),
                      "end": g.ENDERECO.last(), "pav": pd.to_numeric(g.QTDE_PAVIMENTOS.last(), errors="coerce")})
    p.loc[p.und <= 0, "und"] = g.und.max()
    p = p[p.und > 0]
    fimp = pd.Timestamp(fim) + pd.offsets.MonthEnd(0)
    ev = {"aprovadas": "aprov", "iniciadas": "inicio", "entregues": "baixa"}
    anual = {k: p[p[c] <= fimp].groupby(p[c].dt.year).und.sum() for k, c in ev.items()}
    anos = range(2010, fimp.year + 1)
    tab = [[a] + [int(anual[k].get(a, 0)) for k in ev] for a in anos]
    def soma(c, de, ate):
        return int(p[(p[c] > de) & (p[c] <= ate)].und.sum())
    u12 = {k: soma(c, fimp - pd.DateOffset(months=12), fimp) for k, c in ev.items()}
    a12 = {k: soma(c, fimp - pd.DateOffset(months=24), fimp - pd.DateOffset(months=12)) for k, c in ev.items()}
    # maiores projetos aprovados nos últimos 12 meses
    r = p[(p.aprov > fimp - pd.DateOffset(months=12)) & (p.aprov <= fimp) & (p.und >= 20)].sort_values("und", ascending=False).head(15)
    rec = []
    for x in r.itertuples():
        end = str(x.end or "").strip()
        m = re.match(r"^(.*?),\s*(\d+)", end)
        bai = end_bairro.get((m.group(1), m.group(2).lstrip("0"))) if m else None
        if bai is None and m:
            bai = end_bairro.get((m.group(1), None))
        rec.append({"end": end or "endereço não informado", "bai": bai, "und": int(x.und),
                    "pav": None if pd.isna(x.pav) else int(x.pav), "aprov": x.aprov.date().isoformat(),
                    "alvara": None if pd.isna(x.alvara) else x.alvara.date().isoformat(),
                    "inicio": None if pd.isna(x.inicio) else x.inicio.date().isoformat()})
    return {"versao": alv.attrs.get("versao"), "anual": tab, "u12": u12, "a12": a12, "recentes": rec,
            "processos": int(len(p)), "inicio_desde": 2019}


# Termômetro: cada sinal vira uma nota de -1 (esfriando) a +1 (aquecendo), dividindo a variação pela escala
# em que o sinal é "forte"; a nota final é a média. Pesos iguais, de propósito: é um resumo, não um modelo.
SINAIS = [
    ("vendas", "Vendas nos últimos 12 meses", "vendas_var", 0.10),
    ("historico", "Vendas contra a média de 2016 a 2025", "vs_hist", 0.15),
    ("preco", "Preço acima da inflação (mesmos prédios)", "preco_real", 0.04),
    ("giro", "Revendas de apartamentos usados (giro do estoque)", "giro_var", 0.10),
    ("oferta", "Unidades aprovadas para construir", "aprovadas_var", 0.25),
]
FAIXAS = [(-0.5, "Frio"), (-0.15, "Esfriando"), (0.15, "Estável"), (0.5, "Aquecido"), (9, "Muito aquecido")]


def termometro(s):
    if s.get("giro") and s.get("giro_ant"):
        s["giro_var"] = round(s["giro"] / s["giro_ant"] - 1, 4)
    comp = []
    for k, nome, campo, esc in SINAIS:
        v = s.get(campo)
        if v is None:
            continue
        comp.append({"k": k, "nome": nome, "v": v, "nota": round(float(np.clip(v / esc, -1, 1)), 3)})
    nota = float(np.mean([c["nota"] for c in comp])) if comp else 0.0
    rot = next(r for lim, r in FAIXAS if nota < lim)
    return {"nota": round(nota, 3), "rotulo": rot, "componentes": comp, "faixas": FAIXAS}


def main(itbi, calib, econ, perfil, pasta_alv, saida):
    r = preparar(itbi, calib)
    r["anoc"] = pd.to_numeric(r.ano_construcao, errors="coerce")
    r["idade"] = r.data.str[:4].astype(int) - r.anoc
    r["novo"] = r.idade.between(-10, NOVO_ANOS)
    fim = r.mes.max()
    res = r[r.tipo.isin(["AP", "CA"])]
    ok = res[~res.suspeita & res.valor_declarado.notna() & (res.valor_declarado >= 30000)]
    aps = ok[(ok.tipo == "AP") & (ok.area_construida >= 20)]

    # ---- vendas por mês
    g = res.groupby("mes")
    mensal = pd.DataFrame({"ap": g.apply(lambda x: (x.tipo == "AP").sum()), "ca": g.apply(lambda x: (x.tipo == "CA").sum()),
                           "novo": g.apply(lambda x: ((x.tipo == "AP") & x.novo).sum()),
                           "vol": ok.groupby("mes").valor_declarado.sum()}).fillna(0)
    mensal = mensal[mensal.index >= "2008-01"]
    lst_mensal = [[m, int(x.ap), int(x.ca), int(x.novo), round(float(x.vol) / 1e6, 1)] for m, x in mensal.iterrows()]

    # ---- por ano
    anual = []
    for a, x in res.groupby(res.data.str[:4]):
        o = ok[ok.data.str[:4] == a]; ap_ = aps[aps.data.str[:4] == a]
        meses = x.mes.nunique()
        anual.append([a, int((x.tipo == "AP").sum()), int((x.tipo == "CA").sum()), int(((x.tipo == "AP") & x.novo).sum()),
                      round(float(o.valor_declarado.sum()) / 1e9, 2), round(float(o[o.tipo == "AP"].valor_declarado.median())),
                      round(float(ap_[ap_.novo].mu.median())) if ap_.novo.sum() >= 30 else None,
                      round(float(ap_[~ap_.novo].mu.median())), int(meses)])
    # acumulado do ano até o mesmo mês, para comparar o ano corrente
    mfim = fim[5:]
    ytd = {a: int(((res.data.str[:4] == a) & (res.mes.str[5:] <= mfim) & (res.tipo == "AP")).sum()) for a in [fim[:4], str(int(fim[:4]) - 1)]}

    # ---- índice de preço (mesmos prédios), nominal e real
    e = json.load(open(econ)); ipc = pd.Series(np.cumprod([1 + v / 100 for v in e["ipca"]]), index=e["m"])
    idx = indice_trimestral(aps)
    def ipca_tri(q):
        p = pd.Period(q, "Q"); ms = [str(p.asfreq("M", "start") + k) for k in range(3)]
        v = ipc.reindex(ms).dropna(); return float(v.mean()) if len(v) else float(ipc.iloc[-1])
    base_ipca = ipca_tri(idx[-1][0])
    preco = [[q, v, round(v * base_ipca / ipca_tri(q), 4), n] for q, v, n in idx]

    # ---- sinais (12 meses até o último mês contra os 12 anteriores)
    j1, j0 = janela(fim), janela(fim, desloc=12)
    ap_n = res[res.tipo == "AP"].groupby("mes").size()
    v1, v0 = int(ap_n.reindex(j1).fillna(0).sum()), int(ap_n.reindex(j0).fillna(0).sum())
    hist = []  # médias de 12 meses de 2016 a 2025 (fora da lacuna)
    for a in range(2016, int(fim[:4])):
        hist.append(int(ap_n.reindex([f"{a}-{m:02d}" for m in range(1, 13)]).fillna(0).sum()))
    media_hist = float(np.mean(hist))
    p4 = [x[1] for x in idx[-4:]]; p8 = [x[1] for x in idx[-8:-4]]
    preco_nom = float(np.mean(p4) / np.mean(p8) - 1)
    ip12 = float(ipc.get(fim, ipc.iloc[-1]) / ipc.get(j0[0], ipc.iloc[-13]) - 1)
    nov1 = float(res[(res.tipo == "AP") & res.mes.isin(j1)].novo.mean()); nov0 = float(res[(res.tipo == "AP") & res.mes.isin(j0)].novo.mean())

    # giro: revendas (prédios usados) em 12 meses / apartamentos existentes (só endereços do cadastro)
    giro = None
    if perfil and os.path.exists(perfil):
        pf = pd.read_pickle(perfil); estoque = int(pf.n_ap.sum())
        chaves = set(pf.lg + "|" + pf.num.astype(str))
        usa = res[(res.tipo == "AP") & ~res.novo & (res.logradouro + "|" + res.num).isin(chaves)]   # só revendas (prédios usados)
        u12 = usa[usa.mes.isin(j1)]; u0_ = usa[usa.mes.isin(j0)]
        giro = {"estoque": estoque, "vendas12": int(len(u12)), "pct": round(len(u12) / estoque, 4), "pct_ant": round(len(u0_) / estoque, 4)}

    # mix: bairros (12 meses contra 12 anteriores)
    mx = var_mesmos(aps, j1, j0)
    mx = mx[(mx.n1 >= 15) & (mx.n0 >= 15)]
    mx["efeito_mix"] = (1 + mx.aparente) / (1 + mx.mesmos) - 1
    enganosos = mx[(mx.efeito_mix.abs() >= 0.05) & (np.sign(mx.aparente) != np.sign(mx.mesmos)) | (mx.efeito_mix.abs() >= 0.10)]
    enganosos = enganosos.reindex(enganosos.efeito_mix.abs().sort_values(ascending=False).index).head(12)
    lst_mix = [{"bai": b, "aparente": round(float(x.aparente), 4), "mesmos": round(float(x.mesmos), 4), "n": int(x.n_mesmos),
                "novo1": round(float(x.novo1), 3), "novo0": round(float(x.novo0), 3)} for b, x in enganosos.iterrows()]
    geral = var_mesmos(aps.assign(tudo="BH"), j1, j0, chave="tudo", min_predios=1)

    # oferta nova (projetos licenciados)
    try:
        eb = r.groupby(["logradouro", "num"]).bairro.agg(lambda v: v.mode().iat[0]).to_dict()
        eb.update({(lg, None): b for lg, b in r.groupby("logradouro").bairro.agg(lambda v: v.mode().iat[0]).items()})
        of = oferta(ler_alvaras(pasta_alv), fim, eb)
    except Exception as ex:  # noqa: BLE001
        print(f"AVISO: oferta indisponível ({ex})"); of = None

    sinais = {"vendas12": v1, "vendas12_ant": v0, "vendas_var": round(v1 / v0 - 1, 4), "media_hist": round(media_hist),
              "vs_hist": round(v1 / media_hist - 1, 4), "preco_nom": round(preco_nom, 4), "ipca12": round(ip12, 4),
              "preco_real": round((1 + preco_nom) / (1 + ip12) - 1, 4), "novo12": round(nov1, 4), "novo12_ant": round(nov0, 4),
              "mesmos_bh": round(float(geral.mesmos.iloc[0]), 4), "aparente_bh": round(float(geral.aparente.iloc[0]), 4)}
    if giro:
        sinais["giro"] = giro["pct"]; sinais["giro_ant"] = giro["pct_ant"]
    if of and of["a12"].get("aprovadas"):
        sinais["aprovadas"] = of["u12"]["aprovadas"]; sinais["aprovadas_ant"] = of["a12"]["aprovadas"]
        sinais["aprovadas_var"] = round(of["u12"]["aprovadas"] / of["a12"]["aprovadas"] - 1, 4)

    sinais["termometro"] = termometro(sinais)
    out = {"meta": {"fim": fim, "ini12": j1[-1], "lacuna": LACUNA, "novo_anos": NOVO_ANOS},
           "mensal": lst_mensal, "anual": anual, "ytd": ytd, "preco": preco, "sinais": sinais, "giro": giro,
           "mix": lst_mix, "oferta": of}
    with open(saida, "w") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"Mercado até {fim}: {v1} aptos em 12 meses ({v1 / v0 - 1:+.1%}); preço real {sinais['preco_real']:+.1%}; "
          f"{len(lst_mix)} bairros com efeito de mix; oferta {'ok' if of else 'indisponível'}")


if __name__ == "__main__":
    main(*sys.argv[1:])
