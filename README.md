# PBL Cohort-X Mentor Dashboard (`PBL-Cohort-X-Teams-13-18`)

A secure, modular, production-ready **Streamlit Mentor Dashboard** engineered for the two Organization Owners of **`PBL-Cohort-X-Teams-13-18`** to monitor six private multidisciplinary student repositories (`pbl-team-13` through `pbl-team-18`) from a single interface.

---

## 1. System Architecture & Module Boundaries

```text
pbl_mentor_dashboard/
├── app.py                                  # Main Streamlit entry point, login gate & navigation router
├── requirements.txt                        # Pinned, compatible Python dependencies
├── .gitignore                              # Excludes secrets.toml, .env, *.pem, virtualenvs & SQLite DBs
├── .streamlit/
│   └── secrets.toml.example                # Placeholder-only configuration template
├── src/
│   ├── __init__.py
│   ├── config.py                           # Org/repo registry, convention paths, review definitions & config loader
│   ├── security.py                         # PBKDF2-HMAC-SHA256 auth, server-side RBAC, XSS Markdown sanitizer & token redaction
│   ├── github_client.py                    # Resilient GitHub REST API & GitHub App client (JWT RS256, caching, pagination, rate-limits)
│   ├── validators.py                       # Strict JSON schema validation & dataclasses (VALID vs MISSING vs MALFORMED)
│   ├── analytics.py                        # Hybrid progress engine, repo-tree evidence verifier, milestone weights & alert generator
│   ├── storage.py                          # Fault-tolerant local SQLite store for mentor drafts, preferences & security audit logs
│   └── views/
│       ├── __init__.py
│       ├── overview.py                     # Page 1: Cohort Executive Overview, Comparison Matrix, Charts & Alerts
│       ├── team_workspace.py               # Page 2: Individual Team Workspace (Profile, Members, Updates, Categorized Files, Health)
│       ├── repo_explorer.py                # Page 3: Dynamic GitHub Repository Browser with Breadcrumbs & Safe File Previewer
│       ├── tasks_progress.py               # Page 4: Hybrid Progress, Milestone Weight Configurator & Filterable Task Tracker
│       ├── reviews.py                      # Page 5: Review 1–4 Management, Cross-Review Comparison & Mentor Evaluation Editor
│       ├── timeline.py                     # Page 6: Chronological Timeline, Planned vs. Actual Dates & Slippage Analysis
│       ├── research_competitions.py        # Page 7: Research, Literature, Datasets, Technical Docs & Competition Tracker
│       └── settings.py                     # Page 8: GitHub Connection Diagnostics, Rate-Limit Monitor, Password Hasher & Audit Log
├── templates/
│   └── starter_repo/                       # Optional starter JSON files for student repositories
│       ├── project/
│       │   ├── metadata.json
│       │   ├── progress.json
│       │   └── timeline.json
│       ├── team/
│       │   ├── members.json
│       │   └── responsibilities.json
│       ├── tasks/
│       │   └── tasks.json
│       └── reviews/
│           └── review-1.json
└── tests/
    └── test_dashboard_suite.py             # Automated unit & integration tests (unittest / pytest compatible)
```

---

## 2. Security Model & Required GitHub Permissions

### A. Keeping All Six Repositories Private
- All six student repositories (`pbl-team-13`..`pbl-team-18`) remain **private** inside `PBL-Cohort-X-Teams-13-18`.
- Each student team is granted GitHub repository permissions **only** to its own repository via GitHub Teams (`team-13` -> `pbl-team-13`, etc.).
- The two Organization Owners retain full access to all six repositories and authenticate into the dashboard with the `owner` role.

### B. GitHub Authentication Options (Least-Privilege)

#### Option 1: GitHub App Installation (Recommended for Production)
1. In GitHub, navigate to **Organization Settings (`PBL-Cohort-X-Teams-13-18`) → Developer settings → GitHub Apps → New GitHub App**.
2. Disable Webhook (unless push-triggered cache invalidation is desired).
3. Configure **Repository Permissions**:
   - **Contents**: `Read-only` (or `Read and write` *only* if you explicitly enable `enable_github_writeback = true` to commit `reviews/review-N.json` files).
   - **Metadata**: `Read-only` (mandatory default).
   - **Commits / Pull requests / Issues**: `Read-only` (optional).
4. Install the GitHub App on the `PBL-Cohort-X-Teams-13-18` organization and select the six repositories (`pbl-team-13` through `pbl-team-18`).
5. Copy the **App ID**, **Installation ID**, and generated **RSA Private Key (`.pem`)** into `.streamlit/secrets.toml` under `[github]`.
6. `GitHubAuthProvider` automatically signs a 9-minute RS256 JWT in memory and exchanges it for a short-lived installation token, refreshing it automatically before expiration.

