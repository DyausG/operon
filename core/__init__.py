"""Sentinel — Agentic Predictive Maintenance POC (UI-agnostic core).

This package holds all domain logic — dataset, ML model, fleet simulator,
governed tools, the Bedrock agent, and the demo engine — with no dependency on
any particular front end. A FastAPI layer (server/) and a React dashboard sit on
top of it, but the core could equally be driven from a notebook or a CLI.
"""
