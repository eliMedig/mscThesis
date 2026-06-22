"""TEAF PoC — Streamlit entrypoint and page router (single process, multipage).

Run from the repo root:  streamlit run poc/app.py

Theme: TWO token palettes (dark + light) selected from Settings. ALL custom
styling references CSS variables, so switching the toggle swaps the whole theme with
no hardcoded, theme-specific colours. The native dark base (config.toml) only sets
the first paint; the variables below drive everything.
"""
import streamlit as st

import config
from teaf import store
from ui import admin_patches, chat, settings

st.set_page_config(
    page_title="TEAF PoC",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)

_DARK_TOKENS = """
  --bg:#101114; --surface-1:#181b20; --surface-2:#22262d;
  --surface-3:#2a3038; --border:#3b424d; --table-border:#5a6372; --text:#f2f4f8; --text-muted:#b2bac6;
  --primary:#4f8cff; --primary-soft:#172a4d; --accent-coach:#22c55e; --accent-coach-soft:#143521;
  --user-surface:#17243d; --coach-surface:#162b20; --shadow:0 16px 42px rgba(0,0,0,.28);
"""
_LIGHT_TOKENS = """
  --bg:#f4f6f8; --surface-1:#ffffff; --surface-2:#eef2f6;
  --surface-3:#dbe3ee; --border:#9aa7b8; --table-border:#7f8da1; --text:#151922; --text-muted:#3f4c5c;
  --primary:#2563eb; --primary-soft:#dbeafe; --accent-coach:#15803d; --accent-coach-soft:#dcfce7;
  --user-surface:#eaf2ff; --coach-surface:#eaf8ef; --shadow:0 14px 34px rgba(24,35,55,.12);
"""

