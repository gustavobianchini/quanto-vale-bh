"""Baixa os dados públicos usados no site.

- ITBI (PBH): todos os CSVs mensais do conjunto "itbi-relatorios"
- Cadastro Imobiliário (PBH): o arquivo mais recente de cada uma das 10 regionais
- Projetos de edificação licenciados (PBH): alvarás de construção, início de obra e baixa (habite-se); arquivo mais recente
- IPCA, CDI e dólar (Banco Central, SGS): séries mensais desde 2008
- Notícias (Google Notícias, RSS): manchetes recentes sobre o mercado imobiliário de BH (só título, veículo, data e link)

Uso: python pipeline/baixar.py dados/brutos
Os arquivos já baixados não são baixados de novo (o cadastro é sempre o mais recente).
"""
import json, os, re, sys, time, urllib.request, urllib.parse
from datetime import date

PORTAIS = ["https://ckan.pbh.gov.br", "https://dados.pbh.gov.br"]
REGIONAIS = ["barreiro", "centro-sul", "hipercentro", "leste", "nordeste", "noroeste", "norte", "oeste", "pampulha", "venda-nova"]
UA = {"User-Agent": "quanto-vale-bh/1.0 (+https://github.com/gustavobianchini/quanto-vale-bh)"}


def get(url, tentativas=4):
    for i in range(tentativas):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=300) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            if i == tentativas - 1:
                raise
            print(f"  erro ({e}); nova tentativa em {5 * (i + 1)}s")
            time.sleep(5 * (i + 1))


def ckan(acao, **params):
    erro = None
    for base in PORTAIS:
        try:
            url = f"{base}/api/3/action/{acao}?{urllib.parse.urlencode(params)}"
            d = json.loads(get(url))
            if d.get("success"):
                return d["result"]
        except Exception as e:  # noqa: BLE001
            erro = e
    raise RuntimeError(f"API do portal da PBH indisponível: {erro}")


def baixar(url, destino):
    tmp = destino + ".part"
    with open(tmp, "wb") as f:
        f.write(get(url))
    os.replace(tmp, destino)
    print(f"  baixado {os.path.basename(destino)} ({os.path.getsize(destino) / 1e6:.1f} MB)")


def itbi(pasta):
    os.makedirs(pasta, exist_ok=True)
    pkg = ckan("package_show", id="itbi-relatorios")
    escolhidos = {}
    for r in pkg["resources"]:
        nome = (r.get("name") or "") + " " + (r.get("url") or "")
        if not re.search(r"\.csv", nome, re.I) or "itbi_relatorio" not in nome.lower():
            continue
        m = re.search(r"itbi_relatorio_(\d{6}(?:_a_\d{6})?)(_corrigido)?", nome.lower())
        if not m:
            continue
        chave, corrigido = m.group(1), bool(m.group(2))
        # se houver versão corrigida do mesmo mês, fica com ela
        if chave in escolhidos and escolhidos[chave][1] and not corrigido:
            continue
        escolhidos[chave] = (r["url"], corrigido)
    if not escolhidos:
        raise RuntimeError("Nenhum CSV de ITBI encontrado no portal")
    validos = {f"pda_itbi_relatorio_{k}.csv" for k in escolhidos}
    for f in os.listdir(pasta):  # remove versões substituídas
        if f.endswith(".csv") and f not in validos:
            os.remove(os.path.join(pasta, f))
    novos = 0
    ultimo = max(k for k in escolhidos if len(k) == 6)
    for chave, (url, _) in sorted(escolhidos.items()):
        destino = os.path.join(pasta, f"pda_itbi_relatorio_{chave}.csv")
        if not os.path.exists(destino) or chave == ultimo:  # o último mês é sempre baixado de novo
            baixar(url, destino); novos += 1
    print(f"ITBI: {len(escolhidos)} arquivos no portal, {novos} baixados agora")


def cadastro(pasta):
    os.makedirs(pasta, exist_ok=True)
    datas = []
    for reg in REGIONAIS:
        try:
            pkg = ckan("package_show", id=f"cadastro-imobiliario-regional-{reg}")
        except RuntimeError:
            res = ckan("package_search", q=f"cadastro imobiliario regional {reg.replace('-', ' ')}", rows=5)
            pkg = next((p for p in res["results"] if p["name"].startswith("cadastro-imobiliario")), None)
            if not pkg:
                raise RuntimeError(f"Cadastro da regional {reg} não encontrado")
        cands = []
        for r in pkg["resources"]:
            m = re.search(r"(20\d{6})_regional_.*cadastro_imobiliario", (r.get("name") or "") + (r.get("url") or ""))
            if m:
                cands.append((m.group(1), r["url"]))
        if not cands:
            raise RuntimeError(f"Sem arquivos no cadastro da regional {reg}")
        data, url = max(cands)
        destino = os.path.join(pasta, f"{reg}_{data}.csv")
        for f in os.listdir(pasta):  # apaga versões antigas da regional
            if f.startswith(reg + "_") and f != os.path.basename(destino):
                os.remove(os.path.join(pasta, f))
        if not os.path.exists(destino):
            baixar(url, destino)
        datas.append(data)
    print(f"Cadastro: 10 regionais, versões {min(datas)} a {max(datas)}")


