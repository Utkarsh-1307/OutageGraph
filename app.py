import pandas as pd
import streamlit as st
from pyvis.network import Network

from src.impact import (add_what_if_link, clear_what_if_links, critical_devices, impact,
                        rank_devices, topology)

st.set_page_config(page_title="Network Outage Impact Analyzer", page_icon="📡", layout="wide")
st.title("📡 Network Outage Impact Analyzer")
st.caption("Neo4j knowledge graph of an enterprise network · fictional data for demonstration")

try:
    topo = topology()
except Exception as e:
    st.error("Can't reach the Neo4j database. If you're on AuraDB Free, the instance may be "
             "paused: resume it at https://console.neo4j.io, wait a minute, then refresh. "
             "Also check NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD in .env.")
    st.caption(f"{type(e).__name__}: {e}")
    st.stop()
if not topo["devices"]:
    st.warning("The database is empty. Load the graph with `python -m src.load_data`, then refresh.")
    st.stop()
names = {d["id"]: d["name"] for d in topo["devices"]}
label = lambda x: f"{x} · {names[x]}"

# ---------- sidebar: failures ----------
failed = st.sidebar.multiselect("💥 Fail device(s)", sorted(names), format_func=label,
                                placeholder="— no failure —")

# ---------- sidebar: what-if link ----------
what_ifs = [l for l in topo["links"] if l["what_if"]]
with st.sidebar.expander("🧪 What-if: add a backup link", expanded=bool(what_ifs)):
    a = st.selectbox("From", sorted(names), format_func=label,
                     index=sorted(names).index("AGG-PUN-1"))
    b = st.selectbox("To", sorted(names), format_func=label,
                     index=sorted(names).index("CORE-CHN"))
    latency = st.number_input("Latency (ms)", min_value=1, max_value=200, value=20)
    if st.button("➕ Add link", disabled=a == b):
        add_what_if_link(a, b, int(latency))
        st.session_state.pop("ranking", None)
        st.rerun()
    if what_ifs:
        st.write("Active what-if links:")
        for l in what_ifs:
            st.write(f"- {l['source']} ↔ {l['target']} ({l['latency_ms']} ms)")
        if st.button("🗑️ Clear what-if links"):
            clear_what_if_links()
            st.session_state.pop("ranking", None)
            st.rerun()

results = impact(failed)
down = [s for s in results if s["status"] == "DOWN"]
rerouted = [s for s in results if s["status"] == "REROUTED"]

# ---------- metrics ----------
m1, m2, m3 = st.columns(3)
m1.metric("Customers down", len({s["customer"] for s in down}))
m2.metric("Monthly revenue at risk", f"₹{sum(s['mrc_inr'] for s in down) / 1e5:.1f} lakh")
m3.metric("Services rerouted", len(rerouted))

# ---------- graph ----------
customer_status = {}
for s in results:
    rank = {"DOWN": 2, "REROUTED": 1, "OK": 0}[s["status"]]
    customer_status[s["customer_id"]] = max(customer_status.get(s["customer_id"], 0), rank)

DEVICE_COLOR = {"core": "#1f4e79", "aggregation": "#2e86c1", "edge": "#85c1e9"}
DEVICE_SHAPE = {"core": "diamond", "aggregation": "dot", "edge": "square"}
STATUS_COLOR = {0: "#27ae60", 1: "#f39c12", 2: "#e74c3c"}

net = Network(height="600px", width="100%", bgcolor="#ffffff")
for d in topo["devices"]:
    is_failed = d["id"] in failed
    net.add_node(d["id"], label=d["id"], shape=DEVICE_SHAPE[d["type"]],
                 color="#e74c3c" if is_failed else DEVICE_COLOR[d["type"]],
                 size=30 if d["type"] == "core" else 18,
                 title=f"{d['name']} ({d['city']})")
for l in topo["links"]:
    touches_failed = l["source"] in failed or l["target"] in failed
    if touches_failed:
        color, width = "#e74c3c", 3
    elif l["what_if"]:
        color, width = "#8e44ad", 3
    else:
        color, width = "#95a5a6", 1
    net.add_edge(l["source"], l["target"], color=color, width=width, dashes=l["what_if"],
                 title=f"{l['latency_ms']} ms" + (" (what-if)" if l["what_if"] else ""))
for acc in topo["access"]:
    cid = "cust:" + acc["customer_id"]
    net.add_node(cid, label=acc["customer"], shape="box",
                 color=STATUS_COLOR[customer_status.get(acc["customer_id"], 0)])
    net.add_edge(cid, acc["device"], dashes=True, color="#bdc3c7")

st.iframe(net.generate_html(), height=620)
st.caption("◆ core · ● aggregation · ■ edge · boxes = customers (🟢 OK · 🟠 rerouted · 🔴 down)"
           " · purple dashed = what-if link")

# ---------- tables ----------
if down:
    st.subheader("🔴 Services down")
    st.dataframe(pd.DataFrame(down)[["customer", "tier", "service", "mrc_inr"]], hide_index=True)
if rerouted:
    st.subheader("🟠 Services surviving on a backup path")
    st.dataframe(pd.DataFrame([{
        "customer": s["customer"], "service": s["service"],
        "old path": " → ".join(s["old_path"]), "new path": " → ".join(s["new_path"]),
        "latency": f"{s['old_latency_ms']} ms → {s['new_latency_ms']} ms",
    } for s in rerouted]), hide_index=True)

# ---------- single points of failure ----------
st.divider()
left, right = st.columns(2)

with left:
    if st.button("🔍 Find single points of failure"):
        st.session_state["ranking"] = rank_devices()
    if "ranking" in st.session_state:
        df = pd.DataFrame(st.session_state["ranking"])
        df = df[df["revenue_at_risk_inr"] > 0]
        st.subheader("Most critical devices (if this one fails alone)")
        st.dataframe(df, hide_index=True)

with right:
    if st.button("🕸️ Centrality analysis"):
        st.session_state["centrality"] = True
    if st.session_state.get("centrality"):
        rows, engine = critical_devices(topo)
        st.subheader("Betweenness centrality & articulation points")
        st.caption(f"Engine: {engine}. An articulation point is a device whose removal "
                   "splits the network, which makes it a structural single point of failure.")
        st.dataframe(pd.DataFrame(rows), hide_index=True)
