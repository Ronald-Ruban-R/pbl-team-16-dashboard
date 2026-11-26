"""
Unified Visual Theme, Design System Components & Responsive CSS (`src/ui_theme.py`).

Provides:
- Cohesive typography, color tokens, elevation shadows, and responsive breakpoints
  across desktop, tablet, and mobile viewports.
- Semantic status indicators (`format_health_badge`, `format_task_status`, `format_bool_indicator`)
  and HTML pill badges (`render_health_pill`, `render_role_pill`, `render_page_header`).
- Consistent styling for navigation, tabs, metric cards, forms, and tables.
"""

from __future__ import annotations

import html
from typing import Optional

import streamlit as st


def format_health_badge(status: str) -> str:
    """Return a consistent status indicator string for team health in tables and cards."""
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


def render_health_pill(status: str) -> str:
    """Return an HTML semantic status pill badge for card and page headers."""
    s = (status or "Unknown").strip()
    palette = {
        "On Track": ("#ECFDF5", "#047857", "#A7F3D0", "●"),
        "Needs Attention": ("#FFFBEB", "#B45309", "#FDE68A", "◐"),
        "At Risk": ("#FEF2F2", "#B91C1C", "#FECACA", "▲"),
    }
    bg, fg, border, dot = palette.get(s, ("#F1F5F9", "#475569", "#CBD5E1", "○"))
    safe_s = html.escape(s)
    return (
        f"<span style='display:inline-flex;align-items:center;gap:0.38rem;"
        f"background:{bg};color:{fg};border:1px solid {border};"
        f"padding:0.24rem 0.72rem;border-radius:999px;font-size:0.78rem;"
        f"font-weight:600;letter-spacing:0.01em;white-space:nowrap;'>"
        f"<span>{dot}</span><span>{safe_s}</span></span>"
    )


def render_role_pill(role_value: str) -> str:
    """Return an HTML pill badge indicating user role and access level."""
    r = (role_value or "student").strip().lower()
    if r == "owner":
        bg, fg, border, label = "#EFF6FF", "#1D4ED8", "#BFDBFE", "Owner · Write Access"
    elif r == "mentor":
        bg, fg, border, label = "#F5F3FF", "#6D28D9", "#DDD6FE", "Mentor · Review Access"
    else:
        bg, fg, border, label = "#F8FAFC", "#475569", "#E2E8F0", "Student · Read-Only"
    return (
        f"<span style='display:inline-block;background:{bg};color:{fg};"
        f"border:1px solid {border};padding:0.18rem 0.6rem;border-radius:999px;"
        f"font-size:0.74rem;font-weight:600;letter-spacing:0.01em;'>{label}</span>"
    )


def render_page_header(
    title: str,
    subtitle: str,
    right_badge_html: Optional[str] = None,
) -> None:
    """Render a consistent, aligned page header with subtitle and optional right-hand status pill."""
    if right_badge_html:
        c1, c2 = st.columns([3.2, 1])
        with c1:
            st.markdown(f"## {title}")
            st.caption(subtitle)
        with c2:
            st.markdown(
                f"<div style='display:flex;justify-content:flex-end;align-items:center;padding-top:0.55rem;'>"
                f"{right_badge_html}</div>",
                unsafe_allow_html=True,
            )
    else:
        st.markdown(f"## {title}")
        st.caption(subtitle)


def style_plotly_figure(fig, height: int = 340):
    """Apply consistent, theme-aware typography, margins, and gridlines to a Plotly figure."""
    fig.update_layout(
        height=height,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, system-ui, -apple-system, sans-serif", size=12),
        margin=dict(l=16, r=16, t=28, b=16),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
            bgcolor="rgba(0,0,0,0)",
        ),
    )
    fig.update_xaxes(showgrid=False, zeroline=False)
    fig.update_yaxes(gridcolor="rgba(148, 163, 184, 0.18)", zeroline=False)
    return fig


