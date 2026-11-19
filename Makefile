.PHONY: local-up local-deploy test eval loadtest up down cost

local-up:      ; ./local/kind-up.sh
local-deploy:  ; kubectl apply -k k8s/base   # TODO: local overlay
test:          ; cd gateway && pytest -v
eval:          ; python -m evals.run --suite all
loadtest:      ; echo "TODO: loadtest/run.sh"
up:            ; ./scripts/up.sh
down:          ; ./scripts/down.sh
cost:          ; ./scripts/cost-report.sh
