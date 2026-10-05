import json
from pathlib import Path

from src.db import run_write

DATA = Path(__file__).resolve().parent.parent / "data" / "network.json"

CONSTRAINTS = [
    "CREATE CONSTRAINT device_id IF NOT EXISTS FOR (n:Device) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT customer_id IF NOT EXISTS FOR (n:Customer) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT service_id IF NOT EXISTS FOR (n:Service) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT site_id IF NOT EXISTS FOR (n:Site) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT region_name IF NOT EXISTS FOR (n:Region) REQUIRE n.name IS UNIQUE",
]

LOAD_SITES = """
UNWIND $sites AS s
MERGE (r:Region {name: s.region})
MERGE (x:Site {id: s.id}) SET x.city = s.city
MERGE (x)-[:IN_REGION]->(r)
"""

LOAD_DEVICES = """
UNWIND $devices AS d
MATCH (s:Site {id: d.site})
MERGE (x:Device {id: d.id}) SET x.name = d.name, x.type = d.type
MERGE (x)-[:LOCATED_AT]->(s)
"""

LOAD_LINKS = """
UNWIND $links AS l
MATCH (a:Device {id: l.a}), (b:Device {id: l.b})
MERGE (a)-[r:CONNECTED_TO]->(b) SET r.latency_ms = l.latency_ms
"""

LOAD_CUSTOMERS = """
UNWIND $customers AS c
MERGE (x:Customer {id: c.id}) SET x.name = c.name, x.industry = c.industry, x.tier = c.tier
WITH x, c
UNWIND c.services AS s
MERGE (svc:Service {id: s.id}) SET svc.type = s.type, svc.mrc_inr = s.mrc_inr, svc.sla_pct = s.sla_pct
MERGE (x)-[:SUBSCRIBES_TO]->(svc)
WITH svc, s
UNWIND s.via AS dev
MATCH (d:Device {id: dev})
MERGE (svc)-[:DELIVERED_VIA]->(d)
"""


def main():
    data = json.loads(DATA.read_text(encoding="utf-8"))
    run_write("MATCH (n) DETACH DELETE n")          # fresh start every time
    for q in CONSTRAINTS:
        run_write(q)
    print("sites:    ", run_write(LOAD_SITES, {"sites": data["sites"]}))
    print("devices:  ", run_write(LOAD_DEVICES, {"devices": data["devices"]}))
    print("links:    ", run_write(LOAD_LINKS, {"links": data["links"]}))
    print("customers:", run_write(LOAD_CUSTOMERS, {"customers": data["customers"]}))
    print("✅ Network graph loaded")


if __name__ == "__main__":
    main()
