"""
Clean UI theme and layout helpers for the PBL Mentor & Team Dashboards.

Applies consistent spacing, subtle card elevation, compact metric typography,
and organized tab navigation to eliminate visual clutter without removing any features.
"""

from __future__ import annotations

import streamlit as st


def apply_clean_theme() -> None:
    """Inject clean, non-intrusive CSS rules for spacing, cards, metrics, and tabs."""
    st.markdown(
        """
        <style>
        /* Reduce excessive top padding while keeping breathing room */
        .block-container {
            padding-top: 1.5rem !important;
            padding-bottom: 2.5rem !important;
            max-width: 1380px !important;
        }

        /* Clean metric cards */
        div[data-testid="stMetric"] {
            background-color: rgba(128, 128, 128, 0.06);
            border: 1px solid rgba(128, 128, 128, 0.16);
            border-radius: 10px;
            padding: 12px 16px;
        }
        div[data-testid="stMetricLabel"] > div {
            font-size: 0.82rem !important;
            font-weight: 600 !important;
            opacity: 0.82;
        }
        div[data-testid="stMetricValue"] > div {
            font-size: 1.45rem !important;
            font-weight: 700 !important;
        }

        /* Clean tab bar styling with generous spacing */
        button[data-baseweb="tab"] {
            font-weight: 600 !important;
            padding: 10px 18px !important;
        }

        /* Subtle container borders */
        div[data-testid="stVerticalBlockBorderWrapper"] {
            border-radius: 10px !important;
        }

        /* Compact dataframe headers */
        .stDataFrame {
            border-radius: 8px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
