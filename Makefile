.PHONY: help setup new resume assemble upload costs test clean

help:
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN{FS=":.*?## "};{printf "  %-12s %s\n", $$1, $$2}'

setup:   ## install deps and check ffmpeg
	pip install -r requirements.txt
	@command -v ffmpeg >/dev/null || (echo "!! ffmpeg not on PATH"; exit 1)
	@test -f .env || (cp .env.example .env && echo ">> created .env - fill it in")

new:     ## generate a whole new episode (stops before upload)
	python -m pipeline.cli new

preview: ## build episode 001 with free stand-ins - no API keys needed
	python -m pipeline.cli seed ep001
	python -m pipeline.cli run --dry-run

resume:  ## resume the latest episode from wherever it stopped
	python -m pipeline.cli run

assemble: ## re-render the latest episode only
	python -m pipeline.cli run --stage assemble --force

upload:  ## upload latest as PRIVATE (add PUBLISH=1 to go public)
	python -m pipeline.cli upload $(if $(PUBLISH),--publish,)

costs:   ## month-to-date spend
	python -m pipeline.cli costs

test:    ## end-to-end assembly smoke test, no API keys needed
	python scripts/smoke_test.py

clean:   ## drop intermediate clips (keeps scripts, audio, images, renders)
	rm -rf episodes/*/clips
