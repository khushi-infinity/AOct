# Deletion assurance agent — developer tasks.
#
#   make run       regenerate output.csv for all 518 requests
#   make score     public-sample accuracy (status/exact/sequence/step/field)
#   make eval      legality checks on the generated output
#   make test      unit tests
#   make custom    hand-built custom cases
#   make verify    everything above, in order
#   make package   build code.zip for submission
#
# Data lives in dataset/. Nothing here writes outside build/ and the repo root.

PYTHON ?= python3
BUILD  := build
DATASET := dataset

.PHONY: help run score eval test custom verify package clean

help:
	@grep -E '^#   make' Makefile | sed 's/^#   //'

run:
	$(PYTHON) code/main.py

score: $(BUILD)
	$(PYTHON) code/main.py --requests $(DATASET)/sample_deletion_requests.csv --output $(BUILD)/sample_pred.csv
	$(PYTHON) code/evaluation/main.py $(BUILD)/sample_pred.csv --requests $(DATASET)/sample_deletion_requests.csv --gold $(DATASET)/sample_output.csv

eval:
	$(PYTHON) code/evaluation/main.py output.csv --requests $(DATASET)/deletion_requests.csv

test:
	$(PYTHON) -m unittest discover -s code/tests -v

custom:
	$(PYTHON) code/evaluation/custom_cases.py

verify: run eval test custom
	@echo "verify: pipeline, legality, unit tests and custom cases all completed"

package: run
	rm -f code.zip
	zip -rq code.zip README.md ENGAGEMENT-BRIEF.md DECISIONS.md Makefile code docs -x '*/__pycache__/*' '*.DS_Store'
	@echo "package: code.zip built from the current tree"

$(BUILD):
	mkdir -p $(BUILD)

clean:
	rm -rf $(BUILD) code.zip
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
