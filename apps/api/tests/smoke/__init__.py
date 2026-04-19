"""Demo smoke tests — hit the running docker stack over HTTP + bolt.

These tests assume:
- API at http://localhost:8000
- Neo4j at bolt://localhost:7688 (auth neo4j / neo4jpassword)

Run with:  pytest -m smoke -v
"""
