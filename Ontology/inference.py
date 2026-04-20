from owlready2 import *
import rdflib
import io

g = rdflib.Graph()
g.parse("final_ontology.ttl", format="turtle")

rdfxml_buffer = io.BytesIO()
g.serialize(destination=rdfxml_buffer, format="xml")
rdfxml_buffer.seek(0)

world = World()
onto = world.get_ontology("http://example.org/tfl").load(fileobj=rdfxml_buffer)

with onto:
    class TransitAccessPoint(Thing): pass
    class LineSegment(Thing): pass
    class Route(Thing): pass

    class hasStartPoint(LineSegment >> TransitAccessPoint, FunctionalProperty): pass
    class hasEndPoint(LineSegment >> TransitAccessPoint, FunctionalProperty): pass
    class onRoute(LineSegment >> Route): pass

    class isStartPointOf(TransitAccessPoint >> LineSegment): pass
    hasStartPoint.inverse_property = isStartPointOf

    class reachableFrom(TransitAccessPoint >> TransitAccessPoint, TransitiveProperty): pass

    reachableFrom.property_chain = [PropertyChain([isStartPointOf, hasEndPoint])]

sync_reasoner_hermit(world, infer_property_values=True)


graph = world.as_rdflib_graph()
graph.serialize(destination="inferred_ontology.ttl", format="turtle")

print("Done. Output written to inferred_ontology.ttl")