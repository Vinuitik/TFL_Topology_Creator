from rdflib import Graph, URIRef, Literal, Namespace, BNode
from rdflib.namespace import RDF, RDFS, OWL, XSD
from rdflib.collection import Collection

# Create graph
g = Graph()

ontology_iri = URIRef("https://example.org/tfl-topology")
g.add((ontology_iri, RDF.type, OWL.Ontology))
g.add((ontology_iri, RDFS.label, Literal("TfL Topology")))
g.add((ontology_iri, RDFS.comment, Literal("Ontology for TfL network topology")))

# Define namespace
EX = Namespace("http://example.org/tfl#")
g.bind("ex", EX)

classes = [
    # Root
    (EX.TflNetwork, "TfL Network", "Top-level container for the TfL topology knowledge graph."),
    
    # Core Infrastructure & Journey
    (EX.AccessibilityFeature, "Accessibility Feature", "Physical features or services providing access (e.g., step-free access)."),
    (EX.FareClass, "Fare Class", "The category of fare applicable to a journey."),
    (EX.Journey, "Journey", "A specific instance of travel from an origin to a destination."),
    (EX.Route, "Route", "A path or course followed by a public transport service."),
    (EX.Line, "Line", "A named transport line, such as a specific Tube or DLR line."),
    (EX.BusRoute, "Bus Route", "A specific numbered route followed by a bus service."),
    (EX.RouteStopSequence, "Route Stop Sequence", "The ordered list of stops that define a specific route."),
    (EX.SpatialThing, "Spatial Thing", "Anything with a physical location or spatial extent."),
    (EX.StopTime, "Stop Time", "The scheduled arrival or departure time at a specific stop."),
    (EX.TransportMode, "Transport Mode", "The type of vehicle used (e.g., Tube, Bus, DLR)."),
    
    # Fares & Zones
    (EX.Zone, "Zone", "A geographic area used for fare calculation."),
    (EX.Fare, "Fare", "The cost associated with a journey."),
    (EX.PeakFare, "Peak Fare", "Higher pricing applied during high-demand morning and evening periods."),
    (EX.OffPeakFare, "Off-Peak Fare", "Discounted pricing applied during lower-demand periods."),
    
    # Spatial & Stations
    (EX.LineSegment, "Line Segment", "A specific portion of a transport line between two points."),
    (EX.Point, "Point", "A specific geographic coordinate."),
    (EX.TransitAccessPoint, "Transit Access Point", "A physical location where passengers enter or exit the system."),
    (EX.Station, "Station", "A designated stopping place for trains."),
    (EX.TrainStation, "Train Station", "A station specifically for heavy or light rail services."),
    (EX.BusStop, "Bus Stop", "A designated place where buses stop for passengers."),
    (EX.InterchangeStation, "Interchange Station", "A station where passengers can switch between different lines."),
    
    # Disruptions
    (EX.ServiceDisruption, "Service Disruption", "An event that interferes with normal operation."),
    (EX.PlannedDisruption, "Planned Disruption", "A disruption scheduled in advance, like maintenance."),
    (EX.UnplannedDisruption, "Unplanned Disruption", "An unexpected disruption, like a technical fault."),
    (EX.SignificantDisruption, "Significant Disruption", "A major event causing widespread impact over time."),
    (EX.DisruptionCause, "Disruption Cause", "The underlying reason for a service disruption."),
    (EX.EngineeringWorks, "Engineering Works", "Planned maintenance or construction on infrastructure."),
    (EX.IndustrialAction, "Industrial Action", "Strikes or labor-related service withdrawals."),
    (EX.TechnicalFault, "Technical Fault", "Mechanical or electronic equipment failure."),
    (EX.SignalFailure, "Signal Failure", "A specific technical fault in the signaling system."),
    (EX.RollingStockIssue, "Rolling Stock Issue", "Mechanical problems with the vehicles (trains/buses)."),
    (EX.DisruptionStatus, "Disruption Status", "The operational state of a line (e.g., Severe Delays)."),
    
    # Schedules & Times
    (EX.ServiceSchedule, "Service Schedule", "The timeframe and frequency under which a transport service operates."),
    (EX.TwentyFourHourService, "24-Hour Service", "A service that operates continuously throughout a 24-hour period (e.g., Night Tube, 24-hour buses)."),
    (EX.LimitedService, "Limited Service", "A service with restricted operating hours, such as daytime-only or peak-hour only services."),
    (EX.NightService, "Night Service", "A specific service pattern that operates during late-night and early-morning hours."),
    (EX.TimeWindow, "Time Window", "A defined period of time during the day used for scheduling or fare calculation."),
    (EX.PeakPeriod, "Peak Period", "High-demand travel times (e.g., morning and evening rush hours) where higher fares often apply."),
    (EX.OffPeakPeriod, "Off-Peak Period", "Lower-demand travel times where discounted fares typically apply."),
    
    # Infrastructure Projects
    (EX.InfrastructureProject, "Infrastructure Project", "A planned endeavor to improve or expand the transport network."),
    (EX.StationUpgrade, "Station Upgrade", "Improvements to existing stations, such as adding step-free access or increasing capacity."),
    (EX.LineExpansion, "Line Expansion", "The construction of new tracks or the extension of an existing line to new areas."),
    (EX.ProjectStatus, "Project Status", "The current stage of a project (e.g., Proposed, Under Construction, Completed).")
]