_STYLE = """
  [data-testid="stToolbar"] { display:none !important; }
  [data-testid="collapsedControl"], [data-testid="stSidebarCollapseButton"] { display:none !important; }

  /* page + sidebar surfaces */
  .stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"], [data-testid="stHeader"],
  [data-testid="stBottom"], [data-testid="stBottom"] > div, [data-testid="stBottomBlockContainer"] {
    background:var(--bg) !important;
  }
  [data-testid="stSidebar"] {
    background:var(--surface-1) !important; border-right:1px solid var(--border);
    display:block !important; visibility:visible !important; opacity:1 !important;
    min-width:18rem !important; width:18rem !important; transform:translateX(0) !important;
    margin-left:0 !important; z-index:999999 !important;
  }
  [data-testid="stSidebar"][aria-expanded="false"],
  [data-testid="stSidebar"][aria-hidden="true"] {
    display:block !important; visibility:visible !important; opacity:1 !important;
    transform:translateX(0) !important; margin-left:0 !important;
  }
  [data-testid="stSidebarContent"] { display:block !important; visibility:visible !important; opacity:1 !important; }
  [data-testid="stSidebarNav"] { padding-top:0 !important; }

  /* text */
  h1,h2,h3,h4,h5,h6, [data-testid="stMarkdownContainer"] p, [data-testid="stMarkdownContainer"] li,
  [data-testid="stWidgetLabel"] p, label, .stRadio label { color:var(--text) !important; }
  [data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p { color:var(--text-muted) !important; }

  /* toast / transient saved flags */
  [data-testid="stToast"],
  [data-testid="stToast"] *,
  [data-testid="stToastContainer"],
  [data-testid="stToastContainer"] * {
    color:var(--text) !important;
    -webkit-text-fill-color:var(--text) !important;
  }
  [data-testid="stToast"] {
    background:var(--surface-1) !important;
    border:1px solid var(--border) !important;
    box-shadow:var(--shadow) !important;
  }

  /* sidebar title + bottom-left version */
  [data-testid="stSidebarNav"]::before {
    content:"TEAF PoC"; display:block; font-size:1.9rem; font-weight:800;
    letter-spacing:0; color:var(--primary); padding:.15rem 1rem .25rem 1rem;
  }
  .teaf-version { position:fixed; left:.9rem; bottom:.55rem; max-width:15rem; font-size:.72rem; color:var(--text-muted); z-index:100; }

  /* cards / expanders: filled surface + visible border */
  div[data-testid="stVerticalBlockBorderWrapper"] { background:var(--surface-1) !important; border:1px solid var(--border) !important; border-radius:10px; }
  [data-testid="stExpander"] details { background:var(--surface-1) !important; border:1px solid var(--border) !important; border-radius:10px; }
  [data-testid="stExpander"] summary,
  [data-testid="stExpander"] summary *,
  [data-testid="stExpander"] [data-testid="stMarkdownContainer"],
  [data-testid="stExpander"] [data-testid="stMarkdownContainer"] * {
    color:var(--text) !important;
    -webkit-text-fill-color:var(--text) !important;
  }
  [data-testid="stExpander"] summary { background:var(--surface-2) !important; border-radius:8px !important; }
  [data-testid="stExpander"] summary svg { color:var(--text) !important; fill:var(--text) !important; }
  [data-testid="stExpander"] pre,
  [data-testid="stExpander"] code,
  [data-testid="stExpander"] [data-testid="stText"],
  [data-testid="stExpander"] [data-testid="stText"] * {
    background:var(--surface-2) !important;
    color:var(--text) !important;
    -webkit-text-fill-color:var(--text) !important;
    border-color:var(--border) !important;
    overflow-wrap:anywhere !important;
    white-space:pre-wrap !important;
  }

  /* conversation bubbles */
  [data-testid="stChatMessage"] {
    background:var(--surface-1) !important; border:1px solid var(--border) !important;
    border-radius:8px !important; box-shadow:var(--shadow) !important;
    padding:.85rem 1rem !important; margin:.75rem 0 !important;
  }
  [data-testid="stChatMessage"]:has(.teaf-user-message) {
    background:linear-gradient(180deg, var(--user-surface), var(--primary-soft)) !important;
    border-color:var(--primary) !important;
  }
  [data-testid="stChatMessage"]:has(.teaf-agent-message) {
    background:linear-gradient(180deg, var(--coach-surface), var(--surface-1)) !important;
    border-color:var(--accent-coach) !important;
  }
  .teaf-chat-sentinel { display:none; }
  [data-testid="stChatMessage"] h1,
  [data-testid="stChatMessage"] h2,
  [data-testid="stChatMessage"] h3 {
    font-size:1rem !important; line-height:1.35 !important; margin:.65rem 0 .35rem 0 !important;
    font-weight:800 !important; letter-spacing:0 !important;
  }
  [data-testid="stChatMessage"] h4,
  [data-testid="stChatMessage"] h5,
  [data-testid="stChatMessage"] h6 {
    font-size:.95rem !important; line-height:1.35 !important; margin:.55rem 0 .3rem 0 !important;
    font-weight:800 !important; letter-spacing:0 !important;
  }
  [data-testid="stChatMessage"] p, [data-testid="stChatMessage"] li { line-height:1.5 !important; }
  [data-testid="stChatMessage"] table {
    width:100%; border-collapse:collapse; margin:.7rem 0; font-size:.9rem;
  }
  [data-testid="stChatMessage"] th {
    background:var(--surface-3) !important; color:var(--text) !important;
    border:1px solid var(--table-border) !important; padding:7px 9px !important; text-align:left;
  }
  [data-testid="stChatMessage"] td {
    background:var(--surface-1) !important; color:var(--text) !important;
    border:1px solid var(--table-border) !important; padding:7px 9px !important;
  }
  .teaf-chat-row { display:flex; width:100%; margin:.7rem 0; }
  .teaf-chat-row-user { justify-content:flex-end; }
  .teaf-chat-row-coach { justify-content:flex-start; }
  .teaf-chat-bubble {
    width:min(760px, 88%); border:1px solid var(--border); border-radius:8px;
    padding:.85rem 1rem; box-shadow:var(--shadow); color:var(--text);
  }
  .teaf-chat-user { background:linear-gradient(180deg, var(--user-surface), var(--primary-soft)); border-color:var(--primary); }
  .teaf-chat-coach { background:linear-gradient(180deg, var(--coach-surface), var(--accent-coach-soft)); border-color:var(--accent-coach); }
  .teaf-chat-meta {
    display:flex; align-items:center; gap:.45rem; margin-bottom:.45rem;
    font-size:.78rem; font-weight:800; color:var(--text); text-transform:uppercase;
    letter-spacing:0;
  }
  .teaf-chat-badge {
    display:inline-flex; align-items:center; border:1px solid var(--border);
    border-radius:999px; padding:.08rem .45rem; font-size:.7rem; color:var(--text-muted);
    background:var(--surface-1);
  }
  .teaf-chat-badge-coaching { color:var(--primary); border-color:var(--primary); background:var(--primary-soft); }
  .teaf-chat-badge-facilitation { color:var(--accent-coach); border-color:var(--accent-coach); background:var(--accent-coach-soft); }
  .teaf-chat-badge-consulting { color:#b45309; border-color:#f59e0b; background:#fef3c7; }
  .teaf-chat-content { font-size:.98rem; line-height:1.55; overflow-wrap:anywhere; }

  /* Conversation heading + small "session #" version-style tag */
  h3.teaf-conversation-heading { color:var(--text) !important; margin:.2rem 0 .4rem 0; }
  .teaf-session-tag {
    margin-left:.6rem; font-size:.82rem; font-weight:600; letter-spacing:.01em;
    color:var(--text-muted) !important; text-transform:none; line-height:1.4; white-space:nowrap;
  }

  /* Safe global page padding. Chat uses keyed containers below for compactness;
     Settings/Tacit pages still need top breathing room so titles are not clipped. */
  [data-testid="stMainBlockContainer"] { padding-top:3.6rem !important; padding-bottom:.45rem !important; }
  [data-testid="stMain"] h1 { margin:0 0 .55rem 0 !important; padding:0 !important; font-size:1.7rem !important; }
  [data-testid="stMain"] hr { margin:.5rem 0 !important; }

  /* Data Sources panel: tight padding + tight rows (not spaced cards). */
  .st-key-data_sources { padding:.55rem .8rem !important; }
  .st-key-data_sources [data-testid="stVerticalBlock"] { gap:.4rem !important; }
  .st-key-data_sources [data-testid="stExpander"] summary { padding:.3rem .65rem !important; min-height:0 !important; }
  .st-key-data_sources [data-testid="stExpander"] details { border-radius:8px !important; }
  .st-key-data_sources [data-testid="stAlert"] { padding:.45rem .7rem !important; }

  /* message-history scroll region: fixed height that adapts to the viewport so the
     header (title + Data Sources) stays put and only the history scrolls, filling the
     space down to the input. Overrides the inline px height from st.container(height=…). */
  .st-key-chat_history [data-testid="stVerticalBlockBorderWrapper"] {
    height:clamp(32rem, calc(100vh - 7.25rem), 78rem) !important;
    min-height:32rem !important;
    max-height:none !important;
    overflow-y:auto !important;
  }
  .st-key-chat_history [data-testid="stChatMessage"],
  .st-key-chat_history [data-testid="stChatMessage"] > div,
  .st-key-chat_history [data-testid="stChatMessage"] [data-testid="stVerticalBlock"] {
    height:auto !important;
    min-height:0 !important;
    max-height:none !important;
  }

  /* conversation starter chips: rendered in normal flow (last block before the chat
     input) so they share the main block's bounds with the input — same left edge and
     width, no overflow, and the alignment tracks layout changes automatically rather
     than relying on hardcoded pixel offsets. */
  .st-key-teaf_starters { margin-top:.25rem; }
  .st-key-teaf_starters [data-testid="stHorizontalBlock"] { gap:.6rem !important; }
  .st-key-teaf_starters [data-testid="stCaptionContainer"] { margin-bottom:.2rem; }
  .st-key-teaf_starters .stButton button {
    background:var(--surface-1) !important;
    color:var(--text) !important;
    -webkit-text-fill-color:var(--text) !important;
    border:1px solid var(--border) !important;
    box-shadow:none !important;
    font-weight:600 !important;
  }
  .st-key-teaf_starters .stButton button * {
    color:inherit !important;
    -webkit-text-fill-color:inherit !important;
  }
  .st-key-teaf_starters .stButton button:hover {
    background:var(--surface-2) !important;
    border-color:var(--primary) !important;
    filter:none !important;
  }

  /* inputs / select / uploader */
  input, textarea, [data-baseweb="base-input"], [data-baseweb="textarea"], [data-baseweb="input"], [data-baseweb="select"] > div {
    background:var(--surface-2) !important; color:var(--text) !important; border:1px solid var(--border) !important; border-radius:8px !important;
  }
  input:focus, textarea:focus { border-color:var(--primary) !important; }
  input::placeholder, textarea::placeholder { color:var(--text-muted) !important; opacity:1 !important; }
  [data-testid="stFileUploader"],
  [data-testid="stFileUploader"] *,
  [data-testid="stFileUploaderDropzone"],
  [data-testid="stFileUploaderDropzone"] * {
    color:var(--text) !important;
    -webkit-text-fill-color:var(--text) !important;
  }
  [data-testid="stFileUploaderDropzone"] {
    background:var(--surface-2) !important; border:1px solid var(--border) !important;
  }
  [data-testid="stFileUploaderDropzone"] button,
  [data-testid="stFileUploader"] button {
    background:var(--surface-1) !important; color:var(--text) !important;
    -webkit-text-fill-color:var(--text) !important; border:1px solid var(--border) !important;
    border-radius:8px !important;
  }
  [data-testid="stFileUploaderDropzone"] button:hover,
  [data-testid="stFileUploader"] button:hover {
    border-color:var(--primary) !important;
  }
  /* Uploaded-file chip contrast: Streamlit (base="dark") renders the selected-file
     chips INSIDE the dropzone using the native dark secondaryBackgroundColor, so in
     light mode they are dark-text-on-dark. The chip has no stable testid, so we
     neutralise those native backgrounds and let the chips inherit the themed
     dropzone surface; text comes from the dropzone rule above, icons from fill. */
  [data-testid="stFileUploaderDropzone"] div,
  [data-testid="stFileUploaderDropzone"] ul,
  [data-testid="stFileUploaderDropzone"] li {
    background-color:transparent !important;
  }
  [data-testid="stFileUploaderDropzone"] svg {
    color:var(--text) !important; fill:var(--text) !important;
  }

  /* buttons — DESCENDANT selectors (not `> button`): a button with help= is wrapped in
     a tooltip hover-target, so the direct-child selector misses it and it renders
     native dark in light mode (this was the unreadable model Test button). */
  .stButton button,
  [data-testid="stFormSubmitButton"] button,
  [data-testid="stDownloadButton"] button,
  [data-testid="stFileUploaderDropzone"] button,
  [data-testid="stFileUploader"] button {
    background:var(--primary) !important;
    color:#fff !important;
    -webkit-text-fill-color:#fff !important;
    border:1px solid var(--primary) !important;
    border-radius:8px !important;
    cursor:pointer !important;
    font-size:.86rem !important;
    font-weight:650 !important;
    padding:.34rem .85rem !important;
    min-height:2.15rem !important;
    box-shadow:none !important;
    transition:filter .12s ease, transform .12s ease;
  }
  .stButton button[kind="secondary"] { background:var(--primary) !important; color:#fff !important; border:1px solid var(--primary) !important; }
  /* button label children must follow the button's colour */
  .stButton button p, .stButton button span, .stButton button div,
  [data-testid="stFormSubmitButton"] button p, [data-testid="stFormSubmitButton"] button span,
  [data-testid="stDownloadButton"] button p, [data-testid="stDownloadButton"] button span,
  [data-testid="stFileUploaderDropzone"] button p, [data-testid="stFileUploaderDropzone"] button span,
  [data-testid="stFileUploader"] button p, [data-testid="stFileUploader"] button span {
    color:inherit !important; -webkit-text-fill-color:inherit !important;
  }
  .stButton button[kind="primary"] { background:var(--primary) !important; color:#fff !important; border-color:var(--primary) !important; }
  [data-testid="stFormSubmitButton"] > button {
    background:var(--primary) !important; color:#fff !important;
    -webkit-text-fill-color:#fff !important; border:1px solid var(--primary) !important;
    border-radius:8px !important;
  }
  [data-testid="stFormSubmitButton"] > button[kind="primary"] {
    background:var(--primary) !important; color:#fff !important;
    -webkit-text-fill-color:#fff !important; border-color:var(--primary) !important;
  }
  [data-testid="stFormSubmitButton"] > button * {
    color:inherit !important; -webkit-text-fill-color:inherit !important;
  }
  [data-testid="stDownloadButton"] > button { background:var(--primary) !important; color:#fff !important; border:1px solid var(--primary) !important; }

  /* OPTIONS / SETTINGS panel: ONE shared rule gives every button the same Delete-style
     treatment (blue bg, white text, hover, pointer) — correct in both themes, applied
     uniformly regardless of primary/secondary/help-wrapped. */
  .st-key-options_panel button,
  .st-key-options_panel [data-testid="stFormSubmitButton"] button {
    background:var(--primary) !important; border:1px solid var(--primary) !important;
    color:#fff !important; border-radius:8px !important; cursor:pointer;
    transition:filter .12s ease;
  }
  .st-key-options_panel button *,
  .st-key-options_panel [data-testid="stFormSubmitButton"] button * {
    color:#fff !important; -webkit-text-fill-color:#fff !important;
  }
  .st-key-options_panel button:hover,
  .st-key-options_panel [data-testid="stFormSubmitButton"] button:hover {
    filter:brightness(1.12); border-color:var(--primary) !important;
  }

  /* button HOVER states — our !important backgrounds above suppress Streamlit's own
     :hover, so define token-driven hover here (correct in light + dark). */
  .stButton button, [data-testid="stFormSubmitButton"] button, [data-testid="stDownloadButton"] button {
    cursor:pointer; transition:background-color .12s ease, border-color .12s ease;
  }
  .stButton button:hover,
  [data-testid="stFormSubmitButton"] button:hover,
  [data-testid="stDownloadButton"] button:hover {
    background:var(--primary) !important; border-color:var(--primary) !important;
    filter:brightness(1.12);
  }
  .stButton button[kind="primary"]:hover,
  [data-testid="stFormSubmitButton"] button[kind="primary"]:hover {
    background:var(--primary) !important; border-color:var(--primary) !important; filter:brightness(1.12);
  }

  /* Starter prompts intentionally stay calm and neutral, separate from action
     buttons. This later rule wins over Streamlit's secondary-button styling. */
  .st-key-teaf_starters .stButton button,
  .st-key-teaf_starters .stButton button[kind="secondary"] {
    background:var(--surface-2) !important;
    border:1px solid var(--border) !important;
    color:var(--text) !important;
    -webkit-text-fill-color:var(--text) !important;
    box-shadow:none !important;
    font-weight:600 !important;
    min-height:2.35rem !important;
    padding:.42rem .58rem !important;
    font-size:.82rem !important;
  }
  .st-key-teaf_starters .stButton button *,
  .st-key-teaf_starters .stButton button[kind="secondary"] * {
    color:var(--text) !important;
    -webkit-text-fill-color:var(--text) !important;
    overflow:hidden !important;
    text-overflow:ellipsis !important;
    white-space:nowrap !important;
  }
  .st-key-teaf_starters .stButton button:hover,
  .st-key-teaf_starters .stButton button[kind="secondary"]:hover {
    background:var(--surface-3) !important;
    border-color:var(--border) !important;
    filter:none !important;
  }

  /* tabs / metrics */
  .st-key-options_panel [data-baseweb="tab-list"],
  [data-baseweb="tab-list"] {
    gap:.35rem !important;
    border-bottom:1px solid var(--border) !important;
    align-items:flex-end !important;
  }
  .st-key-options_panel [data-baseweb="tab"],
  [data-baseweb="tab"] {
    background:transparent !important;
    border:0 !important;
    border-radius:0 !important;
    color:var(--text-muted) !important;
    -webkit-text-fill-color:var(--text-muted) !important;
    padding:.45rem .25rem .55rem .25rem !important;
    margin-right:1rem !important;
    min-height:2rem !important;
    box-shadow:none !important;
    filter:none !important;
  }
  .st-key-options_panel [data-baseweb="tab"] *,
  [data-baseweb="tab"] * {
    color:inherit !important;
    -webkit-text-fill-color:inherit !important;
    background:transparent !important;
  }
  .st-key-options_panel [data-baseweb="tab"]:hover,
  [data-baseweb="tab"]:hover {
    background:transparent !important;
    border:0 !important;
    filter:none !important;
  }
  .st-key-options_panel [data-baseweb="tab"][aria-selected="true"],
  [data-baseweb="tab"][aria-selected="true"] {
    color:var(--primary) !important;
    -webkit-text-fill-color:var(--primary) !important;
    box-shadow:inset 0 -2px 0 var(--primary) !important;
  }
  .st-key-options_panel button:not([data-baseweb="tab"]),
  .st-key-options_panel [data-testid="stFormSubmitButton"] button {
    background:var(--primary) !important;
    border:1px solid var(--primary) !important;
    color:#fff !important;
    -webkit-text-fill-color:#fff !important;
  }
  .st-key-options_panel button:not([data-baseweb="tab"]) *,
  .st-key-options_panel button:not([data-baseweb="tab"]) [data-testid="stMarkdownContainer"] p,
  .st-key-options_panel [data-testid="stFormSubmitButton"] button *,
  .st-key-options_panel [data-testid="stFormSubmitButton"] button [data-testid="stMarkdownContainer"] p {
    color:#fff !important;
    -webkit-text-fill-color:#fff !important;
  }
  [data-testid="stMetricValue"], [data-testid="stMetricLabel"] { color:var(--text) !important; }

  /* alerts (e.g. the model Test panel output, danger-zone notices): token surface +
     readable text in BOTH modes; the dynamic icon keeps its semantic colour */
  [data-testid="stAlert"], [data-testid="stAlertContainer"] {
    background:var(--surface-2) !important; border:1px solid var(--border) !important;
    border-radius:8px !important;
  }
  [data-testid="stAlertContainer"] p, [data-testid="stAlertContent"],
  [data-testid="stAlertContent"] p, [data-testid="stAlertContent"] li,
  [data-testid="stAlert"] [data-testid="stMarkdownContainer"] * {
    color:var(--text) !important; -webkit-text-fill-color:var(--text) !important;
  }

  /* help tooltip/popover (e.g. hovering the Test button) */
  [data-testid="stTooltipContent"] {
    background:var(--surface-1) !important; border:1px solid var(--border) !important;
    border-radius:8px !important; box-shadow:var(--shadow) !important;
  }
  [data-testid="stTooltipContent"], [data-testid="stTooltipContent"] * {
    color:var(--text) !important; -webkit-text-fill-color:var(--text) !important;
  }

  /* checkbox box (e.g. "Clear stored key") legible in light mode */
  [data-testid="stCheckbox"] label { color:var(--text) !important; }
  [data-testid="stCheckbox"] label > span:first-child {
    background-color:var(--surface-2) !important; border-color:var(--border) !important;
  }
  [data-testid="stCheckbox"] label > span:first-child[aria-checked="true"],
  [data-testid="stCheckbox"] input:checked + span:first-child {
    background-color:var(--primary) !important; border-color:var(--primary) !important;
  }

  /* kill the stray surface/border box that sits behind the pinned chat input
     (Streamlit wraps the bottom block; our generic card styling was painting it,
     which showed as a "weird box" in dark mode) */
  [data-testid="stBottom"], [data-testid="stBottom"] > div, [data-testid="stBottomBlockContainer"],
  [data-testid="stBottom"] div[data-testid="stVerticalBlockBorderWrapper"],
  [data-testid="stBottom"] div[data-testid="stVerticalBlock"] {
    background:var(--bg) !important; border:none !important; box-shadow:none !important;
  }

  /* chat composer: ONE integrated bar, inline send, focus ring */
  [data-testid="stChatInput"] {
    background:var(--surface-1) !important; border:1px solid var(--border) !important;
    border-radius:8px !important; box-shadow:var(--shadow) !important; padding:.12rem .35rem !important;
  }
  [data-testid="stChatInput"] > div { background:transparent !important; border:none !important; }
  [data-testid="stChatInput"] [data-baseweb="base-input"],
  [data-testid="stChatInput"] [data-baseweb="textarea"],
  [data-testid="stChatInput"] [data-baseweb="input"],
  [data-testid="stChatInput"] textarea {
    background:transparent !important; border:none !important; box-shadow:none !important; color:var(--text) !important;
  }
  [data-testid="stChatInput"] [data-baseweb="base-input"] > div,
  [data-testid="stChatInput"] [data-baseweb="textarea"] > div,
  [data-testid="stChatInput"] [data-baseweb="input"] > div {
    background:transparent !important; border:none !important; box-shadow:none !important;
  }
  [data-testid="stChatInput"] textarea::placeholder { color:var(--text-muted) !important; opacity:1 !important; }
  [data-testid="stChatInput"]:focus-within { border-color:var(--primary) !important; box-shadow:0 0 0 2px rgba(59,130,246,.20) !important; }
  [data-testid="stChatInput"] button { background:transparent !important; border:none !important; color:var(--primary) !important; }
  [data-testid="stChatInput"]:has(textarea:disabled) {
    background:var(--surface-2) !important; opacity:.68 !important; box-shadow:none !important;
  }
  [data-testid="stChatInput"] textarea:disabled,
  [data-testid="stChatInput"] button:disabled {
    cursor:default !important; color:var(--text-muted) !important;
  }

  /* code/pre: themed + WRAP */
  [data-testid="stCode"], pre, code { background:var(--surface-1) !important; color:var(--text) !important; }
  [data-testid="stCode"] pre, [data-testid="stCode"] code, .stMarkdown pre, .stMarkdown code {
    white-space:pre-wrap !important; overflow-wrap:anywhere !important;
  }

  /* token-styled results table (replaces the canvas dataframe so it themes in BOTH modes) */
  table.teaf-table { width:100%; border-collapse:collapse; font-size:.85rem; }
  table.teaf-table th { background:var(--surface-3); color:var(--text); border:1px solid var(--table-border); padding:6px 8px; text-align:left; }
  table.teaf-table td { background:var(--surface-1); color:var(--text); border:1px solid var(--table-border); padding:6px 8px; }

  /* fixed SVG diagrams in settings */
  .teaf-flow-diagram {
    width:100%; overflow:auto; background:var(--surface-1);
    border:1px solid var(--border); border-radius:8px; padding:.75rem;
  }
  .teaf-flow-diagram svg { min-width:940px; display:block; color:var(--text); }
  .teaf-flow-label { fill:var(--text); font-family:Arial, Helvetica, sans-serif; }
  .teaf-flow-label-muted { fill:var(--text-muted); font-family:Arial, Helvetica, sans-serif; }
  .teaf-flow-blue { color:var(--primary); fill:var(--primary); }
"""

# Idempotent: create tables + seed the two agents on first run.
store.init_db()

if "light_mode" not in st.session_state:
    st.session_state["light_mode"] = (
        str(store.get_setting(config.SETTING_LIGHT_MODE, "1")) == "1"
    )

light = bool(st.session_state.get("light_mode", True))
_tokens = _LIGHT_TOKENS if light else _DARK_TOKENS
st.markdown(f"<style>:root {{{_tokens}}}\n{_STYLE}</style>", unsafe_allow_html=True)

nav = st.navigation([
    st.Page(chat.render, title="Chat", icon="💬", url_path="chat", default=True),
    st.Page(admin_patches.render, title="Tacit Externalisation", icon="📝", url_path="tacit"),
    st.Page(settings.render, title="Settings", icon="⚙️", url_path="settings"),
])

st.sidebar.markdown(
    f"<div class='teaf-version'>Tacit Externalisation Framework · v{config.APP_VERSION}</div>",
    unsafe_allow_html=True,
)

nav.run()
