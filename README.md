# PBL Cohort-X Universal Mentor & Team Dashboard

Production Streamlit dashboard for monitoring, evaluating, and updating PBL repositories under `PBL-Cohort-X-Teams-13-18`.

## Key Features
- **Universal Dynamic Configuration**: Runs as a single-team dashboard or a multi-team cohort mentor dashboard based purely on `.streamlit/secrets.toml`.
- **In-App JSON Editors (Owner Only)**: Users with `role = "owner"` (Team Leads / Organization Owners) can add and edit `project/metadata.json`, `project/progress.json`, `project/timeline.json`, `team/members.json`, `team/responsibilities.json`, `tasks/tasks.json`, and `reviews/review-1..4.json` directly from the UI. Users with `role = "student"` have read-only access.
- **Automatic Placeholder Sanitization**: Cleanly replaces unedited starter placeholders (`<TEAM_DISPLAY_NAME>`, `<TECHNICAL_OR_SOCIAL_IMPACT_DOMAIN>`, etc.) with formatted team names and defaults.
- **Dual Progress Verification**: Compares self-reported progress against repository-verified milestones, tasks, and review deliverables.