for cls, label, comment in classes:
    g.add((cls, RDF.type, OWL.Class))
    g.add((cls, RDFS.label, Literal(label)))
    g.add((cls, RDFS.comment, Literal(comment)))
    g.add((cls, RDFS.subClassOf, OWL.Thing))

# --- Class Hierarchy ---
g.add((EX.LineSegment, RDFS.subClassOf, EX.SpatialThing))
g.add((EX.TransitAccessPoint, RDFS.subClassOf, EX.SpatialThing))

g.add((EX.Station, RDFS.subClassOf, EX.TransitAccessPoint)) 
g.add((EX.BusStop, RDFS.subClassOf, EX.TransitAccessPoint)) 
g.add((EX.TrainStation, RDFS.subClassOf, EX.Station))
g.add((EX.InterchangeStation, RDFS.subClassOf, EX.TrainStation))

# 2. Routes
g.add((EX.Line, RDFS.subClassOf, EX.Route)) 
g.add((EX.BusRoute, RDFS.subClassOf, EX.Route)) 

# 3. Fares
g.add((EX.PeakFare, RDFS.subClassOf, EX.Fare))
g.add((EX.OffPeakFare, RDFS.subClassOf, EX.Fare))

# 4. Disruptions
g.add((EX.PlannedDisruption, RDFS.subClassOf, EX.ServiceDisruption))
g.add((EX.UnplannedDisruption, RDFS.subClassOf, EX.ServiceDisruption))
g.add((EX.SignificantDisruption, RDFS.subClassOf, EX.ServiceDisruption))

# 5. Disruption Causes
g.add((EX.EngineeringWorks, RDFS.subClassOf, EX.DisruptionCause))
g.add((EX.IndustrialAction, RDFS.subClassOf, EX.DisruptionCause))
g.add((EX.TechnicalFault, RDFS.subClassOf, EX.DisruptionCause))
g.add((EX.SignalFailure, RDFS.subClassOf, EX.TechnicalFault))
g.add((EX.RollingStockIssue, RDFS.subClassOf, EX.TechnicalFault))

# 6. Schedules & Time Windows
g.add((EX.TwentyFourHourService, RDFS.subClassOf, EX.ServiceSchedule))
g.add((EX.LimitedService, RDFS.subClassOf, EX.ServiceSchedule))
g.add((EX.NightService, RDFS.subClassOf, EX.ServiceSchedule))

g.add((EX.PeakPeriod, RDFS.subClassOf, EX.TimeWindow))
g.add((EX.OffPeakPeriod, RDFS.subClassOf, EX.TimeWindow))

