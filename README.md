# NEXUS — pharmaceutical inventory-to-procurement copilot

A working local vertical slice: validate a snapshot → forecast daily demand → compare replenishment options → review → approve or reject → export a draft purchase requisition. Synthetic demo only; no supplier messages or ERP writes.

## Run

Python 3.11+; no external packages required.

```sh
python app.py
```

Open http://127.0.0.1:8765. On this computer, `start.ps1` locates the bundled Python automatically. Load the synthetic example, review the plan, enter a reviewer name and reason, approve, then export. JSON imports use the same contract as `data/demo.json`. All quantities use each SKU's base unit; money is integer IDR.

```sh
python -m unittest discover -s tests -v
```

The local SQLite database is created in `runtime/`. The browser is a single-user demonstration; reviewer names are self-declared, not authenticated. Do not deploy this HTTP server publicly. See `docs/PRODUCT.md` for pilot architecture and release gates, `docs/AUDIT.md` for the repository audit, and `docs/CONTRACTS.md` for supported inputs and limitations.

No upstream source code was copied or merged. The current baseline is deliberately deterministic and explainable. LLM explanations and advanced forecasting are subsequent adapters, not dependencies of approval or calculation.
