from rdflib import Graph, Namespace, RDF, RDFS, OWL, Literal, XSD, BNode
from rdflib.collection import Collection

# Create graph
g = Graph()

# Define namespace
EX = Namespace("http://example.org/tfl#")
g.bind("ex", EX)

# --- Classes ---
g.add((EX.AccessibilityFeature, RDF.type, OWL.Class))

g.add((EX.FareClass, RDF.type, OWL.Class))

g.add((EX.Journey, RDF.type, OWL.Class))

g.add((EX.Route, RDF.type, OWL.Class))

g.add((EX.RouteStopSequence, RDF.type, OWL.Class))

g.add((EX.SpatialThing, RDF.type, OWL.Class))

g.add((EX.Station, RDF.type, OWL.Class))

g.add((EX.TransitAccessPoint, RDF.type, OWL.Class))

g.add((EX.StopTime, RDF.type, OWL.Class))

g.add((EX.TransportMode, RDF.type, OWL.Class))

g.add((EX.Zone, RDF.type, OWL.Class))

g.add((EX.Fare, RDF.type, OWL.Class))

g.add((EX.PeakFare, RDF.type, OWL.Class))
g.add((EX.PeakFare, RDFS.subClassOf, EX.Fare))

g.add((EX.OffPeakFare, RDF.type, OWL.Class))
g.add((EX.OffPeakFare, RDFS.subClassOf, EX.Fare))

g.add((EX.Line, RDF.type, OWL.Class))
g.add((EX.Line, RDFS.subClassOf, EX.Route))

g.add((EX.Point, RDF.type, OWL.Class))

g.add((EX.TrainStation, RDF.type, OWL.Class))
g.add((EX.TrainStation, RDFS.subClassOf, EX.TransitAccessPoint))

g.add((EX.BusStop, RDF.type, OWL.Class))
g.add((EX.BusStop, RDFS.subClassOf, EX.TransitAccessPoint))

g.add((EX.InterchangeStation, RDF.type, OWL.Class))
g.add((EX.InterchangeStation, RDFS.subClassOf, EX.TrainStation))

# --- Disjoint Classes ---
disjoint_node = BNode()
g.add((disjoint_node, RDF.type, OWL.AllDisjointClasses))
disjoint_list_node = BNode()
Collection(g, disjoint_list_node, [
    EX.TransitAccessPoint,
    EX.Zone,
    EX.TransportMode,
    EX.Journey,
    EX.AccessibilityFeature,
    EX.Fare,
    EX.Route,
    EX.RouteStopSequence
])
g.add((disjoint_node, OWL.members, disjoint_list_node))




# --- Object Properties ---
g.add((EX.belongsToRoute, RDF.type, OWL.ObjectProperty))
g.add((EX.belongsToRoute, RDFS.domain, EX.RouteStopSequence))
g.add((EX.belongsToRoute, RDFS.range, EX.Route))

g.add((EX.connectionLine, RDF.type, OWL.ObjectProperty))
g.add((EX.connectionLine, RDFS.domain, EX.TrainStation))
g.add((EX.connectionLine, RDFS.range, EX.Line))

g.add((EX.directlyConnectedTo, RDF.type, OWL.ObjectProperty))
g.add((EX.directlyConnectedTo, RDFS.domain, EX.TrainStation))
g.add((EX.directlyConnectedTo, RDFS.range, EX.TrainStation))

g.add((EX.endStation, RDF.type, OWL.ObjectProperty))
g.add((EX.endStation, RDFS.domain, EX.Journey))
g.add((EX.endStation, RDFS.range, EX.TrainStation))

g.add((EX.endZone, RDF.type, OWL.ObjectProperty))
g.add((EX.endZone, RDFS.domain, EX.Journey))
g.add((EX.endZone, RDFS.range, EX.Zone))

g.add((EX.hasFare, RDF.type, OWL.ObjectProperty))
g.add((EX.hasFare, RDFS.domain, EX.Journey))
g.add((EX.hasFare, RDFS.range, EX.Fare))

g.add((EX.hasStop, RDF.type, OWL.ObjectProperty))
g.add((EX.hasStop, RDFS.domain, EX.Route))
g.add((EX.hasStop, RDFS.domain, EX.Line))
g.add((EX.hasStop, RDFS.range, EX.TransitAccessPoint))

g.add((EX.hasTransportMode, RDF.type, OWL.ObjectProperty))
g.add((EX.hasTransportMode, RDFS.domain, EX.TransitAccessPoint))
g.add((EX.hasTransportMode, RDFS.range, EX.TransportMode))

g.add((EX.hasZone, RDF.type, OWL.ObjectProperty))
g.add((EX.hasZone, RDFS.domain, EX.TrainStation))
g.add((EX.hasZone, RDFS.range, EX.Zone))

g.add((EX.offersAccessibilityFeature, RDF.type, OWL.ObjectProperty))
g.add((EX.offersAccessibilityFeature, RDFS.domain, EX.TrainStation))
g.add((EX.offersAccessibilityFeature, RDFS.range, EX.AccessibilityFeature))

g.add((EX.providesService, RDF.type, OWL.ObjectProperty))
g.add((EX.providesService, RDFS.domain, EX.TrainStation))
g.add((EX.providesService, RDFS.range, EX.Line))

g.add((EX.sequenceStop, RDF.type, OWL.ObjectProperty))
g.add((EX.sequenceStop, RDFS.domain, EX.RouteStopSequence))
g.add((EX.sequenceStop, RDFS.range, EX.TransitAccessPoint))

g.add((EX.servedByLine, RDF.type, OWL.ObjectProperty))
g.add((EX.servedByLine, RDFS.domain, EX.TrainStation))
g.add((EX.servedByLine, RDFS.range, EX.Line))

g.add((EX.startStation, RDF.type, OWL.ObjectProperty))
g.add((EX.startStation, RDFS.domain, EX.Journey))
g.add((EX.startStation, RDFS.range, EX.TrainStation))

g.add((EX.startZone, RDF.type, OWL.ObjectProperty))
g.add((EX.startZone, RDFS.domain, EX.TrainStation))
g.add((EX.startZone, RDFS.range, EX.Zone))


# --- Data Properties ---
g.add((EX.fareCost, RDF.type, OWL.DatatypeProperty))
g.add((EX.fareCost, RDFS.domain, EX.Fare))
g.add((EX.fareCost, RDFS.range, XSD.decimal))

g.add((EX.hasName, RDF.type, OWL.DatatypeProperty))
g.add((EX.hasName, RDFS.range, XSD.string))

g.add((EX.latitude, RDF.type, OWL.DatatypeProperty))
g.add((EX.latitude, RDFS.domain, EX.TransitAccessPoint))
g.add((EX.latitude, RDFS.range, XSD.decimal))

g.add((EX.longitude, RDF.type, OWL.DatatypeProperty))
g.add((EX.longitude, RDFS.domain, EX.TransitAccessPoint))
g.add((EX.longitude, RDFS.range, XSD.decimal))

g.add((EX.stopSequenceNumber, RDF.type, OWL.DatatypeProperty))
g.add((EX.stopSequenceNumber, RDFS.domain, EX.RouteStopSequence))
g.add((EX.stopSequenceNumber, RDFS.range, XSD.integer))

g.add((EX.zoneNumber, RDF.type, OWL.DatatypeProperty))
g.add((EX.zoneNumber, RDFS.domain, EX.Zone))
g.add((EX.zoneNumber, RDFS.range, XSD.integer))


# --- Individuals ---

# --- Relationships ---


# --- Data values ---




# --- Save as TTL ---
g.serialize(destination="created_ontology.ttl", format="turtle")