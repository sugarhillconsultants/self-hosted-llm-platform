.PHONY: test local-up local-down smoke eval loadtest up down cost

test:          ; cd gateway && python -m pytest -q
local-up:      ; ./local/kind-up.sh
local-down:    ; ./local/kind-down.sh
smoke:         ; ./local/smoke-test.sh
eval:          ; @echo "Phase 5: python -m evals.run --suite all"
loadtest:      ; @echo "Phase 3: loadtest/run.sh"
up:            ; ./scripts/up.sh
down:          ; ./scripts/down.sh
cost:          ; ./scripts/cost-report.sh
