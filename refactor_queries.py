import re

def refactor_queries(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Add rdfs prefix to each block if missing
    blocks = content.split('# ==========================================')
    new_blocks = []
    for block in blocks:
        if 'PREFIX' in block and 'PREFIX rdfs:' not in block:
            block = block.replace('PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>', 
                                  'PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>\nPREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>')
        
        # Apply property path replacements
        block = block.replace(':hasName', '(:hasName|rdfs:label)')
        block = block.replace(':hasStop', '(:hasStop|^:Connecting_Line|^:hasLines)')
        block = block.replace(':hasZone', '(:hasZone|:isInFareZone)')
        block = block.replace(':zoneNumber', '(:zoneNumber|rdfs:label)')
        block = block.replace(':belongsToRoute', '(:belongsToRoute|^:hasStopSequence)')
        block = block.replace(':stopSequenceNumber', '(:stopSequenceNumber|:sequence)')
        block = block.replace(':hasTransportMode', '(:hasTransportMode|:mode)')
        
        new_blocks.append(block)

    new_content = '# ========================================== '.join(new_blocks)
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(new_content)
    print(f"Refactored {filepath}")

refactor_queries("Ontology/Sparql_queries.txt")
