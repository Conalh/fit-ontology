"""FastAPI route modules.

Each file exposes an ``APIRouter`` named ``router`` that the app
factory in ``fit_ontology.api`` mounts. Routes are grouped by the
ontology surface they read or write, not by HTTP verb — so the
calibration view and its tuning-suggestion rules live together,
even though one is a GET and the others are pure functions.
"""
