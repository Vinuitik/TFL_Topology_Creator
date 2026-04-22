import subprocess
import yaml
from pathlib import Path

# Config 
BASE_DIR        = Path(__file__).parent.parent
TTL_FILE        = "created_ontology.ttl"
OFN_FILE        = "created_ontology.ofn"
SCHEMA_FILE     = "tfl_template.yaml"
DOCKER_IMAGE    = "robot-owl"


def run(cmd, description):
    print(f"\n>>> {description}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr)
    if result.returncode != 0:
        raise RuntimeError(f"FAILED: {description}")
    print(f"Success: {description}")

def step1_convert_ttl_to_ofn():
    cwd = BASE_DIR.as_posix()
    # On Windows, convert to proper Docker path
    if cwd[1] == ":":
        drive = cwd[0].lower()
        cwd = "/" + drive + cwd[2:].replace("\\", "/")
    
    cmd = (
        f'docker run --rm -v "{cwd}:/data" {DOCKER_IMAGE} convert '
        f'--input {TTL_FILE} --output {OFN_FILE} --format ofn'
    )
    run(cmd, f"Converting {TTL_FILE} → {OFN_FILE} via ROBOT")

def step2_schemauto():
    cmd = f'schemauto import-owl {OFN_FILE}'
    print(f"\n>>> Running schemauto on {OFN_FILE}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    # Write output explicitly as UTF-8 to avoid PowerShell UTF-16 issue
    with open(SCHEMA_FILE, "w", encoding="utf-8") as f:
        f.write(result.stdout)
    print(f"Success: Schema written to {SCHEMA_FILE}")

def step3_fix_header():
    print("\n>>> Fixing schema header")
    with open(SCHEMA_FILE, "r", encoding="utf-8") as f:
        content = f.read()

    content = content.replace("....name: tfl-topology", "name: tfl-topology")
    content = content.replace("....name: None", "name: tfl-topology")
    content = content.replace("name: None", "name: tfl-topology")
    content = content.replace("description: None", "description: TfL Topology Ontology")
    content = content.replace("id: None", "id: https://example.org/tfl-topology")
    content = content.replace("default_prefix: None", "default_prefix: tfl")
    content = content.replace("default_prefix: tfl-topology", "default_prefix: tfl")
    content = content.replace("  None: https://w3id.org/None/", "  tfl: https://example.org/tfl-topology/")
    content = content.replace("  tfl-topology: https://w3id.org/None/", "  tfl: https://example.org/tfl-topology/")

    with open(SCHEMA_FILE, "w", encoding="utf-8") as f:
        f.write(content)
    print("Success: Header fixed")

def step4_fix_hierarchy():
    print("\n>>> Fixing class hierarchy")
    with open(SCHEMA_FILE, "r", encoding="utf-8") as f:
        schema = yaml.safe_load(f)

    # Add Thing as explicit base class
    if "Thing" not in schema["classes"]:
        thing = {"Thing": {
            "description": "Base class for all entities",
            "class_uri": "owl:Thing"
        }}
        schema["classes"] = {**thing, **schema["classes"]}

    # Correct is_a hierarchy
    hierarchy = {
        "TflNetwork":           "Thing",
        "SpatialThing":         "Thing",
        "Route":                "Thing",
        "Fare":                 "Thing",
        "ServiceDisruption":    "Thing",
        "DisruptionCause":      "Thing",
        "ServiceSchedule":      "Thing",
        "TimeWindow":           "Thing",
        "InfrastructureProject":"Thing",
        "TransitAccessPoint":   "SpatialThing",
        "LineSegment":          "SpatialThing",
        "Point":                "SpatialThing",
        "Station":              "TransitAccessPoint",
        "BusStop":              "TransitAccessPoint",
        "Line":                 "Route",
        "BusRoute":             "Route",
        "TrainStation":         "Station",
        "InterchangeStation":   "TrainStation",
        "PeakFare":             "Fare",
        "OffPeakFare":          "Fare",
        "PlannedDisruption":    "ServiceDisruption",
        "UnplannedDisruption":  "ServiceDisruption",
        "SignificantDisruption":"ServiceDisruption",
        "EngineeringWorks":     "DisruptionCause",
        "IndustrialAction":     "DisruptionCause",
        "TechnicalFault":       "DisruptionCause",
        "SignalFailure":        "TechnicalFault",
        "RollingStockIssue":    "TechnicalFault",
        "TwentyFourHourService":"ServiceSchedule",
        "LimitedService":       "ServiceSchedule",
        "NightService":         "ServiceSchedule",
        "PeakPeriod":           "TimeWindow",
        "OffPeakPeriod":        "TimeWindow",
        "StationUpgrade":       "InfrastructureProject",
        "LineExpansion":        "InfrastructureProject",
    }

    # Classes that should have is_a: Thing but aren't in the hierarchy above
    needs_thing = [
        "AccessibilityFeature", "DisruptionStatus", "FareClass",
        "Journey", "ProjectStatus", "RouteStopSequence",
        "StopTime", "TransportMode", "Zone",
    ]

    for class_name, parent in hierarchy.items():
        if class_name in schema["classes"]:
            schema["classes"][class_name]["is_a"] = parent
            schema["classes"][class_name].pop("mixins", None)

    for class_name in needs_thing:
        if class_name in schema["classes"]:
            schema["classes"][class_name]["is_a"] = "Thing"
            schema["classes"][class_name].pop("mixins", None)

    with open(SCHEMA_FILE, "w", encoding="utf-8") as f:
        yaml.dump(schema, f, allow_unicode=True, sort_keys=False)
    print("Success: Hierarchy fixed")

def step5_fix_tree_root():
    print("\n>>> Setting tree_root on TflNetwork")
    with open(SCHEMA_FILE, "r", encoding="utf-8") as f:
        schema = yaml.safe_load(f)

    if "TflNetwork" in schema["classes"]:
        schema["classes"]["TflNetwork"]["tree_root"] = True

    with open(SCHEMA_FILE, "w", encoding="utf-8") as f:
        yaml.dump(schema, f, allow_unicode=True, sort_keys=False)
    print("Success: tree_root set")

def step6_validate():
    print("\n>>> Validating final schema")
    with open(SCHEMA_FILE, "r", encoding="utf-8") as f:
        schema = yaml.safe_load(f)

    errors = []

    # Check header
    for field in ["name", "id", "default_prefix"]:
        if not schema.get(field) or schema[field] in [None, "None"]:
            errors.append(f"Missing or None: {field}")

    # Check Thing exists
    if "Thing" not in schema.get("classes", {}):
        errors.append("Missing base class: Thing")

    # Check tree_root
    tfl = schema.get("classes", {}).get("TflNetwork", {})
    if not tfl.get("tree_root"):
        errors.append("TflNetwork missing tree_root: true")

    # Check all is_a references resolve
    class_names = set(schema.get("classes", {}).keys())
    for class_name, class_def in schema.get("classes", {}).items():
        parent = class_def.get("is_a")
        if parent and parent not in class_names:
            errors.append(f"{class_name} has unknown is_a: {parent}")

    # Check slots exist
    defined_slots = set(schema.get("slots", {}).keys())
    for class_name, class_def in schema.get("classes", {}).items():
        for slot in class_def.get("slots", []):
            if slot not in defined_slots:
                errors.append(f"{class_name} references undefined slot: {slot}")

    if errors:
        print("✗ Validation errors:")
        for e in errors:
            print(f"  - {e}")
        raise RuntimeError("Schema validation failed")
    else:
        print("Success: Schema is valid")

#Run pipeline
if __name__ == "__main__":
    print("=" * 60)
    print("TfL Ontology → LinkML Schema Pipeline")
    print("=" * 60)

    step1_convert_ttl_to_ofn()
    step2_schemauto()
    step3_fix_header()
    step4_fix_hierarchy()
    step5_fix_tree_root()
    step6_validate()

    print("\n" + "=" * 60)
    print(f"Success: Pipeline complete. Schema ready at: {SCHEMA_FILE}")
    print("=" * 60)