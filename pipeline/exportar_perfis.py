"""Exporta perfil + estimativa por prédio em shards data/p{s}.json (mesmo shard do logradouro).
Uso: python3 exportar_perfis.py valores.pkl pasta_data N
"""
import json, sys, zlib
import numpy as np, pandas as pd

# faixa P20–P80 de (venda real ÷ estimativa) na validação fora da amostra (vendas de out/2025 a set/2026)
# prédios sem venda: estimativa pelos vizinhos (modelo v1); com venda: modelo ponderado (pipeline/ponderado.py),
# faixa P20–P80 relativa à mediana na validação de out/2025–set/2026 (BH inteira)
BANDA = {"0": (0.91, 1.68), "1-2": (0.87, 1.16), "3-9": (0.88, 1.15), "10+": (0.90, 1.12)}
COMP = ["predio", "ano", "rua", "bairro"]


def faixa(wp, cfg):
    for f in cfg["faixas_confianca"]:
        if wp >= f["peso_predio_min"]:
            return f["rotulo"], f["p20"], f["p80"]


def main(src, outdir, N, calib=None, comps=None, pesos=None):
    p = pd.read_pickle(src); N = int(N)
    C = pd.read_pickle(comps) if comps else None
    cfg = json.load(open(pesos)) if pesos else None
    if C is not None and cfg:
        import sys as _s, os as _o
        _s.path.insert(0, _o.path.dirname(__file__))
        from ponderado import estimar
        hoje = pd.Timestamp.today().normalize()
        g = C.attrs.get("tendencia_anual", 1.0); ref = pd.Timestamp(C.attrs.get("ref", str(hoje.date())))
        est, W = estimar(C, cfg, [hoje] * len(C), ref, g)
        C = C.assign(m2_final=est, w=W)
        tend = g ** max((hoje - ref).days / 365.25, 0) if cfg["formula"].get("tendencia") else 1.0
    cal = {}
    if calib:
        c = pd.read_csv(calib)
        c["f"] = c.area_util / c.area_pbh
        cal = {(r.lg, str(r.num)): (round(r.f, 4), r.fonte) for r in c.itertuples()}
        f_glob = round(float(c.f.median()), 3); n_cal = len(c)
    else:
        f_glob, n_cal = None, 0
    sh = {s: [] for s in range(N)}
    for r in p.itertuples():
        b = f"{r.lg}|{r.num}"
        cr = C.loc[b] if C is not None and b in C.index else None
        n = int(cr["n_predio"]) if cr is not None else 0
        lo, hi = BANDA["0"]
        rec = {"ap": int(r.n_ap), "vg": int(r.n_vaga), "vr": int(r.n_vr), "lj": int(r.n_loja), "ca": int(r.n_ca),
               "pad": r.padrao, "tip": r.tipologia, "lat": round(r.lat, 6), "lon": round(r.lon, 6),
               "tipos": r.tipos, "ano": None if pd.isna(r.ano) else int(r.ano), "n": n, "reg": getattr(r, "regional", ""),
               "m2": round(float(r.m2est)), "m2viz": round(float(r.m2viz)), "m2b": None if pd.isna(r.m2b) else round(float(r.m2b)),
               "bai": None if pd.isna(r.bairro) else r.bairro, "lo": lo, "hi": hi, "conf": "baixa"}
        if cr is not None and cfg and cr["m2_final"] == cr["m2_final"]:
            w = cr["w"]
            if True:
                rec["m2"] = round(float(cr["m2_final"])); rec["w"] = {c: round(v, 3) for c, v in w.items()}
                rec["conf"], rec["lo"], rec["hi"] = faixa(w["predio"], cfg); rec["tend"] = round(tend - 1, 4)
                rec["c"] = {c: [None if pd.isna(cr[f"m2_{c}"]) else round(float(cr[f"m2_{c}"])),
                                int(cr[{"predio": "n_predio", "ano": "np_ano", "rua": "np_rua", "bairro": "np_bairro"}[c]])] for c in COMP}
                rec["bai"] = cr["bairro"]
                if not pd.isna(cr["anoc"]):
                    rec["ano"] = int(cr["anoc"])
        if (r.lg, r.num) in cal:
            rec["fu"], rec["fuf"] = cal[(r.lg, r.num)]; rec["fuc"] = 1
        elif f_glob:
            rec["fu"], rec["fuf"], rec["fuc"] = f_glob, f"mediana de {n_cal} prédios conferidos", 0
        sh[zlib.crc32(r.lg.encode()) % N].append([r.lg, r.num, rec])
    for s, rows in sh.items():
        with open(f"{outdir}/p{s}.json", "w") as o:
            o.write("[\n" + ",\n".join(json.dumps(x, ensure_ascii=False, separators=(",", ":")) for x in rows) + "\n]")
    print(sum(len(v) for v in sh.values()), "prédios exportados")


if __name__ == "__main__":
    main(*sys.argv[1:])