def alvaras(pasta):
    """Arquivo mais recente do conjunto "projeto-edificacao-licenciado" (snapshot completo, ~35 MB)."""
    os.makedirs(pasta, exist_ok=True)
    pkg = ckan("package_show", id="projeto-edificacao-licenciado")
    cands = []
    for r in pkg["resources"]:
        m = re.search(r"(20\d{6})_projeto_edificacao_licenciado", (r.get("name") or "") + (r.get("url") or ""))
        if m:
            cands.append((m.group(1), r["url"]))
    if not cands:
        raise RuntimeError("Sem arquivos de projetos licenciados")
    data, url = max(cands)
    destino = os.path.join(pasta, f"alvaras_{data}.csv")
    for f in os.listdir(pasta):
        if f.startswith("alvaras_") and f != os.path.basename(destino):
            os.remove(os.path.join(pasta, f))
    if not os.path.exists(destino):
        baixar(url, destino)
    print(f"Projetos licenciados: versão {data}")
    return destino


BUSCAS_NOTICIAS = [
    '"mercado imobiliário" "Belo Horizonte"',
    '"Belo Horizonte" (lançamento OR lançamentos OR empreendimento) (imobiliário OR apartamentos OR residencial)',
    '"Belo Horizonte" (imóveis OR apartamentos) (vendas OR preço OR aluguel OR financiamento)',
]
TEMA = re.compile(r"imóve|imobili|apartament|lançament|construtor|incorporador|minha casa|mcmv|aluguel|vgv|residencia|condomín"
                  r"|sinduscon|secovi|\bcmi\b|m²|metro quadrado|prédio|empreendiment|habitaç|financiamento|itbi|moradia", re.I)
LOCAL = re.compile(r"belo horizonte|\bbh\b|minas|mineir|nova lima|contagem|betim|pampulha|savassi|lagoa santa|grande bh", re.I)
LANC = re.compile(r"lançament|\bvgv\b|empreendiment|novo (complexo|residencial|prédio|edifício|condomínio)|\d+ apartamentos", re.I)


def noticias(destino, maximo=15):
    """Manchetes do Google Notícias (RSS) sobre imóveis em BH. Guarda só título, veículo, data e link."""
    import xml.etree.ElementTree as ET
    from email.utils import parsedate_to_datetime
    itens, vistos = [], set()
    for q in BUSCAS_NOTICIAS:
        url = "https://news.google.com/rss/search?" + urllib.parse.urlencode({"q": q + " when:45d", "hl": "pt-BR", "gl": "BR", "ceid": "BR:pt-419"})
        for it in ET.fromstring(get(url)).iter("item"):
            tit = (it.findtext("title") or "").strip(); fonte = (it.findtext("source") or "").strip()
            if fonte and tit.endswith(" - " + fonte):
                tit = tit[: -len(fonte) - 3]
            chave = re.sub(r"\W+", "", tit.lower())[:60]
            if not tit or chave in vistos or not TEMA.search(tit) or not LOCAL.search(tit):
                continue
            vistos.add(chave)
            try:
                dt = parsedate_to_datetime(it.findtext("pubDate")).date().isoformat()
            except Exception:  # noqa: BLE001
                dt = ""
            itens.append({"t": tit, "f": fonte, "d": dt, "u": (it.findtext("link") or "").strip(), "l": bool(LANC.search(tit))})
    itens.sort(key=lambda x: x["d"], reverse=True)
    if not itens:
        raise RuntimeError("nenhuma manchete encontrada")
    with open(destino, "w") as f:
        json.dump({"atualizado": date.today().isoformat(), "itens": itens[:maximo]}, f, ensure_ascii=False, indent=0)
    print(f"Notícias: {len(itens[:maximo])} manchetes ({sum(x['l'] for x in itens[:maximo])} sobre lançamentos)")


SGS = {"ipca": 433, "cdi": 4391, "usd": 3696}


def economia(destino, anterior=None):
    try:
        hoje = date.today().strftime("%d/%m/%Y")
        series = {}
        for k, cod in SGS.items():
            url = f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{cod}/dados?formato=json&dataInicial=01/01/2008&dataFinal={hoje}"
            d = json.loads(get(url))
            series[k] = {f"{x['data'][6:10]}-{x['data'][3:5]}": float(x["valor"]) for x in d}
        meses = sorted(set(series["ipca"]) & set(series["cdi"]) & set(series["usd"]))
        out = {"m": meses, "ipca": [series["ipca"][m] for m in meses], "cdi": [series["cdi"][m] for m in meses],
               "usd": [series["usd"][m] for m in meses]}
        with open(destino, "w") as f:
            json.dump(out, f, separators=(",", ":"))
        print(f"Economia: IPCA, CDI e dólar de {meses[0]} a {meses[-1]}")
    except Exception as e:  # noqa: BLE001
        if anterior and os.path.exists(anterior):
            print(f"Banco Central indisponível ({e}); mantendo séries anteriores")
            if anterior != destino:
                with open(anterior) as a, open(destino, "w") as b:
                    b.write(a.read())
        else:
            raise


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "noticias":      # só as manchetes (rotina diária)
        noticias(sys.argv[2]); sys.exit()
    base = sys.argv[1] if len(sys.argv) > 1 else "dados/brutos"
    itbi(os.path.join(base, "itbi"))
    cadastro(os.path.join(base, "cadastro"))
    economia(os.path.join(base, "econ.json"), anterior="dados/econ.json")
    try:  # bases complementares: se falharem, o site sai com a versão anterior
        alvaras(os.path.join(base, "alvaras"))
    except Exception as e:  # noqa: BLE001
        print(f"AVISO: projetos licenciados indisponíveis ({e})")
    try:
        noticias("dados/noticias.json")
    except Exception as e:  # noqa: BLE001
        print(f"AVISO: notícias indisponíveis ({e})")
