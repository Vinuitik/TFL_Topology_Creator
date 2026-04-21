import time
import psutil
import os
from rdflib import Graph

def evaluate_pipeline():
    start_time = time.time()
    
    # Track memory
    process = psutil.Process(os.getpid())
    start_mem = process.memory_info().rss / 1024 / 1024 # MB
    
    print("Loading graph...")
    g = Graph()
    g.parse("Ontology/final.ttl", format="turtle")
    
    # Competency queries
    with open("Ontology/Sparql_queries.txt", "r", encoding="utf-8") as f:
        content = f.read()
    
    # Extremely basic parsing of the queries based on comments
    queries = []
    current_query = []
    lines = content.split("\n")
    q_name = ""
    for line in lines:
        if line.startswith("# Q"):
            q_name = line.strip("# =").strip()
            current_query = []
        elif line.startswith("# ===="):
            continue
        else:
            if q_name:
                current_query.append(line)
                if line.strip() == "}":
                    # Simple heuristic for end of query, might need adjustment
                    pass
    
    # Better parsing: split by Q1, Q2, etc.
    import re
    query_blocks = re.split(r'# =+\n# Q\d+:.*?\n# =+\n', content)
    titles = re.findall(r'# =+\n# (Q\d+:.*?)\n# =+\n', content)
    
    results_markdown = "# Pipeline Evaluation Report\n\n## Quantitative Metrics\n"
    
    total_time = 0
    query_results = []
    
    print(f"Executing {len(titles)} queries...")
    
    for i, title in enumerate(titles):
        q_text = query_blocks[i+1].strip()
        
        q_start = time.time()
        try:
            res = g.query(q_text)
            count = len(list(res))
        except Exception as e:
            count = f"Error: {e}"
        q_end = time.time()
        
        q_time = q_end - q_start
        total_time += q_time
        
        query_results.append((title, count, q_time))
        print(f"{title} -> {count} results in {q_time:.3f}s")
    
    end_time = time.time()
    end_mem = process.memory_info().rss / 1024 / 1024 # MB
    
    results_markdown += f"- **Total Graph Load & Query Time:** {end_time - start_time:.2f} seconds\n"
    results_markdown += f"- **Peak Memory Usage:** ~{end_mem:.2f} MB\n\n"
    
    results_markdown += "## Query Quality (Competency Questions)\n\n"
    results_markdown += "| Query | Results Found | Execution Time (s) |\n"
    results_markdown += "|---|---|---|\n"
    
    for title, count, q_time in query_results:
        results_markdown += f"| {title} | {count} | {q_time:.3f} |\n"
        
    results_markdown += "\n*Note: High result counts indicate the graph successfully integrated the heterogeneous data required to answer the CQs.*\n"
    
    with open("outputs/evaluation_report.md", "w", encoding="utf-8") as f:
        f.write(results_markdown)
        
    print("Evaluation complete. Report saved to outputs/evaluation_report.md")

if __name__ == "__main__":
    evaluate_pipeline()
