# BudgetIQ AI — full stack budget workspace

BudgetIQ connects objectives, programmes, activities, costs, funding, execution and results. The example is a fictional Community Learning Centre. The FastAPI backend now includes authenticated, account-scoped project storage in PostgreSQL. The Render frontend and backend remain separate services.

## Database setup

Create a **dedicated PostgreSQL database** for BudgetIQ on a managed provider such as Neon, Supabase or paid Render PostgreSQL. Do not reuse a database that belongs to another application. In the Render `budgetiq-api` service, set:

- `DATABASE_URL`: the provider's PostgreSQL connection string, including TLS parameters required by that provider. Set this in the Render environment settings only, never in GitHub or chat.
- `AUTH_SECRET`: a new random secret of at least 32 bytes. For example, generate one locally with `python -c "import secrets; print(secrets.token_urlsafe(48))"` and place it directly in Render environment settings.
- `FRONTEND_ORIGIN`: `https://budgetiq-ai.onrender.com` (already configured).
- `BUDGETIQ_ADMIN_EMAIL`: email address of an **existing** BudgetIQ account that you personally control. Set this on the API service before approving new accounts. The registration endpoint reserves this address after it is configured, so register and confirm control of the account first. The address is compared with the signed-in account on every admin request; it is not a secret.

The API creates its account, project, membership, treasury request and treasury event tables on startup when both settings are present. It refuses storage requests when either setting is absent. Configure database backups with the chosen provider before entering important records.

## What is saved

Accounts and projects are saved on PostgreSQL. Passwords use salted PBKDF2 hashes; sign-in tokens expire after 24 hours. New registration records a **pending** account and returns no session token. The administrator can approve or suspend accounts; suspended sessions stop working on the next API request. Existing accounts stay active during the schema migration so current project owners do not lose their data. Review them in the admin panel and suspend any account that should not retain access. Projects have a server-generated ID, tenant membership checks, a version number for conflicting edits, and a 1 MB size limit. The browser keeps only the short-lived sign-in token in session storage and current in-memory edits until they are saved; it does not use localStorage for budget records. A complete JSON project backup remains available.

## Approval and organization roles

The platform administrator signs in with the existing account configured as `BUDGETIQ_ADMIN_EMAIL`. The **Organization access** panel lists account requests, can approve or suspend an account, and creates organization workspaces. A new user cannot sign in while pending. An organization administrator assigns approved accounts to one of four roles: **budget preparer**, **reviewer**, **approver**, or **procurement evaluator**. The organization administrator has preparer access and can assign staff. Staff see only their relevant workspace tabs; the API independently checks membership and role for projects, procurement decisions and Treasury actions. Reviewer and procurement accounts receive a restricted project document; their relevant module loads through its role-protected endpoint.

To onboard an organization: (1) create it from the platform admin panel; (2) have staff request accounts; (3) approve their requests; (4) assign their roles in Organization access; (5) create a budget under that organization. A preparer can create and edit budgets; a reviewer reviews Treasury requests; an approver decides Treasury and procurement recommendations; a procurement evaluator records offers and recommendations. An account with no organization membership has no organization budgets. The old projects remain private to their original owner and previously invited project collaborators; new budgets require an organization. Their owners can export a JSON backup and restore it as a new organization budget if a move is needed. Roles assigned in organization access apply to every budget in that organization; use separate organizations for data that must stay apart.

This is still an early account system: it has no email verification, password reset or production-grade abuse controls. Confirm a person's email and organization affiliation out of band before approving. The original budget review log remains self reported. The separate Treasury pilot enforces reviewer and approver roles for its requests. Do not treat the pilot as an approved financial system before independent security and finance workflow review.

## Treasury and commitment control pilot

The Treasury tab gives each project a server-side expenditure request ledger. The owner can invite existing BudgetIQ accounts as reviewer and approver. The owner records an internal funding release by source and quarter, up to the project's ceiling. A request follows draft → submitted → reviewed → approved → committed → invoiced → partially or fully paid. The API checks the project ceiling, linked activity budget and source-quarter release before submission, review, approval and commitment. Submitted amounts reserve capacity; rejected requests release it. An owner cannot review their own request, and the reviewer cannot also approve that same request. A project edit cannot reduce the ceiling or activity cost below already reserved requests or releases. The event history records the authenticated actor, action and timestamp.

The invoice step records a user-entered invoice amount and delivery/service completion reference, ensuring the amount cannot exceed the commitment. Payment references can be recorded in parts, but their sum cannot exceed the matched invoice. These are **unverified records**, not invoice verification or money transfers. BudgetIQ does not issue purchase orders, government allotments or cash warrants, connect to GIFMIS or reconcile a bank account. In particular, public guidance reserves official government purchase orders for GIFMIS. The older Execution tab remains a separate planning record and is not automatically reconciled with Treasury. In a production phase, implement verified supplier records, chart of accounts and fund codes, real warrant/cash controls, attachment checks, reversals, period close and authorized audited integrations. This pilot is inspired by public financial management controls, not affiliated with the Government of Ghana's GIFMIS.

To try it, create an organization budget with a ceiling and costed activity. Record an internal funding release for a source and quarter. Approve two collaborators' requested accounts; assign one reviewer and another approver in Organization access. Create a request against that source and quarter, submit it, then have each person sign in and perform the relevant step. After approval, record a commitment, matched invoice with delivery reference, and one or more payment references.

## Procurement comparison pilot

The **Procurement** tab connects a costed activity to a supplier comparison. The project owner creates an internal case with an estimate, proposed sourcing method, rationale, funding source, quarter and optional reference to an external system. A separately assigned procurement account enters supplier offers, records responsiveness and a technical score, declares no conflict of interest and writes a reasoned recommendation. One offer requires a specific explanation. A separate approver may return or approve the recommendation. Only then can the owner create a linked Treasury **draft** using the selected supplier and quoted price. Treasury still requires its own funding release, review, approval and commitment controls.

This feature does not publish tenders, invite suppliers, validate supplier eligibility, determine the lawful procurement method or threshold, issue a purchase order, award a contract or communicate with GHANEPS or GIFMIS. Public entities must continue to use their applicable official systems and authorized processes. Quotes and external references are entered by users and have not been independently verified. A production procurement system would need controlled document attachments, solicitation and opening records, evaluator panels, eligibility verification, approvals by the legally competent authority, supplier and contract management, and integration approved by the relevant agencies.

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
