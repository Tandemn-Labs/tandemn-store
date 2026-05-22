"""Event envelope + typed payload registry. Lands in Phase 1b.

The canonical envelope is:
    Event = { event_id, tenant_id, job_id, chain_id?, type, payload, created_at }

Event types are listed in DATA_ARCHITECTURE.md §9.
"""
