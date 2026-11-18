"""MLOps additions (MADT8102 Chapter 07): versioned Feature Store, Training Runs and model artifacts on object storage.

Everything here is ADDITIVE: it reads the Published ER2, writes only under a new object-storage prefix (never overwrites) and
never touches ER1/ER2, KPI formulas, the pipeline, sealed forecasts or the official model-selection logic in `monthly_forecast`.
"""
