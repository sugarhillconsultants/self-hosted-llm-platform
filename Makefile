.PHONY: test tf-check local-up local-down smoke up down running platform-up platform-down pin-model gpu-smoke deploy-gateway phase3 eval loadtest cost

test:          ; cd gateway && python -m pytest -q
tf-check:      ; terraform fmt -recursive -check infra/terraform && for m in cluster-admins github-oidc; do terraform -chdir=infra/terraform/modules/$$m init -input=false >/dev/null && terraform -chdir=infra/terraform/modules/$$m test || exit 1; done
local-up:      ; ./local/kind-up.sh
local-down:    ; ./local/kind-down.sh
smoke:         ; ./local/smoke-test.sh
up:            ; ./scripts/up.sh
down:          ; ./scripts/down.sh
running:       ; ./scripts/whats-running.sh
platform-up:   ; ./scripts/k8s-platform.sh up
platform-down: ; ./scripts/k8s-platform.sh down
pin-model:     ; ./scripts/pin-model.sh
gpu-smoke:     ; ./scripts/vllm-smoke.sh
deploy-gateway: ; ./scripts/deploy-gateway.sh
phase3:        ; ./scripts/phase3-run.sh
eval:          ; @echo "Phase 5: python -m evals.run --suite all"
loadtest:      ; ./scripts/phase3-run.sh
cost:          ; @echo "Phase 7: scripts/cost-report.sh"
