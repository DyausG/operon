"""Application-side reasoning backends and the strict remote reasoning protocol.

AGENTS REASON. THE APPLICATION OWNS AUTHORITY.

A backend returns one advisory ``SupervisorResult`` per durable run. The application
persists it, re-audits it and alone promotes, approves, executes, verifies and closes.
A packet-mode run sees only an application-built, bounded evidence packet and can
merely name evidence needs; it holds no store, no write path and no durable IDs.

Importing this package creates no model, agent, credential session, client or socket.
"""
