from pathlib import Path
import subprocess
import requests

# Config
BASE_DIR      = Path(__file__).parent
INPUTS_DIR    = BASE_DIR / "inputs"
SUMMARIES_DIR = BASE_DIR / "summaries"
OUTPUTS_DIR   = BASE_DIR / "outputs"
SCHEMA_FILE   = BASE_DIR.parent / "tfl_template.yaml"
OLLAMA_MODEL  = "qwen2.5:3b"
ONTOGPT_MODEL = "ollama/qwen2.5:3b"
TARGET_CLASS  = "TflNetwork"
TARGET_CLASSES = [
    "Station", "Line", "Route", "ServiceDisruption",
    "InfrastructureProject", "TransportMode", "Zone"
]


def summarise_for_extraction(text: str, target_classes: list[str]) -> str:
    prompt = f"""You are preparing text for a knowledge graph extraction system.
Your job is to rewrite the following text as a concise list of factual statements.
Each statement must be on its own line in the format: "Subject: predicate object"
Focus only on facts relevant to these concepts: {', '.join(target_classes)}
Do not use markdown headers, bullet points, or prose paragraphs.
Only output the factual statements, nothing else.

Text:
{text}"""

    try:
        response = requests.post(
            "http://localhost:11434/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            timeout=120
        )
        response.raise_for_status()
        return response.json()["response"]
    except requests.exceptions.ConnectionError:
        raise RuntimeError("Ollama is not running. Start it with: ollama serve")
    except requests.exceptions.Timeout:
        raise RuntimeError("Ollama timed out — try a smaller input or faster model")


def run_pipeline():
    # Create output directories
    SUMMARIES_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

    input_files = list(INPUTS_DIR.glob("*.txt"))
    if not input_files:
        print(f"No .txt files found in {INPUTS_DIR}")
        return

    for txt_file in input_files:
        print(f"\n{'='*50}")
        print(f"Processing: {txt_file.name}")

        # Step 1: Summarise
        print("  Summarising...")
        with open(txt_file, encoding="utf-8") as f:
            raw = f.read()

        summarised = summarise_for_extraction(raw, TARGET_CLASSES)
        summary_path = SUMMARIES_DIR / f"{txt_file.stem}_summary.txt"
        with open(summary_path, "w", encoding="utf-8") as f:
            f.write(summarised)
        print(f"  Success: Summary saved to {summary_path}")

        # Step 2: Extract with OntoGPT
        output_path = OUTPUTS_DIR / f"{txt_file.stem}_extracted.ttl"

        result = subprocess.run([
            "ontogpt", "extract",
            "-i", str(summary_path),
            "-t", str(SCHEMA_FILE),
            "-o", str(output_path),
            "--target-class", TARGET_CLASS,
            "--model", ONTOGPT_MODEL,
            "--output-format", "turtle"  # add this
        ], capture_output=True, text=True)

        if result.returncode != 0:
            print(f"   OntoGPT failed for {txt_file.name}:")
            print(result.stderr)
        else:
            print(f"  Success: Extracted to {output_path}")

    print(f"\n{'='*50}")
    print("Pipeline complete.")


if __name__ == "__main__":
    run_pipeline()