# 7. Infrastructure Projects
g.add((EX.StationUpgrade, RDFS.subClassOf, EX.InfrastructureProject))
g.add((EX.LineExpansion, RDFS.subClassOf, EX.InfrastructureProject))


# --- Status Individuals ---
statuses = [
    (EX.GoodService, "Good Service"),
    (EX.MinorDelays, "Minor Delays"),
    (EX.SevereDelays, "Severe Delays"),
    (EX.PartSuspended, "Part Suspended")
]
for status, label in statuses:
    g.add((status, RDF.type, EX.DisruptionStatus))
    g.add((status, RDFS.label, Literal(label)))

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
    EX.RouteStopSequence,
    EX.ServiceDisruption,
    EX.DisruptionCause,
    EX.DisruptionStatus,
    EX.ServiceSchedule,
    EX.TimeWindow,
    EX.InfrastructureProject,
    EX.ProjectStatus
])
g.add((disjoint_node, OWL.members, disjoint_list_node))

# --- Object Properties ---
tfl_network_properties = [
    (EX.hasSpatialEntity, "has spatial entity", "Links the TfL network to its spatial components.", EX.TflNetwork, EX.SpatialThing, OWL.ObjectProperty),
    (EX.hasRoute, "has route", "Links the TfL network to its routes.", EX.TflNetwork, EX.Route, OWL.ObjectProperty),
    (EX.hasDisruption, "has disruption", "Links the TfL network to its service disruptions.", EX.TflNetwork, EX.ServiceDisruption, OWL.ObjectProperty),
    (EX.hasFareType, "has fare type", "Links the TfL network to its fare structures.", EX.TflNetwork, EX.Fare, OWL.ObjectProperty),
    (EX.hasSchedule, "has schedule", "Links the TfL network to its service schedules.", EX.TflNetwork, EX.ServiceSchedule, OWL.ObjectProperty),
    (EX.hasTimeWindow, "has time window", "Links the TfL network to its time windows.", EX.TflNetwork, EX.TimeWindow, OWL.ObjectProperty),
    (EX.hasProject, "has project", "Links the TfL network to its infrastructure projects.", EX.TflNetwork, EX.InfrastructureProject, OWL.ObjectProperty),
]

