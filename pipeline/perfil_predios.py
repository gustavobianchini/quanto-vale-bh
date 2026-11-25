"""Perfil por prédio (logradouro + número) a partir do Cadastro Imobiliário da PBH.
Uso: python3 perfil_predios.py cadastro.pkl saida.pkl
"""
import math, re, sys, unicodedata
import numpy as np, pandas as pd


def norm(s):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().upper()).strip()


def utm_to_latlon(E, N, zone=23, south=True):
    """UTM (SIRGAS 2000 ~ WGS84) -> lat/lon em graus."""
    a, f, k0 = 6378137.0, 1 / 298.257222101, 0.9996
    e2 = f * (2 - f); ep2 = e2 / (1 - e2)
    x = E - 500000.0; y = N - (10000000.0 if south else 0)
    M = y / k0
    mu = M / (a * (1 - e2 / 4 - 3 * e2**2 / 64 - 5 * e2**3 / 256))
    e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))
    p1 = mu + (3 * e1 / 2 - 27 * e1**3 / 32) * math.sin(2 * mu) + (21 * e1**2 / 16 - 55 * e1**4 / 32) * math.sin(4 * mu) \
        + (151 * e1**3 / 96) * math.sin(6 * mu) + (1097 * e1**4 / 512) * math.sin(8 * mu)
    C1 = ep2 * math.cos(p1)**2; T1 = math.tan(p1)**2
    N1 = a / math.sqrt(1 - e2 * math.sin(p1)**2); R1 = a * (1 - e2) / (1 - e2 * math.sin(p1)**2)**1.5
    D = x / (N1 * k0)
    lat = p1 - (N1 * math.tan(p1) / R1) * (D**2 / 2 - (5 + 3 * T1 + 10 * C1 - 4 * C1**2 - 9 * ep2) * D**4 / 24
                                           + (61 + 90 * T1 + 298 * C1 + 45 * T1**2 - 252 * ep2 - 3 * C1**2) * D**6 / 720)
    lon = (D - (1 + 2 * T1 + C1) * D**3 / 6 + (5 - 2 * C1 + 28 * T1 + 3 * C1**2 + 8 * ep2 + 24 * T1**2) * D**5 / 120) / math.cos(p1)
    return math.degrees(lat), (zone * 6 - 183) + math.degrees(lon)


def centroid(wkt):
    nums = re.findall(r"(-?\d+(?:\.\d+)?) (-?\d+(?:\.\d+)?)", wkt or "")
    if not nums:
        return (np.nan, np.nan)
    xs = np.array([float(a) for a, _ in nums]); ys = np.array([float(b) for _, b in nums])
    return utm_to_latlon(xs.mean(), ys.mean())


TC = {"APARTAMENTO": "AP", "VAGA DE GARAGEM RESIDENCIAL": "VR", "VAGA DE GARAGEM NAO RESIDENCIAL": "VC",
      "SALA": "SL", "LOJA": "LJ", "CASA": "CA", "APARTAMENTO COM OCUPACAO NAO RESIDENCIAL": "AC"}


def moda(s):
    m = s.dropna().mode()
    return m.iat[0] if len(m) else ""


COLS = ["TIPO_LOGRADOURO", "NOME_LOGRADOURO", "NUMERO_IMOVEL", "TIPO_CONSTRUTIVO", "AREA_CONSTRUCAO", "FRACAO_IDEAL",
        "AREA_TERRENO", "NULOTCTM", "PADRAO_ACABAMENTO", "TIPOLOGIA", "GEOMETRIA"]


def ler_cadastros(pasta):
    """Lê o CSV mais recente de cada regional (pasta com arquivos <regional>_<AAAAMMDD>.csv)."""
    import glob, os
    partes, datas = [], []
    for f in sorted(glob.glob(os.path.join(pasta, "*.csv"))):
        d = pd.read_csv(f, sep=";", dtype=str, usecols=lambda c: c in COLS)
        d["REGIONAL"] = os.path.basename(f).rsplit("_", 1)[0]
        partes.append(d)
        m = re.search(r"(20\d{6})", os.path.basename(f))
        if m:
            datas.append(m.group(1))
        print(f"  {os.path.basename(f)}: {len(d)} unidades")
    return pd.concat(partes, ignore_index=True), (f"{min(datas)}-{max(datas)}" if datas else "")


def main(src, out):
    if src.endswith(".pkl"):
        c = pd.read_pickle(src); data = ""
    else:
        c, data = ler_cadastros(src)
    for x in ["AREA_CONSTRUCAO", "FRACAO_IDEAL", "AREA_TERRENO"]:
        c[x] = pd.to_numeric(c[x], errors="coerce")
    c["lg"] = (c.TIPO_LOGRADOURO + " " + c.NOME_LOGRADOURO).map(norm)
    c["num"] = c.NUMERO_IMOVEL.fillna("").str.lstrip("0")
    c["tc"] = c.TIPO_CONSTRUTIVO.map(TC).fillna("OUT")
    # um centróide por lote
    com_ap = set(zip(c.lg[c.tc == "AP"], c.num[c.tc == "AP"]))  # só endereços com apartamentos
    c = c[[k in com_ap for k in zip(c.lg, c.num)]]
    lots = c.drop_duplicates("NULOTCTM")[["NULOTCTM", "GEOMETRIA"]]
    ll = {k: centroid(g) for k, g in zip(lots.NULOTCTM, lots.GEOMETRIA)}
    rows = []
    for (lg, num), d in c.groupby(["lg", "num"]):
        ap = d[d.tc == "AP"]
        tipos = ap.groupby(ap.AREA_CONSTRUCAO.round(2)).size().sort_index()
        lot = moda(d.NULOTCTM)
        lat, lon = ll.get(lot, (np.nan, np.nan))
        rows.append(dict(lg=lg, num=num, lote=lot, lat=lat, lon=lon, regional=moda(d.REGIONAL) if "REGIONAL" in d else "",
                         n_ap=len(ap), n_ca=int((d.tc == "CA").sum()),
                         n_vaga=int(d.tc.isin(["VR", "VC"]).sum()), n_vr=int((d.tc == "VR").sum()),
                         n_loja=int(d.tc.isin(["LJ", "SL"]).sum()), n_un=len(d),
                         tipos=[[float(a), int(n)] for a, n in tipos.items()],
                         padrao=moda(ap.PADRAO_ACABAMENTO) or moda(d.PADRAO_ACABAMENTO),
                         tipologia=moda(ap.TIPOLOGIA),
                         area_terreno=float(d.AREA_TERRENO.max()),
                         area_total=float(d.AREA_CONSTRUCAO.sum())))
    p = pd.DataFrame(rows)
    p.attrs["data_cadastro"] = data
    p.to_pickle(out)
    print(len(p), "endereços;", (p.n_ap > 0).sum(), "com apartamentos;", p.lat.notna().mean().round(3), "com coordenada")
    print(p[["lat", "lon"]].describe().loc[["min", "max"]])


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
