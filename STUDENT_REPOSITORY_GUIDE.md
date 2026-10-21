# PBL Cohort-X: Student Team Repository Guide

Welcome to **PBL Cohort-X**! Your private team repository under **`PBL-Cohort-X-Teams-13-18`** is your project's single source of truth. Your mentor monitors your progress, deliverables, research, and review submissions directly from this repository using the **PBL Mentor Dashboard**.

This guide explains how to organize your repository, fill in your structured JSON files, and ensure your completed work is verified by the mentor dashboard.

---

## 1. Quick Repository Structure Overview

Your repository is organized into four structured management folders (`project/`, `team/`, `tasks/`, `reviews/`) and dedicated artifact folders:

```text
pbl-team-XX/
├── README.md                      # Your project overview and team introduction
├── project/
│   ├── metadata.json              # Problem statement, domain, objectives, outcomes
│   ├── progress.json              # Weekly sprint progress, blockers, milestone weights
│   └── timeline.json              # Chronological milestone schedule (planned vs. actual)
├── team/
│   ├── members.json               # Team roster, roles, disciplines, GitHub usernames
│   └── responsibilities.json      # Individual ownership and responsibility matrix
├── tasks/
│   └── tasks.json                 # Itemized task tracker with assignees and evidence links
├── reviews/
│   ├── review-1.json              # Review 1 submission, deliverables, and action items
│   ├── review-2.json              # Review 2 submission, deliverables, and action items
│   ├── review-3.json              # Review 3 submission, deliverables, and action items
│   └── review-4.json              # Review 4 submission, deliverables, and action items
├── research/                      # Literature survey, papers, citations, comparative studies
├── documentation/                 # System architecture, specs, circuit diagrams, user guides
├── datasets/                      # Datasets, benchmarks, experiment results, test logs
├── competitions/                  # Hackathon entries, certificates, external evaluations
├── meeting-notes/                 # Weekly mentor meeting minutes and sprint retrospectives
└── deliverables/                  # Slide decks, final reports, demo videos, prototypes
```

> **Note on Custom Folders:** You are free to add custom folders (such as `cad/`, `firmware/`, `src/`, or `mobile-app/`). The mentor dashboard dynamically scans your entire repository tree and displays custom folders automatically.

---

## 2. Step-by-Step: How to Fill Each JSON File

### File 1: `project/metadata.json` (Fill Once at Kickoff, Update as Scope Evolves)

This file defines your project's identity, problem statement, and goals.

```json
{
  "team_id": "pbl-team-13",
  "team_name": "Team 13 — SolarPulse",
  "project_title": "Automated Anomaly Detection in Rural Microgrids",
  "domain": "Clean Energy & IoT",
  "problem_statement": "Rural solar microgrids suffer from unmonitored inverter failures, causing prolonged power outages for communities. This project develops an edge-IoT sensor suite and ML model to detect fault precursors before outages occur.",
  "objectives": [
    "Design an edge current/voltage sensing unit under $30.",
    "Develop a real-time anomaly classification model running on ESP32.",
    "Build a local dashboard displaying real-time inverter health metrics."
  ],
  "expected_outcomes": [
    "Functional prototype tested across 3 microgrid setups.",
    "Anomaly detection recall rate of at least 92%.",
    "Comprehensive open-source documentation and deployment guide."
  ],
  "start_date": "2026-08-01",
  "target_completion_date": "2026-12-15",
  "lead_mentor": "Dr. R. Ruban",
  "co_mentor": "Prof. S. Sharma",
  "tags": ["IoT", "Renewable Energy", "Edge AI", "Embedded Systems"]
}
```

---

### File 2: `team/members.json` & `team/responsibilities.json`

Introduce your team members and specify who owns which deliverables.

#### `team/members.json`:
```json
{
  "members": [
    {
      "member_id": "M1",
      "name": "Aarav Sharma",
      "github_username": "aarav-s",
      "role": "Team Lead & Embedded Firmware",
      "discipline": "Electrical & Electronics Engineering",
      "email": "aarav.s@college.edu"
    },
    {
      "member_id": "M2",
      "name": "Priya Nair",
      "github_username": "priya-nair",
      "role": "ML Engineer & Data Analysis",
      "discipline": "Computer Science & Engineering",
      "email": "priya.n@college.edu"
    }
  ]
}
```