properties = tfl_network_properties + [
    (EX.belongsToRoute, "belongs to route", "Links a sequence of stops to the specific route they define.", EX.RouteStopSequence, EX.Route, OWL.ObjectProperty),
    (EX.directlyConnectedTo, "directly connected to", "Indicates a direct connection between two transit access points (e.g., adjacent stations).", EX.TransitAccessPoint, EX.TransitAccessPoint, [OWL.ObjectProperty, OWL.SymmetricProperty]),
    (EX.endPoint, "end point", "The final station or stop of a specific journey.", EX.Journey, EX.TransitAccessPoint, OWL.ObjectProperty),
    (EX.endZone, "end zone", "The fare zone where a journey concludes.", EX.Journey, EX.Zone, OWL.ObjectProperty),
    (EX.hasFare, "has fare", "Links a journey to the applicable fare object.", EX.Journey, EX.Fare, OWL.ObjectProperty),
    (EX.hasStop, "has stop", "Links a route to the stations or stops that it serves.", EX.Route, EX.TransitAccessPoint, OWL.ObjectProperty),
    (EX.hasTransportMode, "has transport mode", "Indicates the mode of transport available at an access point (e.g., Tube, Bus).", EX.TransitAccessPoint, EX.TransportMode, OWL.ObjectProperty),
    (EX.hasZone, "has zone", "Assigns a geographic fare zone to a station or stop.", EX.TransitAccessPoint, EX.Zone, OWL.ObjectProperty),
    (EX.offersAccessibilityFeature, "offers accessibility feature", "Links a station to its available accessibility services (e.g., elevators).", EX.TransitAccessPoint, EX.AccessibilityFeature, OWL.ObjectProperty),
    (EX.sequenceStop, "sequence stop", "Links a specific position in a route sequence to a transit stop.", EX.RouteStopSequence, EX.TransitAccessPoint, OWL.ObjectProperty),
    (EX.servedByRoute, "served by route", "Links a station or stop to the routes that pass through it.", EX.TransitAccessPoint, EX.Route, OWL.ObjectProperty),
    (EX.startPoint, "start point", "The station or stop where a journey begins.", EX.Journey, EX.TransitAccessPoint, OWL.ObjectProperty),
    (EX.startZone, "start zone", "The fare zone where a journey begins.", EX.Journey, EX.Zone, OWL.ObjectProperty),
    (EX.hasStartPoint, "has start point", "The beginning point of a specific line segment.", EX.LineSegment, EX.TransitAccessPoint, OWL.ObjectProperty),
    (EX.hasEndPoint, "has end point", "The ending point of a specific line segment.", EX.LineSegment, EX.TransitAccessPoint, OWL.ObjectProperty),
    (EX.onRoute, "on route", "Links a line segment to its parent route.", EX.LineSegment, EX.Route, OWL.ObjectProperty),
    (EX.reachableFrom, "reachable from", "Indicates a station can be reached from another, potentially across multiple segments.", EX.TransitAccessPoint, EX.TransitAccessPoint, [OWL.ObjectProperty, OWL.TransitiveProperty]),
    (EX.affectsRoute, "affects route", "Links a service disruption to the specific route it is impacting.", EX.ServiceDisruption, EX.Route, OWL.ObjectProperty),
    (EX.affectsStop, "affects stop", "Links a service disruption to a specific station or stop.", EX.ServiceDisruption, EX.TransitAccessPoint, OWL.ObjectProperty),
    (EX.hasCause, "has cause", "The underlying reason for a disruption (e.g., strike, fault).", EX.ServiceDisruption, EX.DisruptionCause, OWL.ObjectProperty),
    (EX.hasStatus, "has status", "The current operational status of the service during a disruption.", EX.ServiceDisruption, EX.DisruptionStatus, OWL.ObjectProperty),
    (EX.hasSeverity, "has severity", "The scale of impact a disruption has on the network.", EX.ServiceDisruption, None, OWL.ObjectProperty),
    (EX.disruptionDate, "disruption date", "The date and time when a disruption event occurred.", EX.ServiceDisruption, XSD.dateTime, OWL.DatatypeProperty),
    (EX.hasScheduleType, "has schedule type", "Links a route or line to its operating schedule category (e.g., 24-hour or Limited).", EX.Route, EX.ServiceSchedule, OWL.ObjectProperty),
    (EX.appliesDuring, "applies during", "Links a fare or a service restriction to a specific time window.", [EX.Fare, EX.Route], EX.TimeWindow, OWL.ObjectProperty),
    (EX.hasPeakPeriod, "has peak period", "Links a station or line to its specific peak demand window.", [EX.Station, EX.Route], EX.PeakPeriod, OWL.ObjectProperty),
    (EX.hasOffPeakPeriod, "has off-peak period", "Links a station or line to its specific off-peak window.", [EX.Station, EX.Route], EX.OffPeakPeriod, OWL.ObjectProperty),
    (EX.targetsInfrastructure, "targets infrastructure", "Links a project to the specific station or line being improved.", EX.InfrastructureProject, [EX.Station, EX.Route], OWL.ObjectProperty),
    (EX.hasProjectStatus, "has project status", "Indicates the current lifecycle stage of an infrastructure project.", EX.InfrastructureProject, EX.ProjectStatus, OWL.ObjectProperty),
    (EX.openingDate, "opening date", "The historical date a line or station first opened to the public.", [EX.Line, EX.Station], XSD.date, OWL.DatatypeProperty),
]

