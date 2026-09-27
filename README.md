# BudgetIQ AI — continuous budget cycle pilot

A sector-neutral budget workspace for companies, agencies, schools, churches, NGOs and other organizations. The app connects **objectives → programmes → activities → detailed costs → results**, then records expected and received funding, commitments, payments, review decisions and next-year references. The UI includes a fictional Community Learning Centre example that users may choose to load.

## Current features

- Upload action plans in DOCX, XLSX/XLSM, CSV or text based PDF and review suggested activity rows. The extraction is rules based and scanned PDFs require OCR.
- Split activities into cost lines for transport, venue, refreshments, materials, allowances, equipment, services or other needs. Track frequency, quantity, unit price, funding source, quarter and rate evidence.
- Set an allocation ceiling, see the funding gap, compare the full plan with the available envelope and model a percentage price change. The reduced funding display is an envelope, not an automatic recommendation of which activities to cut.
- Record projected versus received income and committed versus paid expenditure, grouped by activity and quarter.
- Record a self-reported preparer, reviewer or approver decision. Editing a marked Approved draft reopens it.
- Show programme totals, quarterly comparisons, expected versus delivered results and evidence counts.
- Start a next-year draft from paid amounts by activity with an explicit price change assumption. This is an arithmetic reference, not a trained AI forecast; partial-year payments are incomplete evidence.
- Export a detailed Excel workbook with objectives, programmes, cost lines, funding, execution, results, review log and summary; also download a PDF or CSV draft. Export and restore complete JSON project backups.

## Data and access limitations

Working projects are saved **only in this browser's local storage**, with optional user-controlled JSON backup. Clearing browser data or changing device loses the working draft unless it is exported and restored. This is a single-user pilot, with no shared workspace, authenticated identities, server-side approvals, database, backups or role enforcement. The API processes uploaded documents in memory and does not retain them. Do not use this public pilot for confidential institutional financial records. The application does not yet run a trained AI model. Rates, forecasts and approvals require independent institutional review.

A shared production release will require a durable database, account security, organization isolation, audit events and a backup/restore policy. The current Render workspace already uses its single free PostgreSQL allocation for another application; the browser-backed approach avoids changing that project or claiming durable multi-user storage.

## Local development

```bash
cd backend
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn main:app --reload
```

In another terminal from the repository root, run `python -m http.server 5500 --directory frontend` and open `http://localhost:5500`. `frontend/config.js` selects the local API there and the deployed API elsewhere.

## Render

Separate frontend static site and API web service are deployed from this repository. `render.yaml` documents their configuration. Service names are `budgetiq-ai` and `budgetiq-api`. The API CORS setting must match the frontend URL.
