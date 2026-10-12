#!/usr/bin/env bash
set -uo pipefail
API=http://localhost:8000/v1
j() { python3 -c "import sys,json;print(json.load(sys.stdin)$1)"; }
code() { curl -s -o /dev/null -w '%{http_code}' "$@"; }

echo "── registration ──────────────────────────────"
curl -s -X POST $API/users -H 'content-type: application/json' \
  -d '{"email":"alice@x.com","password":"correct-horse-battery","display_name":"Alice"}' >/dev/null
curl -s -X POST $API/users -H 'content-type: application/json' \
  -d '{"email":"bob@x.com","password":"correct-horse-battery","display_name":"Bob"}' >/dev/null
echo "duplicate email → $(code -X POST $API/users -H 'content-type: application/json' \
  -d '{"email":"alice@x.com","password":"correct-horse-battery","display_name":"A"}')  (expect 409)"
echo "weak password   → $(code -X POST $API/users -H 'content-type: application/json' \
  -d '{"email":"c@x.com","password":"short","display_name":"C"}')  (expect 422)"

echo "── authentication ────────────────────────────"
A=$(curl -s -X POST $API/sessions -H 'content-type: application/json' \
     -d '{"email":"alice@x.com","password":"correct-horse-battery"}' | j '["access_token"]')
B=$(curl -s -X POST $API/sessions -H 'content-type: application/json' \
     -d '{"email":"bob@x.com","password":"correct-horse-battery"}' | j '["access_token"]')
echo "no token        → $(code $API/users/me)  (expect 401)"
echo "bad token       → $(code $API/users/me -H 'Authorization: Bearer nonsense')  (expect 401)"
echo "good token      → $(code $API/users/me -H "Authorization: Bearer $A")  (expect 200)"
echo "wrong password  → $(code -X POST $API/sessions -H 'content-type: application/json' \
  -d '{"email":"alice@x.com","password":"wrong-wrong-wrong"}')  (expect 401)"

echo "── authorization ─────────────────────────────"
G=$(curl -s -X POST $API/groups -H "Authorization: Bearer $A" \
     -H 'content-type: application/json' -d '{"name":"Engineering","slug":"eng"}' | j '["id"]')
echo "non-member reads members → $(code $API/groups/$G/members -H "Authorization: Bearer $B")  (expect 404, hides existence)"
BOB=$(curl -s $API/users/me -H "Authorization: Bearer $B" | j '["id"]')
curl -s -X PUT $API/groups/$G/members/$BOB -H "Authorization: Bearer $A" \
  -H 'content-type: application/json' -d '{"role":"member"}' >/dev/null
echo "member reads members     → $(code $API/groups/$G/members -H "Authorization: Bearer $B")  (expect 403, lacks permission)"

echo "── idempotency ───────────────────────────────"
K=$(uuidgen)
BODY='{"description":"Laptop","amount_cents":129900,"currency":"EUR"}'
E1=$(curl -s -X POST $API/groups/$G/expenses -H "Authorization: Bearer $B" \
      -H 'content-type: application/json' -H "Idempotency-Key: $K" -d "$BODY" | j '["id"]')
E2=$(curl -s -X POST $API/groups/$G/expenses -H "Authorization: Bearer $B" \
      -H 'content-type: application/json' -H "Idempotency-Key: $K" -d "$BODY" | j '["id"]')
[ "$E1" = "$E2" ] && echo "same key, same body → SAME id ($E1)  ✓" || echo "MISMATCH ✗"
echo "same key, new body  → $(code -X POST $API/groups/$G/expenses -H "Authorization: Bearer $B" \
  -H 'content-type: application/json' -H "Idempotency-Key: $K" \
  -d '{"description":"Other","amount_cents":100,"currency":"EUR"}')  (expect 422)"

echo "── state machine ─────────────────────────────"
echo "approve a draft   → $(code -X POST $API/expenses/$E1/approval -H "Authorization: Bearer $A" \
  -H 'content-type: application/json' -d '{}')  (expect 409)"
curl -s -X POST $API/expenses/$E1/submission -H "Authorization: Bearer $B" \
  -H 'content-type: application/json' -d '{}' >/dev/null
echo "member approves   → $(code -X POST $API/expenses/$E1/approval -H "Authorization: Bearer $B" \
  -H 'content-type: application/json' -d '{}')  (expect 403)"
echo "admin approves    → $(code -X POST $API/expenses/$E1/approval -H "Authorization: Bearer $A" \
  -H 'content-type: application/json' -d '{}')  (expect 201)"
echo "approve again     → $(code -X POST $API/expenses/$E1/approval -H "Authorization: Bearer $A" \
  -H 'content-type: application/json' -d '{}')  (expect 409)"

echo "── concurrency & caching ─────────────────────"
ET=$(curl -sI $API/expenses/$E1 -H "Authorization: Bearer $A" | grep -i '^etag' | tr -d '\r' | cut -d' ' -f2)
echo "If-None-Match     → $(code $API/expenses/$E1 -H "Authorization: Bearer $A" -H "If-None-Match: $ET")  (expect 304)"
echo "stale If-Match    → $(code -X PATCH $API/expenses/$E1 -H "Authorization: Bearer $A" \
  -H 'content-type: application/json' -H 'If-Match: W/\"bogus.1\"' -d '{"description":"x"}')  (expect 412)"

echo "── mass assignment ───────────────────────────"
echo "unknown field     → $(code -X PATCH $API/users/me -H "Authorization: Bearer $B" \
  -H 'content-type: application/json' -d '{"display_name":"Bob","is_active":false}')  (expect 422)"