#### `team/responsibilities.json`:
```json
{
  "responsibilities": [
    {
      "member_id": "M1",
      "member_name": "Aarav Sharma",
      "primary_areas": [
        "Sensor hardware interfacing",
        "Firmware development on ESP32",
        "Power supply regulation"
      ],
      "deliverables_owned": [
        "documentation/hardware_schematic.pdf",
        "firmware/src/main.cpp"
      ],
      "notes": "Primary contact for mentor hardware check-ins."
    },
    {
      "member_id": "M2",
      "member_name": "Priya Nair",
      "primary_areas": [
        "Dataset cleaning and normalization",
        "Model training and pruning for edge inference",
        "Literature review on vibration and thermal anomalies"
      ],
      "deliverables_owned": [
        "research/literature_survey.pdf",
        "datasets/benchmark_results.csv"
      ],
      "notes": "Lead for IEEE competition paper submission."
    }
  ]
}
```

---

### File 3: `tasks/tasks.json` (Update Weekly During Sprints)

The task tracker is the primary evidence source for your project progress.

```json
{
  "tasks": [
    {
      "task_id": "T-101",
      "title": "Conduct literature survey on inverter fault classification",
      "description": "Review IEEE papers from 2022-2026 on fault precursors and compile a comparative matrix.",
      "assigned_to": "Priya Nair",
      "priority": "High",
      "status": "Completed",
      "start_date": "2026-08-05",
      "due_date": "2026-08-20",
      "completed_date": "2026-08-18",
      "related_milestone": "M1",
      "related_review": "review-1",
      "evidence_link": "research/literature_survey.pdf",
      "last_updated": "2026-08-18",
      "weight": 1.0
    },
    {
      "task_id": "T-102",
      "title": "Fabricate prototype voltage divider circuit",
      "description": "Solder test circuit on breadboard and verify calibration with multimeter.",
      "assigned_to": "Aarav Sharma",
      "priority": "Critical",
      "status": "In Progress",
      "start_date": "2026-08-22",
      "due_date": "2026-09-05",
      "completed_date": null,
      "related_milestone": "M2",
      "related_review": "review-2",
      "evidence_link": "documentation/circuit_diagram.png",
      "last_updated": "2026-08-30",
      "weight": 1.0
    }
  ]
}
```

> **CRITICAL — Evidence Verification Rule:**
> When you mark a task as `"status": "Completed"`, you **must** supply an `"evidence_link"`.
> - If you link `"research/literature_survey.pdf"`, that file **must actually exist** in your repository.
> - The mentor dashboard checks your Git tree in real time. If the file exists, it shows **"✅ Verified"**. If the file is missing or misspelled, your progress shows as **"❌ Unverified"**.

---

### File 4: `project/progress.json` (Update Before Every Mentor Meeting)

This file summarizes what your team accomplished, what blockers you face, and the status of your major milestones.

```json
{
  "last_updated": "2026-09-01",
  "current_phase": "System Architecture & Initial Prototyping",
  "overall_reported_pct": 35.0,
  "summary": "Completed literature review and sensor calibration. Currently soldering the ESP32 breadboard shield and preparing synthetic fault data.",
  "accomplishments_since_last_update": [
    "Calibrated voltage sensor with under 1.5% error margin.",
    "Compiled literature review across 18 peer-reviewed papers.",
    "Configured edge ML pipeline on Edge Impulse."
  ],
  "blockers": [
    "Awaiting delivery of high-current CT clamp sensor (expected Sept 4)."
  ],
  "next_steps": [
    "Integrate current sensor upon arrival.",
    "Run initial 24-hour continuous logging test."
  ],
  "milestones": [
    {
      "milestone_id": "M1",
      "title": "Problem Scoping & Literature Survey",
      "status": "Completed",
      "weight": 20.0,
      "completion_pct": 100.0,
      "due_date": "2026-08-25",
      "completed_date": "2026-08-22",
      "evidence_path": "research/"
    },
    {
      "milestone_id": "M2",
      "title": "System Architecture & Hardware Prototype",
      "status": "In Progress",
      "weight": 25.0,
      "completion_pct": 50.0,
      "due_date": "2026-09-20",
      "completed_date": null,
      "evidence_path": "documentation/"
    },
    {
      "milestone_id": "M3",
      "title": "Core Implementation & ML Testing",
      "status": "Not Started",
      "weight": 30.0,
      "completion_pct": 0.0,
      "due_date": "2026-10-25",
      "completed_date": null,
      "evidence_path": "datasets/"
    },
    {
      "milestone_id": "M4",
      "title": "Field Validation, Documentation & Final Demo",
      "status": "Not Started",
      "weight": 25.0,
      "completion_pct": 0.0,
      "due_date": "2026-11-30",
      "completed_date": null,
      "evidence_path": "deliverables/"
    }
  ]
}
```

