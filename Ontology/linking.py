from rdflib import Graph, Namespace, RDFS, OWL

g = Graph()
g.parse("KE_CW2_Ontology.ttl", format="turtle")

LOCAL = Namespace("http://example.org/tfl#")
EXT = Namespace("http://vocab.gtfs.org/terms#")

g.bind("local", LOCAL)
g.bind("gtfs", EXT)

g.add((LOCAL.Stop, RDFS.subClassOf, EXT.Stop))
g.add((LOCAL.TrainStation, RDFS.subClassOf, LOCAL.Stop))
g.add((LOCAL.BusStop, RDFS.subClassOf, LOCAL.Stop))
g.add((LOCAL.TrainStation, RDFS.subClassOf, EXT.Station))
g.add((LOCAL.Zone, RDFS.equivalentClassOf, EXT.Zone))

g.add((LOCAL.Line, RDFS.subClassOf, EXT.Route))
g.add((LOCAL.Route, RDFS.subClassOf, EXT.Route))

g.add((LOCAL.servesLine, RDFS.subPropertyOf, EXT.route))
g.add((LOCAL.locatedInZone, OWL.equivalentProperty, EXT.zone))

g.add((LOCAL.startStation, RDFS.subPropertyOf, EXT.originStop))
g.add((LOCAL.endStation, RDFS.subPropertyOf, EXT.destinationStop))

g.serialize("final_ontology.ttl", format="turtle")