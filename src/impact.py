import networkx as nx

from src.db import run_read, run_write

SERVICES = """
MATCH (c:Customer)-[:SUBSCRIBES_TO]->(s:Service)
RETURN s.id AS service_id, c.id AS customer_id, c.name AS customer, c.tier AS tier,
       s.type AS service, s.mrc_inr AS mrc_inr
ORDER BY s.mrc_inr DESC
"""

BEST_PATH = """
MATCH (svc:Service)-[:DELIVERED_VIA]->(a:Device), (core:Device {type: 'core'})
WHERE NOT a.id IN $failed AND NOT core.id IN $failed
MATCH p = shortestPath((a)-[:CONNECTED_TO*..6]-(core))
WHERE none(n IN nodes(p) WHERE n.id IN $failed)
WITH svc, p ORDER BY length(p) ASC
WITH svc, collect(p)[0] AS best
RETURN svc.id AS service_id,
       [n IN nodes(best) | n.id] AS path,
       reduce(t = 0, r IN relationships(best) | t + r.latency_ms) AS latency_ms
"""

DEVICES = """
MATCH (d:Device)-[:LOCATED_AT]->(s:Site)
RETURN d.id AS id, d.name AS name, d.type AS type, s.city AS city ORDER BY d.id
"""
LINKS = """
MATCH (a:Device)-[r:CONNECTED_TO]->(b:Device)
RETURN a.id AS source, b.id AS target, r.latency_ms AS latency_ms,
       coalesce(r.what_if, false) AS what_if
"""
ACCESS = """
MATCH (c:Customer)-[:SUBSCRIBES_TO]->(:Service)-[:DELIVERED_VIA]->(d:Device)
RETURN DISTINCT c.id AS customer_id, c.name AS customer, d.id AS device
"""

ADD_WHAT_IF = """
MATCH (a:Device {id: $a}), (b:Device {id: $b})
WHERE NOT (a)-[:CONNECTED_TO]-(b)
MERGE (a)-[r:CONNECTED_TO {what_if: true}]->(b) SET r.latency_ms = $latency_ms
"""
CLEAR_WHAT_IF = "MATCH ()-[r:CONNECTED_TO {what_if: true}]->() DELETE r"


def best_paths(failed: list[str]) -> dict:
    rows = run_read(BEST_PATH, {"failed": failed})
    return {r["service_id"]: r for r in rows}


def impact(failed: list[str] | None = None) -> list[dict]:
    """Status of every service if all `failed` devices go down together ([] = no failure)."""
    failed = list(failed or [])
    baseline = best_paths([])
    now = best_paths(failed) if failed else baseline
    results = []
    for s in run_read(SERVICES):
        before = baseline.get(s["service_id"])
        after = now.get(s["service_id"])
        if after is None:
            status = "DOWN"
        elif before and any(f in before["path"] for f in failed):
            status = "REROUTED"
        else:
            status = "OK"
        results.append({
            **s,
            "status": status,
            "old_path": before["path"] if before else [],
            "new_path": after["path"] if after else [],
            "old_latency_ms": before["latency_ms"] if before else None,
            "new_latency_ms": after["latency_ms"] if after else None,
        })
    return results


def rank_devices() -> list[dict]:
    """Fail every device one by one and rank by revenue at risk."""
    ranking = []
    for d in run_read(DEVICES):
        down = [s for s in impact([d["id"]]) if s["status"] == "DOWN"]
        ranking.append({
            "device": d["id"],
            "type": d["type"],
            "city": d["city"],
            "customers_down": len({s["customer"] for s in down}),
            "revenue_at_risk_inr": sum(s["mrc_inr"] for s in down),
        })
    return sorted(ranking, key=lambda r: r["revenue_at_risk_inr"], reverse=True)


def topology() -> dict:
    return {"devices": run_read(DEVICES), "links": run_read(LINKS), "access": run_read(ACCESS)}


# ---------- what-if links ----------

def add_what_if_link(a: str, b: str, latency_ms: int = 20):
    """Add a temporary backup link (skipped if the two devices are already linked)."""
    return run_write(ADD_WHAT_IF, {"a": a, "b": b, "latency_ms": latency_ms})


def clear_what_if_links():
    return run_write(CLEAR_WHAT_IF)


# ---------- centrality (GDS if available, networkx otherwise) ----------

GDS_PROJECT = """
CALL gds.graph.project('net_tmp', 'Device', {CONNECTED_TO: {orientation: 'UNDIRECTED'}})
"""
GDS_BETWEENNESS = """
CALL gds.betweenness.stream('net_tmp') YIELD nodeId, score
RETURN gds.util.asNode(nodeId).id AS device, score
"""
GDS_ARTICULATION = """
CALL gds.articulationPoints.stream('net_tmp') YIELD nodeId
RETURN gds.util.asNode(nodeId).id AS device
"""
GDS_DROP = "CALL gds.graph.drop('net_tmp', false) YIELD graphName RETURN graphName"


def _centrality_gds() -> tuple[dict, set]:
    run_read("RETURN gds.version() AS v")      # raises if GDS isn't installed
    run_write(GDS_DROP)
    run_write(GDS_PROJECT)
    try:
        scores = {r["device"]: r["score"] for r in run_read(GDS_BETWEENNESS)}
        cut = {r["device"] for r in run_read(GDS_ARTICULATION)}
    finally:
        run_write(GDS_DROP)
    return scores, cut


def _centrality_networkx(topo: dict) -> tuple[dict, set]:
    g = nx.Graph()
    g.add_nodes_from(d["id"] for d in topo["devices"])
    g.add_edges_from((l["source"], l["target"]) for l in topo["links"])
    return nx.betweenness_centrality(g, normalized=False), set(nx.articulation_points(g))


def critical_devices(topo: dict | None = None) -> tuple[list[dict], str]:
    """Betweenness centrality + articulation points of the device graph.

    Uses Neo4j Graph Data Science when installed (AuraDS / self-managed); AuraDB Free
    has no GDS, so it falls back to networkx on the same topology.
    """
    topo = topo or topology()
    try:
        scores, cut = _centrality_gds()
        engine = "Neo4j GDS"
    except Exception:
        scores, cut = _centrality_networkx(topo)
        engine = "networkx (GDS not available)"
    rows = [{
        "device": d["id"],
        "type": d["type"],
        "city": d["city"],
        "betweenness": round(scores.get(d["id"], 0.0), 2),
        "articulation_point": d["id"] in cut,
    } for d in topo["devices"]]
    rows.sort(key=lambda r: r["betweenness"], reverse=True)
    return rows, engine


if __name__ == "__main__":
    for s in impact(["AGG-BLR-1"]):
        if s["status"] != "OK":
            print(s["status"], s["customer"], s["service"], s["old_path"], "->", s["new_path"])
    print("\nTop 5 critical devices:")
    for r in rank_devices()[:5]:
        print(r)
