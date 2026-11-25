#!/usr/bin/env bash
# Atualização completa: baixa os dados, confere, recalcula e monta o site em _site/
# Uso: bash pipeline/rodar.sh            (baixa tudo do portal da PBH)
#      bash pipeline/rodar.sh --sem-baixar  (usa o que já está em dados/brutos/)
set -euo pipefail
cd "$(dirname "$0")/.."
B=dados/brutos; W=dados/work; S=_site
mkdir -p "$B/itbi" "$B/cadastro" "$W" "$S/data"

# CSVs colocados à mão em dados/manual/ (plano B, se o portal bloquear o download automático)
if compgen -G "dados/manual/itbi/*.csv" > /dev/null; then cp dados/manual/itbi/*.csv "$B/itbi/"; fi
if compgen -G "dados/manual/cadastro/*.csv" > /dev/null; then cp dados/manual/cadastro/*.csv "$B/cadastro/"; fi

if [[ "${1:-}" != "--sem-baixar" ]]; then
  echo "== 1/7 Baixando dados públicos"; python pipeline/baixar.py "$B"
fi
[[ -f "$B/econ.json" ]] || cp dados/econ.json "$B/econ.json"

echo "== 2/7 Consolidando ITBI";        python pipeline/consolidar.py "$B/itbi" "$W/itbi_bh.csv"
echo "== 3/7 Conferindo a base";        python pipeline/validar.py "$W/itbi_bh.csv"
echo "== 4/7 Histórico por rua";        rm -f "$S"/data/s*.json; python pipeline/gerar_shards.py "$W/itbi_bh.csv" "$S/data" 200
echo "== 5/7 Perfil dos prédios";       python pipeline/perfil_predios.py "$B/cadastro" "$W/perfil.pkl"
echo "== 6/7 Estimativas de valor";     python pipeline/avaliacao.py "$W/itbi_bh.csv" "$W/perfil.pkl" "$W"
                                        python pipeline/exportar_perfis.py "$W/valores.pkl" "$S/data" 200 dados/calibracao.csv
echo "== 7/7 Bairros e página";         python pipeline/bairros.py "$W/itbi_bh.csv" dados/calibracao.csv "$S/data" 20
                                        python pipeline/destaques.py "$W/itbi_bh.csv" dados/calibracao.csv "$B/econ.json" "$S/data/destaques.json"
                                        python pipeline/montar_site.py site/index.html "$S" "$W/itbi_bh.csv" "$W/valores.pkl" "$B/econ.json"
cp "$B/econ.json" dados/econ.json
echo "Pronto: site em $S/"
