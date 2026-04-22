# entity_extraction.py — REMOVED
#
# This file was a leftover from an earlier pipeline design that used a
# regex-based Named Entity Recognition approach (Entity model with .id,
# .mentions, .confidence fields).
#
# The current pipeline uses REBEL (Babelscape/rebel-large) for triplet
# extraction via states/extraction.py. Entity extraction is now implicit
# in the subject/object fields of each Triplet.
#
# DO NOT restore this file without also adding Entity to schemas/entities.py
# and wiring run_entity_extraction into agent.py / states/__init__.py.
