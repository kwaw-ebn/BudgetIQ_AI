# BudgetIQ AI — full stack budget workspace

BudgetIQ connects objectives, programmes, activities, costs, funding, execution and results. The example is a fictional Community Learning Centre. The FastAPI backend now includes authenticated, account-scoped project storage in PostgreSQL. The Render frontend and backend remain separate services.

## Database setup

Create a **dedicated PostgreSQL database** for BudgetIQ on a managed provider such as Neon, Supabase or paid Render PostgreSQL. Do not reuse a database that belongs to another application. In the Render `budgetiq-api` service, set:

- `DATABASE_URL`: the provider's PostgreSQL connection string, including TLS parameters required by that provider. Set this in the Render environment settings only, never in GitHub or chat.
- `AUTH_SECRET`: a new random secret of at least 32 bytes. For example, generate one locally with `python -c "import secrets; print(secrets.token_urlsafe(48))"` and place it directly in Render environment settings.
- `FRONTEND_ORIGIN`: `https://budgetiq-ai.onrender.com` (already configured).

The API creates its account, project, membership, treasury request and treasury event tables on startup when both settings are present. It refuses storage requests when either setting is absent. Configure database backups with the chosen provider before entering important records.

## What is saved

Accounts and projects are saved on PostgreSQL. Passwords use salted PBKDF2 hashes; sign-in tokens expire after 24 hours. Projects have a server-generated ID, owner isolation, a version number for conflicting edits, and a 1 MB size limit. The browser keeps only the short-lived sign-in token in session storage and current in-memory edits until they are saved; it does not use localStorage for budget records. A complete JSON project backup remains available.

This is still an early account system: it has no email verification, password reset or production-grade abuse controls. The original budget review log remains self reported. The separate Treasury pilot enforces reviewer and approver roles for its requests. Do not treat the pilot as an approved financial system before independent security and finance workflow review.

## Treasury and commitment control pilot

The Treasury tab gives each project a server-side expenditure request ledger. The owner can invite existing BudgetIQ accounts as reviewer and approver. A request follows draft → submitted → reviewed → approved → committed → invoiced → payment recorded. The API checks the project ceiling and linked activity budget before submission, review, approval and commitment. Submitted amounts reserve capacity; rejected requests release it. An owner cannot review their own request, and the reviewer cannot also approve that same request. A project edit cannot reduce the ceiling or activity cost below already reserved requests. The event history records the authenticated actor, action and timestamp.

The invoice and payment steps record **references only**; they do not issue purchase orders, verify invoices, move money, connect to GIFMIS or reconcile a bank account. The older Execution tab remains a separate planning record and is not automatically reconciled with Treasury. In a production phase, implement verified supplier records, chart of accounts and fund codes, warrants/cash limits, line-item encumbrances, goods receipt, invoice matching, partial payments, reversals, period close, attachment controls and audited integrations. This pilot is inspired by public financial management controls, not affiliated with the Government of Ghana's GIFMIS.

To try it, create a project with a ceiling and costed activity. Ask two collaborators to register their own accounts; invite one as reviewer and another as approver from the Treasury tab. Create and submit a request, then have each person sign in and perform the relevant step. Record a commitment, invoice reference and payment reference after approval.

## Budget features

Upload DOCX, XLSX/XLSM, CSV or text based PDF action plans; review suggested activities; create detailed cost lines; set a funding ceiling; track projected and received revenue plus commitments and payments; compare quarters and scenario assumptions; create a next-year draft from actual payments; export PDF, CSV and a multi-sheet Excel workbook. Extraction is rules based and next-year estimates are arithmetic, not a trained AI model.

## Financial evidence and forecasting

The **Evidence** section stores immutable plan snapshots and annual figures in the same account-scoped PostgreSQL project. Record original budgets, revised estimates, provisional results and audited actuals as distinct stages. Revision comparisons use revised minus original; execution comparisons require audited actuals. A revision of at least 10% requires an explanation. These are user-entered figures and do not independently verify an audit.

Import a tidy CSV or Excel file with `year,metric,stage,amount,currency,source` and optional `note`. Metric is `Revenue` or `Expenditure`; stage is one of the four labels shown in the app. The preview flags duplicates, missing audited years, invalid amounts and inconsistent currency. Confirm the accepted rows before they are saved. For example: `2025,Revenue,Audited actual,125000,GHS,Audited statement,`.

With four or more consecutive years of audited actuals for one metric, BudgetIQ compares last actual, linear trend, simple exponential smoothing and Holt trend using expanding one-year-ahead tests. It reports MAE, RMSE, MAPE when denominators are nonzero, and average bias. Four or five years are flagged as preliminary; gaps stop forecasting. The one-year projection is a nominal reference, not an automatically approved allocation. Plan version copies and financial records count toward the project's 1 MB size limit.

## Local development

For a temporary local development database, set `DATABASE_URL=sqlite:////tmp/budgetiq-local.db` and `AUTH_SECRET` to a development-only secret. Install `backend/requirements.txt`, then run `uvicorn main:app --reload` from `backend`. Serve `frontend` at port 5500 with `python -m http.server 5500 --directory frontend` from the repository root.

## Deployment sequence

1. Provision a dedicated durable PostgreSQL database and backups.
2. Set `DATABASE_URL` and `AUTH_SECRET` in the Render API service.
3. Deploy the API branch and check `/health`, registration, project create/read/update and account isolation.
4. Deploy the frontend branch and confirm saving, reloading, export and sign out.
5. Verify treasury role separation, reserved balances, and project isolation with test accounts before using the pilot for any real data.
