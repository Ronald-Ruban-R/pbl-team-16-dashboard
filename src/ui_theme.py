"""
Unified Visual Theme, Status Badges & Consistent Spacing (`src/ui_theme.py`).

Provides:
- Clean, consistent spacing, card borders, metric styling, and tab bar hierarchy.
- Standardized status indicator helpers so icons are used only for navigation and
  meaningful status indicators with uniform style across every view.
"""

from __future__ import annotations

import streamlit as st


def format_health_badge(status: str) -> str:
    """Return a consistent status indicator string for team health."""
    s = (status or "").strip()
    if s == "On Track":
        return "🟢 On Track"
    if s == "Needs Attention":
        return "🟡 Needs Attention"
    if s == "At Risk":
        return "🔴 At Risk"
    return f"⚪ {s or 'Unknown'}"


def format_task_status(status: str) -> str:
    """Return a consistent, scannable indicator for task and milestone statuses."""
    s = (status or "").strip()
    mapping = {
        "Completed": "● Completed",
        "In Progress": "◐ In Progress",
        "Not Started": "○ Not Started",
        "Blocked": "▲ Blocked",
        "Delayed": "▲ Delayed",
    }
    return mapping.get(s, s or "○ Not Started")


def format_bool_indicator(value: bool, true_label: str = "Verified", false_label: str = "Missing") -> str:
    """Return a uniform `✓` / `✕` indicator string for verification tables."""
    return f"✓ {true_label}" if value else f"✕ {false_label}"


def apply_clean_theme() -> None:
    """Inject clean, consistent CSS styling for cards, metrics, tabs, and tables."""
    st.markdown(
        """
        <style>
        /* Main container spacing */
        .block-container {
            padding-top: 1.5rem !important;
            padding-bottom: 2.5rem !important;
            max-width: 1440px;
        }

        /* Consistent typography hierarchy */
        h1, h2, h3 {
            letter-spacing: -0.015em;
            font-weight: 600;
        }
        h2 {
            margin-bottom: 0.25rem !important;
        }
        h4 {
            margin-top: 0.5rem !important;
            margin-bottom: 0.6rem !important;
            font-weight: 600;
        }

        /* Polished metric cards */
        div[data-testid="stMetric"] {
            background-color: rgba(128, 128, 128, 0.05);
            border: 1px solid rgba(128, 128, 128, 0.16);
            border-radius: 10px;
            padding: 0.75rem 1rem;
        }
        div[data-testid="stMetricLabel"] {
            font-size: 0.82rem !important;
            font-weight: 500 !important;
            opacity: 0.85;
        }
        div[data-testid="stMetricValue"] {
            font-size: 1.45rem !important;
            font-weight: 600 !important;
        }

        /* Clean, uniform tab bar styling */
        button[data-baseweb="tab"] {
            font-weight: 500 !important;
            padding-left: 1rem !important;
            padding-right: 1rem !important;
        }

        /* Subtle bordered containers */
        div[data-testid="stVerticalBlockBorderWrapper"] {
            border-radius: 10px !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
