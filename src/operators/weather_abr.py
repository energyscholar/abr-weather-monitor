"""
weather_abr.py — V4 ABR Operator Application
ABR Weather Station Monitor — Phase 1

Applies V4 ABR kernel (A → B → R → E) to declared fields
per timestep. Computes diagnostics: sigma_sq per topology,
Gamma (R-sustained circulation).

Operator topologies (internal to E):
  Spatial:   proximity graph on stations (symmetric)
  Component: all-pairs on 6 components (symmetric)

Observational evolution ordering (NOT an operator topology):
  Temporal:  forward-only succession of hourly snapshots

Metatron Dynamics, Inc.
"""
# Phase 1 build