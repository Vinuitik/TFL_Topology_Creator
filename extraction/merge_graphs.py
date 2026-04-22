from pathlib import Path
from rdflib import Graph, URIRef
from rdflib.namespace import OWL, RDF

#Config
BASE_DIR         = Path(__file__).parent
OUTPUTS_DIR      = BASE_DIR / "outputs"
ONTOLOGY_TTL     = BASE_DIR.parent / "created_ontology.ttl"
MERGED_OUTPUT    = BASE_DIR.parent / "knowledge_graph.ttl"
ONTOLOGY_IRI     = URIRef("https://example.org/tfl-topology")


def merge_graphs():
    #base ontology (schema + class definitions)
    print("Loading base ontology...")
    merged = Graph()
    merged.parse(ONTOLOGY_TTL, format="turtle")
    base_triples = len(merged)
    print(f"  Success, Base ontology: {base_triples} triples")

    # Find all extracted TTL files
    extracted_files = list(OUTPUTS_DIR.glob("*.ttl"))
    if not extracted_files:
        print(f"No .ttl files found in {OUTPUTS_DIR}")
        return

    # Merge each extracted graph in
    for ttl_file in extracted_files:
        print(f"  Merging: {ttl_file.name}")
        try:
            g = Graph()
            g.parse(ttl_file, format="turtle")

            # Copy all triples into merged graph
            for triple in g:
                merged.add(triple)

            # Copy namespace bindings
            for prefix, namespace in g.namespaces():
                merged.bind(prefix, namespace)

            print(f"    Success: +{len(g)} triples")
        except Exception as e:
            print(f"     Failed to parse {ttl_file.name}: {e}")

    # Deduplicate by re-serialising (rdflib handles this automatically
    # since graphs are sets of triples)
    total = len(merged)
    print(f"\nTotal triples after merge: {total} (+{total - base_triples} from extraction)")

    # Save
    merged.serialize(destination=str(MERGED_OUTPUT), format="turtle")
    print(f"Success: Knowledge graph saved to {MERGED_OUTPUT}")


if __name__ == "__main__":
    merge_graphs()