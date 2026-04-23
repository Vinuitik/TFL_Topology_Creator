import logging
import time
from functools import wraps
from typing import Callable

from .coreference_resolution import run_coreference_resolution
from .entity_classification import run_entity_classification
from .entity_linking import run_entity_linking
from .extraction import run_extraction
from .feedback_router import route_after_validation
from .input_ingestion import run_input_ingestion
from .ontology_construction import run_ontology_construction
from .preprocessing import run_preprocessing
from .reasoning import run_reasoning
from .schema_mapping import run_schema_mapping
from .text_normalization import run_text_normalization
from .turtle_serialization import run_turtle_serialization
from .validation import run_validation

log = logging.getLogger(__name__)


def timed_node(name: str) -> Callable:
    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(state):
            t0 = time.monotonic()
            result = fn(state)
            elapsed = time.monotonic() - t0
            log.info("STAGE %s elapsed=%.2fs", name, elapsed)
            existing = state.get("timings", {})
            update = dict(result) if result else {}
            update["timings"] = {**existing, name: elapsed}
            return update
        return wrapper
    return decorator


run_input_ingestion = timed_node("input_ingestion")(run_input_ingestion)
run_preprocessing = timed_node("preprocessing")(run_preprocessing)
run_text_normalization = timed_node("text_normalization")(run_text_normalization)
run_coreference_resolution = timed_node("coreference_resolution")(run_coreference_resolution)
run_extraction = timed_node("extraction")(run_extraction)
run_entity_linking = timed_node("entity_linking")(run_entity_linking)
run_entity_classification = timed_node("entity_classification")(run_entity_classification)
run_schema_mapping = timed_node("schema_mapping")(run_schema_mapping)
run_ontology_construction = timed_node("ontology_construction")(run_ontology_construction)
run_reasoning = timed_node("reasoning")(run_reasoning)
run_validation = timed_node("validation")(run_validation)
run_turtle_serialization = timed_node("turtle_serialization")(run_turtle_serialization)

__all__ = [
    "run_input_ingestion",
    "run_preprocessing",
    "run_text_normalization",
    "run_coreference_resolution",
    "run_extraction",
    "run_entity_linking",
    "run_entity_classification",
    "run_schema_mapping",
    "run_ontology_construction",
    "run_reasoning",
    "run_validation",
    "run_turtle_serialization",
    "route_after_validation",
]
