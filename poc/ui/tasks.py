"""Human-in-the-loop governance task queue.

Tasks are deterministic proposals created by the anomaly pipeline. The system
suggests an owner and action but the human must approved it. In the PoC
there is no integration thus it's more a show-casing of capability rather
than actually notifying anyone.
"""
from __future__ import annotations

import json

import streamlit as st

from teaf import store


def _delete_controls(task) -> None:
    confirm_key = "governance_task_delete_confirm"
    if st.session_state.get(confirm_key) == task["id"]:
        st.warning("Delete this task permanently?")
        yes, no = st.columns(2)
        if yes.button("Confirm delete", key=f"confirm_delete_{task['id']}", type="primary"):
            store.delete_governance_task(task["id"])
            st.session_state.pop(confirm_key, None)
            st.rerun()
        if no.button("Cancel", key=f"cancel_delete_{task['id']}"):
            st.session_state.pop(confirm_key, None)
            st.rerun()
    elif st.button("Delete", key=f"delete_{task['id']}"):
        st.session_state[confirm_key] = task["id"]
        st.rerun()


def _approve(task, owner: str) -> None:
    try:
        store.update_governance_task_owner(task["id"], owner)
        store.update_governance_task_status(task["id"], "approved")
    except ValueError as exc:
        st.error(str(exc))
        return
    st.rerun()


def _render_task(task) -> None:
    with st.expander(f"{task['title']} · {task['app_id']}"):
        st.markdown(f"**Action:** {task['action']}")
        details = [
            f"**Source:** `{task['source']}`",
            f"**Reason:** `{task['reason']}`",
        ]
        if task["anomaly_score"] is not None:
            details.append(f"**Anomaly score:** `{task['anomaly_score']}`")
        st.markdown("  \n".join(details))

        try:
            evidence = json.loads(task["evidence"] or "{}")
        except (TypeError, json.JSONDecodeError):
            evidence = {"raw": task["evidence"]}
        st.markdown("**Evidence:**")
        st.json(evidence, expanded=False)

        owner = task["suggested_owner"]
        if task["status"] != "approved":
            owner = st.text_input(
                "Owner used when approved",
                value=owner,
                key=f"task_owner_{task['id']}",
            )
        else:
            st.markdown(f"**Assigned owner:** {owner}")

        action_cols = st.columns(3)
        if task["status"] != "approved":
            if action_cols[0].button("Approve", key=f"approve_{task['id']}", type="primary"):
                _approve(task, owner)
        if task["status"] != "rejected":
            if action_cols[1].button("Reject", key=f"reject_{task['id']}"):
                store.update_governance_task_status(task["id"], "rejected")
                st.rerun()
        with action_cols[2]:
            _delete_controls(task)


def _render_grouped(tasks) -> None:
    if not tasks:
        st.info("No tasks in this state.")
        return

    grouped: dict[str, list] = {}
    for task in tasks:
        grouped.setdefault(task["suggested_owner"], []).append(task)
    for owner in sorted(grouped, key=str.casefold):
        st.subheader(f"{owner} ({len(grouped[owner])})")
        for task in grouped[owner]:
            _render_task(task)


def render() -> None:
    st.title("📋 Governance Tasks")
    st.caption(
        "Anomaly detection proposes these governance actions deterministically. "
        "A human approves, reassigns, rejects, or deletes every task."
    )

    pending = store.list_governance_tasks("pending")
    approved = store.list_governance_tasks("approved")
    rejected = store.list_governance_tasks("rejected")

    c1, c2, c3 = st.columns(3)
    c1.metric("Pending", len(pending))
    c2.metric("Approved", len(approved))
    c3.metric("Rejected", len(rejected))

    tabs = st.tabs([
        f"Pending ({len(pending)})",
        f"Approved ({len(approved)})",
        f"Rejected ({len(rejected)})",
    ])
    with tabs[0]:
        _render_grouped(pending)
    with tabs[1]:
        _render_grouped(approved)
    with tabs[2]:
        _render_grouped(rejected)
