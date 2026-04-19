from rdflib import Graph, Namespace, RDFS, OWL
from rdflib.namespace import RDF
g = Graph()
g.parse("KE_CW2_Ontology.ttl", format="turtle")

LOCAL = Namespace("http://example.org/tfl#")
EXT = Namespace("http://vocab.gtfs.org/terms#")

g.bind("local", LOCAL)
g.bind("gtfs", EXT)

g.add((LOCAL.Zone, RDF.type, OWL.Class))
g.add((EXT.Zone, RDF.type, OWL.Class))

g.add((LOCAL.locatedInZone, RDF.type, OWL.ObjectProperty))
g.add((EXT.zone, RDF.type, OWL.ObjectProperty))

g.add((LOCAL.TransitAccessPoint, RDFS.subClassOf, LOCAL.Stop))
g.add((LOCAL.Zone, OWL.equivalentClass, EXT.Zone))

g.add((LOCAL.Line, RDFS.subClassOf, EXT.Route))
g.add((LOCAL.Route, RDFS.subClassOf, EXT.Route))

g.add((LOCAL.servesLine, RDFS.subPropertyOf, EXT.route))
g.add((LOCAL.locatedInZone, OWL.equivalentProperty, EXT.zone))

g.add((LOCAL.startStation, RDFS.subPropertyOf, EXT.originStop))
g.add((LOCAL.endStation, RDFS.subPropertyOf, EXT.destinationStop))

g.serialize("final_ontology.ttl", format="turtle")