for prop, label, comment, domain, range_type, p_type in properties:

    if isinstance(p_type, list):
        for t in p_type:
            g.add((prop, RDF.type, t))
    else:
        g.add((prop, RDF.type, p_type))

    g.add((prop, RDFS.label, Literal(label)))
    g.add((prop, RDFS.comment, Literal(comment)))

    if domain:
        if isinstance(domain, list):
            union_node = BNode()
            g.add((union_node, RDF.type, OWL.Class))
            list_node = BNode()
            Collection(g, list_node, domain)
            g.add((union_node, OWL.unionOf, list_node))
            g.add((prop, RDFS.domain, union_node))
        else:
            g.add((prop, RDFS.domain, domain))

    if range_type:
        if isinstance(range_type, list):
            union_node = BNode()
            g.add((union_node, RDF.type, OWL.Class))
            list_node = BNode()
            Collection(g, list_node, range_type)
            g.add((union_node, OWL.unionOf, list_node))
            g.add((prop, RDFS.range, union_node))
        else:
            g.add((prop, RDFS.range, range_type))

# --- Data Properties ---
datatype_properties = [
    (EX.fareCost, "fare cost", "The monetary price of a fare.", EX.Fare, XSD.decimal, OWL.DatatypeProperty),
    (EX.hasName, "has name", "the human-readable name of an entity (e.g., station name, line name).", None, XSD.string, OWL.DatatypeProperty),
    (EX.latitude, "latitude", "The geographic latitude coordinate of a transit point.", EX.TransitAccessPoint, XSD.decimal, OWL.DatatypeProperty),
    (EX.longitude, "longitude", "The geographic longitude coordinate of a transit point.", EX.TransitAccessPoint, XSD.decimal, OWL.DatatypeProperty),
    (EX.stopSequenceNumber, "stop sequence number", "The numerical order of a stop within a route.", EX.RouteStopSequence, XSD.integer, OWL.DatatypeProperty),
    (EX.zoneNumber, "zone number", "The identifying number of a fare zone.", EX.Zone, XSD.integer, OWL.DatatypeProperty),
    (EX.disruptionDate, "disruption date", "The date and time when a service disruption occurred.", EX.ServiceDisruption, XSD.dateTime, OWL.DatatypeProperty),
    (EX.operationStartTime, "operation start time", "The time a service begins daily operations.", EX.Route, XSD.time, OWL.DatatypeProperty),
    (EX.operationEndTime, "operation end time", "The time a service ends daily operations.", EX.Route, XSD.time, OWL.DatatypeProperty),
    (EX.isNightService, "is night service", "Indicates if the service is a night-specific variant (e.g., Night Tube).", EX.Route, XSD.boolean, OWL.DatatypeProperty),
    (EX.operatingDays, "operating days", "Textual description of the days the service is active (e.g., 'Mon-Fri').", EX.Route, XSD.string, OWL.DatatypeProperty),
    (EX.startTime, "start time", "The beginning of a time window.", EX.TimeWindow, XSD.time, OWL.DatatypeProperty),
    (EX.endTime, "end time", "The conclusion of a time window.", EX.TimeWindow, XSD.time, OWL.DatatypeProperty),
    (EX.isApplicableOnWeekends, "is applicable on weekends", "Indicates if the time window or fare applies on Saturdays and Sundays.", EX.TimeWindow, XSD.boolean, OWL.DatatypeProperty),
    (EX.expectedCompletionDate, "expected completion date", "The anticipated date when the upgrade or expansion will be finished.", EX.InfrastructureProject, XSD.date, OWL.DatatypeProperty),
    (EX.projectBudget, "project budget", "The estimated financial cost of the infrastructure project.", EX.InfrastructureProject, XSD.decimal, OWL.DatatypeProperty),
    (EX.isPubliclyFunded, "is publicly funded", "Indicates if the project is financed by government or public taxes.", EX.InfrastructureProject, XSD.boolean, OWL.DatatypeProperty)
]

for prop, label, comment, domain, range_type, p_type in datatype_properties:
    g.add((prop, RDF.type, p_type))
    g.add((prop, RDFS.label, Literal(label)))
    g.add((prop, RDFS.comment, Literal(comment)))
    
    if domain:
        g.add((prop, RDFS.domain, domain))
    if range_type:
        g.add((prop, RDFS.range, range_type))

# --- Individuals ---

# --- Relationships ---


# --- Data values ---




# --- Save as TTL ---
g.serialize(destination="created_ontology.ttl", format="turtle")