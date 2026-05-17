#!/bin/bash
TOKEN="3E9zandN1rhVtuXgSnAGT3fvjRw24scgZ2kUmvDnJRA"
BASE="http://localhost:8000"

run() {
  q="$1"
  r=$(curl -s --max-time 60 -X POST "$BASE/search" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"query\":\"$q\",\"limit\":3}")
  hits=$(echo "$r" | python3 -c "import sys,json;d=json.load(sys.stdin);print(len(d.get('hits',[])))" 2>/dev/null)
  ms=$(echo "$r" | python3 -c "import sys,json;d=json.load(sys.stdin);print(round(d.get('took_ms',0)))" 2>/dev/null)
  pq=$(echo "$r" | python3 -c "
import sys,json
d=json.load(sys.stdin)
p=d.get('parsed_query')
if p:
    print(f'query={p[\"query\"]!r} min={p[\"price_min\"]} max={p[\"price_max\"]} excl={p[\"exclude\"]}')
else:
    print('no parser')
" 2>/dev/null)
  echo "[$hits hits|${ms}ms] $q"
  echo "  => $pq"
  echo
}

run "автоматический выключатель 16А"
run "автоматический выключатель до 2400 рублей"
run "выключатель автоматический от 2400 до 3000 рублей"
run "автоматический выключатель 25А не ВА5735"
run "выключатель 63А до 2500р не ВА5735"
run "держатель для гитары до 1000 рублей"
run "ВА57-31-340010-УХЛ3"
run "автаматический выключятель"