#### Option 2: Fine-Grained Personal Access Token (For Initial Prototyping)
1. In GitHub, go to **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token**.
2. Set **Resource owner** to `PBL-Cohort-X-Teams-13-18`.
3. Under **Repository access**, select **Only select repositories** and choose `pbl-team-13` through `pbl-team-18`.
4. Under **Permissions → Repository permissions**, grant:
   - **Contents**: `Read-only`
   - **Metadata**: `Read-only`
5. Place the token in `.streamlit/secrets.toml` (`token = "..."`) or environment variable `PBL_GITHUB_TOKEN`.
6. **Limitations of a PAT**: Tied to a single owner's user account, shares that user's 5,000 req/hr rate limit, and requires manual rotation upon expiry. Migrate to a GitHub App for long-term shared deployment.

### C. Application-Level Authentication & Server-Side RBAC
- Private GitHub repositories do **not** automatically make a deployed Streamlit app private; therefore, `app.py` blocks all access behind `AccessControlManager` login verification.
- Passwords are verified using constant-time `hmac.compare_digest` with salted **PBKDF2-HMAC-SHA256** (260,000 iterations).
- Every view calls `access_manager.authorize_repo_access(user, repo_name)` on the server before rendering. If student accounts (`role = "student"`) are enabled in the future, they are strictly restricted to their single assigned repository (`allowed_repos = ["pbl-team-13"]`) and cannot access another team's data via URL parameters or session state tampering.
- All Markdown rendered from student repositories passes through `sanitize_markdown_for_display()` to strip `<script>`, `<iframe>`, `<object>`, inline `on*` event handlers, and `javascript:` URIs.

---

## 3. Data Source of Truth & Hybrid Progress Calculation

| Data Domain | Authoritative System | Storage Location |
| :--- | :--- | :--- |
| Project files, source code, docs, datasets, certificates | **GitHub Repository** | `PBL-Cohort-X-Teams-13-18/pbl-team-*` |
| Student-maintained metadata, tasks, milestones, timeline | **GitHub Repository** | `project/*.json`, `team/*.json`, `tasks/tasks.json`, `reviews/review-*.json` |
| Uncommitted mentor review drafts, custom milestone weight overrides, security audit trail | **Local SQLite Database** | `data/mentor_dashboard.db` (`src/storage.py`) |

### Progress Calculation Rules (`src/analytics.py`)
1. **Strict Separation from Commit Activity**: Commit counts, lines of code, and push timestamps are displayed as *Repository Activity* and **never** factor into completion percentages.
2. **Distinguishing Zero Progress vs. Missing vs. Malformed**:
   - Missing `progress.json` and `tasks.json` → Displays `"Not Reported"` (`None`).
   - Invalid JSON syntax or schema error → Displays `"Malformed Metadata"` with exact line/column or field errors.
   - Repository HTTP 404/403/503 → Displays `"Repository Unavailable"` while keeping the other 5 teams fully operational.
   - Valid `tasks.json` with 0 of $N$ tasks completed → Displays `0.0%`.
3. **Hybrid Evidence Verification**:
   - **Reported Task Completion %**: Weighted percentage of tasks in `tasks/tasks.json` with `status == "Completed"`.
   - **Evidence-Verified Task Completion %**: Counts a task as completed **only** if `status == "Completed"` **and** its `evidence_link` is verified to exist in the repository's Git tree (or is a valid external HTTPS URL).

---

## 4. Installation, Setup & Execution

### Step 1: Create Virtual Environment & Install Dependencies
```bash
cd pbl_mentor_dashboard
python3 -m venv .venv
source .venv/bin/activate   # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### Step 2: Configure `.streamlit/secrets.toml`
```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
```
Generate PBKDF2-HMAC-SHA256 password hashes for the two Organization Owners:
```bash
python3 -c "from src.security import hash_password_pbkdf2; print(hash_password_pbkdf2('YourStrongPasswordHere'))"
```
Paste the generated hashes and your GitHub App or Fine-Grained PAT into `.streamlit/secrets.toml`.

### Step 3: Run the Test Suite
```bash
python3 -m unittest discover -s tests -v
# or
pytest -v
```

### Step 4: Launch the Streamlit Application
```bash
streamlit run app.py
```

---

## 5. Extending the Dashboard (More Teams or Reviews)

1. **Adding or Removing Teams**:
   Update `repositories = [...]` under `[github]` in `.streamlit/secrets.toml` (or set the `PBL_TEAM_REPOS` comma-separated environment variable). No code changes are required.
2. **Adding Custom Review Stages**:
   Add a `ReviewDefinition` entry to `DEFAULT_REVIEWS` in `src/config.py`, or drop additional `reviews/review-5.json` files into a team's `reviews/` folder—`fetch_repository_snapshot()` automatically discovers all `reviews/*.json` files from the Git tree.
3. **Enabling Student-Facing Views**:
   Add a user block in `.streamlit/secrets.toml` with `role = "student"` and `allowed_repos = ["pbl-team-13"]`. The student will automatically see only `pbl-team-13` in read-only mode.
