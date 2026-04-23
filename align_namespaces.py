import os

def align_namespaces(filepath):
    if not os.path.exists(filepath):
        print(f"File not found: {filepath}")
        return
    
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Replace ns1: with local:
    new_content = content.replace('ns1:', 'local:')
    # Replace @prefix ns1: with @prefix local:
    new_content = new_content.replace('@prefix ns1:', '@prefix local:')
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(new_content)
    print(f"Aligned namespaces in {filepath}")

align_namespaces("final_clean.ttl")
align_namespaces("outputs/final.ttl")
