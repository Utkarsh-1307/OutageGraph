import os

from dotenv import load_dotenv
from neo4j import GraphDatabase, RoutingControl

load_dotenv()

_driver = None


def get_driver():
    """Create one driver and reuse it everywhere."""
    global _driver
    if _driver is None:
        driver = GraphDatabase.driver(
            os.getenv("NEO4J_URI"),
            auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD")),
        )
        try:
            driver.verify_connectivity()
        except Exception:
            driver.close()          # don't cache a broken driver; retry on next call
            raise
        _driver = driver
    return _driver


def run_read(cypher: str, params: dict | None = None) -> list[dict]:
    records, _, _ = get_driver().execute_query(
        cypher, params or {}, routing_=RoutingControl.READ
    )
    return [r.data() for r in records]


def run_write(cypher: str, params: dict | None = None):
    _, summary, _ = get_driver().execute_query(cypher, params or {})
    return summary.counters


if __name__ == "__main__":
    print(run_read("RETURN 'Connected!' AS msg"))
