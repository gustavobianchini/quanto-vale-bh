"""Gera índice + shards JSON para a página de busca. Uso: python3 gerar_shards.py itbi_bh.csv pasta_saida N"""
import csv, json, os, sys, zlib, collections
src, outdir, N = sys.argv[1], sys.argv[2], int(sys.argv[3])
os.makedirs(outdir, exist_ok=True)
shards = collections.defaultdict(list)
idx = collections.defaultdict(lambda: [0, collections.Counter()])
OC = {"RESIDENCIAL": "R", "NAO RESIDENCIAL": "N", "TERRITORIAL": "T"}
def f(x):
    if x == "": return None
    v = float(x); return int(v) if v == int(v) else round(v, 6)
with open(src, encoding="utf-8") as fh:
    for r in csv.DictReader(fh):
        lg = r["logradouro"]
        s = zlib.crc32(lg.encode()) % N
        shards[s].append([lg, r["data"], r["numero"], r["complemento"], r["bairro"], r["tipo"],
                          OC.get(r["ocupacao"], "?"), f(r["area_construida"]), f(r["area_terreno"]),
                          f(r["valor_declarado"]), f(r["valor_base"]), r["padrao"], r["ano_construcao"],
                          f(r["fracao_ideal"]), r["zona"]])
        idx[lg][0] += 1; idx[lg][1][r["bairro"]] += 1
for s, rows in shards.items():
    rows.sort(key=lambda x: (x[0], x[2], x[1]))
    g = collections.OrderedDict()
    for x in rows: g.setdefault(x[0], []).append(x[1:])
    with open(f"{outdir}/s{s}.json", "w") as o:
        o.write("[\n" + ",\n".join(json.dumps([lg, rs], ensure_ascii=False, separators=(",", ":")) for lg, rs in g.items()) + "\n]")
ix = [[lg, zlib.crc32(lg.encode()) % N, c, [b for b, _ in bc.most_common(4)]] for lg, (c, bc) in sorted(idx.items())]
with open(f"{outdir}/idx.json", "w") as o:
    o.write("[\n" + ",\n".join(json.dumps(x, ensure_ascii=False, separators=(",", ":")) for x in ix) + "\n]")
print(len(ix), "logradouros", len(shards), "shards")
