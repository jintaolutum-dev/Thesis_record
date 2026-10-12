FILE := main
OUT  := build
TECTONIC := $(HOME)/.local/bin/tectonic

.PHONY: pdf
pdf:
	@if command -v latexmk >/dev/null 2>&1; then \
		latexmk -interaction=nonstopmode -outdir=$(OUT) -pdf -halt-on-error $(FILE); \
	elif [ -x "$(TECTONIC)" ]; then \
		PATH="$(HOME)/.local/bin:$(PATH)" $(TECTONIC) -X compile $(FILE).tex --outdir $(OUT) --keep-logs; \
	else \
		echo "error: install latexmk or Tectonic to build the thesis" >&2; \
		exit 1; \
	fi

.PHONY: watch
watch:
	latexmk -interaction=nonstopmode -outdir=$(OUT) -pdf -pvc -halt-on-error $(FILE)

.PHONY: clean
clean:
	rm -rf $(filter-out $(OUT)/$(FILE).pdf, $(wildcard $(OUT)/*))

.PHONY: purge
purge:
	rm -rf $(OUT)