def apply_clean_theme() -> None:
    """Inject production-grade CSS for typography, cards, navigation, forms, and responsiveness."""
    st.markdown(
        """
        <style>
        /* Layout & Container Spacing */
        .block-container {
            padding-top: 1.4rem !important;
            padding-bottom: 2.75rem !important;
            padding-left: 2rem !important;
            padding-right: 2rem !important;
            max-width: 1440px;
        }

        /* Typography Hierarchy */
        html, body, [class*="css"] {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            -webkit-font-smoothing: antialiased;
        }
        h1, h2, h3 {
            letter-spacing: -0.02em;
            font-weight: 650 !important;
            line-height: 1.25 !important;
        }
        h2 {
            font-size: 1.6rem !important;
            margin-top: 0 !important;
            margin-bottom: 0.2rem !important;
        }
        h4 {
            font-size: 1.05rem !important;
            margin-top: 0.25rem !important;
            margin-bottom: 0.55rem !important;
            font-weight: 600 !important;
            letter-spacing: -0.01em;
        }

        /* Metric Cards */
        div[data-testid="stMetric"] {
            background-color: rgba(148, 163, 184, 0.055);
            border: 1px solid rgba(148, 163, 184, 0.22);
            border-radius: 10px;
            padding: 0.8rem 1rem !important;
            box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
            transition: border-color 0.15s ease, box-shadow 0.15s ease;
        }
        div[data-testid="stMetric"]:hover {
            border-color: rgba(37, 99, 235, 0.35);
            box-shadow: 0 3px 8px rgba(15, 23, 42, 0.06);
        }
        div[data-testid="stMetricLabel"] {
            font-size: 0.78rem !important;
            font-weight: 600 !important;
            text-transform: uppercase;
            letter-spacing: 0.03em;
            opacity: 0.78;
        }
        div[data-testid="stMetricValue"] {
            font-size: 1.45rem !important;
            font-weight: 650 !important;
            font-variant-numeric: tabular-nums;
            line-height: 1.3 !important;
        }

        /* Bordered Cards & Containers */
        div[data-testid="stVerticalBlockBorderWrapper"] {
            border-radius: 10px !important;
            border-color: rgba(148, 163, 184, 0.24) !important;
            box-shadow: 0 1px 3px rgba(15, 23, 42, 0.03);
        }

        /* Tabs Bar & Active State */
        div[data-baseweb="tab-list"] {
            gap: 0.35rem !important;
            border-bottom: 1px solid rgba(148, 163, 184, 0.22) !important;
            overflow-x: auto !important;
            scrollbar-width: thin;
        }
        button[data-baseweb="tab"] {
            font-size: 0.88rem !important;
            font-weight: 500 !important;
            padding: 0.55rem 0.95rem !important;
            border-radius: 6px 6px 0 0 !important;
            transition: background-color 0.15s ease, color 0.15s ease;
            white-space: nowrap !important;
        }
        button[data-baseweb="tab"][aria-selected="true"] {
            font-weight: 600 !important;
            background-color: rgba(37, 99, 235, 0.06) !important;
        }
        button[data-baseweb="tab"]:hover {
            background-color: rgba(148, 163, 184, 0.08) !important;
        }

        /* Sidebar Navigation Refinement */
        section[data-testid="stSidebar"] div[role="radiogroup"] {
            gap: 0.2rem !important;
        }
        section[data-testid="stSidebar"] div[role="radiogroup"] label {
            padding: 0.42rem 0.65rem !important;
            border-radius: 7px !important;
            transition: background-color 0.15s ease;
            width: 100%;
        }
        section[data-testid="stSidebar"] div[role="radiogroup"] label:hover {
            background-color: rgba(148, 163, 184, 0.12);
        }

        /* Buttons & Form Submit Controls */
        div.stButton > button, div[data-testid="stFormSubmitButton"] > button {
            border-radius: 8px !important;
            font-weight: 550 !important;
            font-size: 0.86rem !important;
            padding: 0.42rem 0.9rem !important;
            transition: all 0.15s ease !important;
        }
        div.stButton > button:hover, div[data-testid="stFormSubmitButton"] > button:hover {
            border-color: rgba(37, 99, 235, 0.55) !important;
            transform: translateY(-0.5px);
        }

        /* Inputs, Selectboxes, TextAreas */
        div[data-baseweb="input"], div[data-baseweb="select"], div[data-baseweb="textarea"] {
            border-radius: 7px !important;
        }

        /* Dataframes & Expanders */
        div[data-testid="stDataFrame"] {
            border-radius: 8px;
            overflow: hidden;
        }
        details[data-testid="stExpander"] {
            border-radius: 8px !important;
            border-color: rgba(148, 163, 184, 0.22) !important;
        }

        /* Responsive Adjustments for Tablet & Mobile */
        @media (max-width: 768px) {
            .block-container {
                padding-top: 1rem !important;
                padding-left: 0.9rem !important;
                padding-right: 0.9rem !important;
            }
            h2 {
                font-size: 1.3rem !important;
            }
            div[data-testid="stMetricValue"] {
                font-size: 1.2rem !important;
            }
            div[data-testid="stMetric"] {
                padding: 0.65rem 0.75rem !important;
            }
            button[data-baseweb="tab"] {
                padding: 0.45rem 0.7rem !important;
                font-size: 0.82rem !important;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
