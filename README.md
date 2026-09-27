# BudgetIQ AI — pilot MVP

A draft budget builder for institutional action plans. The pilot parses Word, Excel, CSV and text based PDF files; suggests activity rows using transparent rules; allows manual quantity and price edits; and exports Excel, PDF and CSV. Previous budgets are imported as **references** with zero prices, never silently reused as current rates.

The name describes the intended product direction. **This pilot does not run a trained AI forecast**, OCR, automatic price discovery, authentication, persistence, financial approvals, revenue tracking or multi-tenant SaaS. Do not upload sensitive financial records to a public demo. All documents are processed in memory and not saved by the API. Browser edits are lost on refresh.

## Local run

```bash
cd backend
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn main:app --reload
```

Open `frontend/index.html` via a local server on port 5500, for example `python -m http.server 5500 --directory frontend` from the project root. The frontend calls `http://localhost:8000` by default.

## Render deployment

`render.yaml` provisions separate static frontend and Python API services on free plans. After creating the repository, edit `frontend/config.js` to set `window.BUDGETIQ_API` to the actual API service URL, then push. If Render assigns a different frontend URL, update the API `FRONTEND_ORIGIN` environment variable to its exact origin. Create a Blueprint from this repository and verify `/health`, import and export in the live UI.

## Design reference

The user's 2027 Nutrition Budget workbook informed the program, activity, allocation and prior-year structure. The workbook itself, macros, personal data and historical price list are not included in this repository. Budget rows use a new, simplified schema and require reviewer confirmation.

## Next milestones

Add authenticated organization workspaces, Postgres persistence, document review, explicit cost categories and funding sources, then revenue/expenditure tracking and accuracy measurement. Evaluate any model against actual historic budgets before labeling estimates as predictions.
