"""Exporta perfil + estimativa por prédio em shards data/p{s}.json (mesmo shard do logradouro).
Uso: python3 exportar_perfis.py valores.pkl pasta_data N
"""
import json, sys, zlib
import numpy as np, pandas as pd

# faixa P20–P80 de (venda real ÷ estimativa) na validação fora da amostra (vendas de out/2025 a set/2026)
BANDA = {"0": (0.91, 1.68), "1-2": (0.85, 1.19), "3-9": (0.89, 1.15), "10+": (0.93, 1.19)}


def bk(n):
    return "0" if n == 0 else "1-2" if n <= 2 else "3-9" if n <= 9 else "10+"


def main(src, outdir, N, calib=None):
    p = pd.read_pickle(src); N = int(N)
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
        lo, hi = BANDA[bk(r.n)]
        rec = {"ap": int(r.n_ap), "vg": int(r.n_vaga), "vr": int(r.n_vr), "lj": int(r.n_loja), "ca": int(r.n_ca),
               "pad": r.padrao, "tip": r.tipologia, "lat": round(r.lat, 6), "lon": round(r.lon, 6),
               "tipos": r.tipos, "ano": None if pd.isna(r.ano) else int(r.ano), "n": int(r.n),
               "m2": round(float(r.m2est)), "m2viz": round(float(r.m2viz)), "m2b": None if pd.isna(r.m2b) else round(float(r.m2b)),
               "bai": None if pd.isna(r.bairro) else r.bairro, "lo": lo, "hi": hi, "conf": bk(r.n)}
        if (r.lg, r.num) in cal:
            rec["fu"], rec["fuf"] = cal[(r.lg, r.num)]; rec["fuc"] = 1
        elif f_glob:
            rec["fu"], rec["fuf"], rec["fuc"] = f_glob, f"média de {n_cal} prédios conferidos", 0
        sh[zlib.crc32(r.lg.encode()) % N].append([r.lg, r.num, rec])
    for s, rows in sh.items():
        with open(f"{outdir}/p{s}.json", "w") as o:
            o.write("[\n" + ",\n".join(json.dumps(x, ensure_ascii=False, separators=(",", ":")) for x in rows) + "\n]")
    print(sum(len(v) for v in sh.values()), "prédios exportados")


if __name__ == "__main__":
    main(*sys.argv[1:])
