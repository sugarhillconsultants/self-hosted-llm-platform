.PHONY: test tf-check local-up local-down smoke up down running eval loadtest cost

test:          ; cd gateway && python -m pytest -q
tf-check:      ; terraform fmt -recursive -check infra/terraform && terraform -chdir=infra/terraform/modules/cluster-admins init -input=false >/dev/null && terraform -chdir=infra/terraform/modules/cluster-admins test
local-up:      ; ./local/kind-up.sh
local-down:    ; ./local/kind-down.sh
smoke:         ; ./local/smoke-test.sh
up:            ; ./scripts/up.sh
down:          ; ./scripts/down.sh
running:       ; ./scripts/whats-running.sh
eval:          ; @echo "Phase 5: python -m evals.run --suite all"
loadtest:      ; @echo "Phase 3: loadtest/run.sh"
cost:          ; @echo "Phase 7: scripts/cost-report.sh"
