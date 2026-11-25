"""Consolida os CSVs de ITBI da PBH numa base única padronizada.

Uso: python3 consolidar.py <pasta_com_csvs> <saida.csv>
"""
import csv, glob, os, re, sys, unicodedata

COLS = ["endereco", "bairro", "ano_construcao", "area_terreno", "area_construida",
        "area_somada", "padrao", "fracao_ideal", "tipo", "ocupacao",
        "valor_declarado", "valor_base", "zona", "data"]

CEP = re.compile(r"^\d{5}-?\d{3}$")


def num(s):
    s = (s or "").strip()
    if not s:
        return None
    if "," in s:  # formato BR: 1.234,56 (nos arquivos, ponto sem vírgula não ocorre)
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s.upper()).strip()


def parse_endereco(e):
    parts = [p.strip() for p in e.split(" - ")]
    # remove "BELO HORIZONTE", "MG" do fim
    while parts and parts[-1] in ("MG", "BELO HORIZONTE"):
        parts.pop()
    cep = ""
    if parts and CEP.match(parts[-1]):
        cep = parts.pop()
    bairro = parts.pop() if len(parts) > 1 else ""
    first = parts[0] if parts else ""
    compl = " - ".join(parts[1:])
    m = re.match(r"^(.*?)\s+(\d+(?:-?[A-Z])?)$", first)
    if m:
        logr, numero = m.group(1), m.group(2)
    else:
        logr, numero = first, ""
    return logr, numero, compl, bairro, cep


def main(pasta, saida):
    arquivos = sorted(glob.glob(os.path.join(pasta, "*.csv")))
    n = 0
    with open(saida, "w", newline="", encoding="utf-8") as out:
        w = csv.writer(out)
        w.writerow(["data", "logradouro", "numero", "complemento", "bairro", "cep",
                    "ano_construcao", "area_terreno", "area_construida", "area_somada",
                    "padrao", "fracao_ideal", "tipo", "ocupacao", "valor_declarado",
                    "valor_base", "zona", "arquivo"])
        for f in arquivos:
            with open(f, encoding="utf-8-sig", newline="") as fh:
                r = csv.reader(fh, delimiter=";")
                next(r)
                for row in r:
                    if len(row) < 14:
                        continue
                    d = dict(zip(COLS, row[:14]))
                    logr, numero, compl, bairro_end, cep = parse_endereco(norm(d["endereco"]))
                    dd, mm, yy = (d["data"].strip().split("/") + ["", "", ""])[:3]
                    data = f"{yy}-{mm}-{dd}" if yy else ""
                    w.writerow([data, logr, numero, compl,
                                norm(d["bairro"]) or bairro_end, cep,
                                d["ano_construcao"].strip(),
                                num(d["area_terreno"]), num(d["area_construida"]),
                                num(d["area_somada"]), d["padrao"].strip(),
                                num(d["fracao_ideal"]), d["tipo"].strip(),
                                norm(d["ocupacao"]), num(d["valor_declarado"]),
                                num(d["valor_base"]), d["zona"].strip(),
                                re.sub(r"^[0-9a-f]{8}-", "", os.path.basename(f))])
                    n += 1
    print(f"{n} linhas de {len(arquivos)} arquivos -> {saida}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