> **Milestone Weights Rule:**
> The `weight` values across all milestones in `milestones` **must sum to 100.0%** (e.g. `20.0 + 25.0 + 30.0 + 25.0 = 100.0`).

---

### File 5: `project/timeline.json` (Planned vs. Actual Dates)

Keep a record of your planned dates versus your actual completion dates to track project schedule variance.

```json
{
  "events": [
    {
      "event_id": "EV-1",
      "title": "Literature Review Submission",
      "category": "Milestone",
      "planned_date": "2026-08-20",
      "actual_date": "2026-08-18",
      "status": "Completed",
      "delay_reason": null,
      "evidence_path": "research/literature_survey.pdf"
    },
    {
      "event_id": "EV-2",
      "title": "Hardware Prototype Bench Test",
      "category": "Deliverable",
      "planned_date": "2026-09-10",
      "actual_date": null,
      "status": "In Progress",
      "delay_reason": "Sensor shipment delayed by 3 days.",
      "evidence_path": "documentation/bench_test_results.png"
    }
  ]
}
```

---

### File 6: `reviews/review-1.json` through `review-4.json` (Update Before Each Review)

Before each formal review evaluation, update the corresponding review JSON file:

```json
{
  "review_id": "review-1",
  "review_number": 1,
  "review_name": "Review 1: Problem Definition & Literature Survey",
  "scheduled_date": "2026-08-25",
  "submission_deadline": "2026-08-23",
  "submitted_at": "2026-08-22",
  "submission_status": "Submitted",
  "deliverables": [
    {
      "title": "Problem Statement & Stakeholder Analysis",
      "required": true,
      "submitted": true,
      "artifact_path": "project/metadata.json",
      "notes": "Defined with inputs from local microgrid technician."
    },
    {
      "title": "Literature Review Summary",
      "required": true,
      "submitted": true,
      "artifact_path": "research/literature_survey.pdf",
      "notes": "18 papers surveyed and summarized."
    },
    {
      "title": "Presentation Slides",
      "required": true,
      "submitted": true,
      "artifact_path": "deliverables/review_1_presentation.pdf",
      "notes": "Slide deck covering problem statement and architecture."
    }
  ],
  "evidence_links": {
    "presentation": "deliverables/review_1_presentation.pdf",
    "report": "research/literature_survey.pdf",
    "prototype": "",
    "research": "research/"
  },
  "mentor_feedback": null,
  "criteria_scores": [],
  "strengths": [],
  "concerns": [],
  "improvement_areas": [],
  "action_items": []
}
```

> **Mentor Feedback Section:**
> Leave `"mentor_feedback"`, `"criteria_scores"`, and `"action_items"` empty initially—your mentor will fill these in during or after your review evaluation.

---

## 3. Allowed Field Values (Cheat Sheet)

| Field | Allowed Exact Values (Case-Sensitive) |
| :--- | :--- |
| **Task Status** | `"Not Started"`, `"In Progress"`, `"Blocked"`, `"Completed"` |
| **Task Priority** | `"Critical"`, `"High"`, `"Medium"`, `"Low"` |
| **Review Submission Status** | `"Not Submitted"`, `"Partial"`, `"Submitted"`, `"Reviewed"`, `"Resubmission Required"` |
| **Timeline Category** | `"Milestone"`, `"Review"`, `"Competition"`, `"Deliverable"`, `"Task Deadline"` |
| **Dates** | ISO format: `"YYYY-MM-DD"` (e.g., `"2026-08-25"`) |

---

## 4. Top 5 Rules to Avoid Dashboard Warnings

1. **No Trailing Commas in JSON:** Unlike JavaScript or Python dictionaries, standard JSON does **not** allow trailing commas before closing braces `}` or `]`.
   - ❌ Bad: `[ "item1", "item2", ]`
   - ✅ Good: `[ "item1", "item2" ]`
2. **Commit Your Artifacts Alongside Your Tasks:** Never mark a task as `"Completed"` without committing the proof file (PDF, code, image, dataset) to the exact path specified in `"evidence_link"`.
3. **Keep Milestone Weights at 100%:** Make sure the `weight` values in `project/progress.json` sum to exactly `100.0`.
4. **Commits ≠ Completed Tasks:** Merely pushing code or commits to GitHub does **not** increase your task completion percentage in the mentor dashboard. You must update your `tasks/tasks.json` file.
5. **Validate Your JSON Before Committing:** Open your `.json` file in VS Code or run it through [JSONLint](https://jsonlint.com/) to confirm there are no syntax errors before running `git push`.
