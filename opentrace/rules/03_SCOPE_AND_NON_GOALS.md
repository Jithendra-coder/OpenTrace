# Scope and Non-Goals

Initial scope is OpenAPI-described REST APIs, Python repositories, `requests` and `httpx`, static analysis, direct impact, Python call graphs, transitive blast radius, and explainable ranking. ML and migration generation are later roadmap work, not early deliverables.

Deferred non-goals: Kubernetes and multi-cloud orchestration (operational complexity); Kafka and microservices (different dependency semantics); Neo4j (NetworkX suffices initially); mobile apps and ten languages (language-specific analysis); complex billing and enterprise RBAC (not core evidence); fully autonomous agents and automatic merge (unsafe); custom vector databases and whole-repository LLM prompting (unjustified cost/confidentiality); twenty providers (provider abstraction precedes breadth).

Adding scope needs an ADR, milestone placement, contracts, security review, tests, and a demonstrated gap—not novelty.
