from fastapi import FastAPI

from finpulse.pipeline import generate, run_gate_a

app = FastAPI(title="FINPULSE AI", version="0.1.0")


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/generate")
def generate_endpoint():
    key = generate()
    return {
        "canonical_cases": key["canonical_cases"],
        "physical_rows": key["physical_rows"],
        "row_counts": key["row_counts"],
        "planted_should_match": key["planted_should_match"],
        "planted_exceptions": key["planted_exceptions"],
        "exception_type_counts": key["exception_type_counts"],
    }


@app.post("/runs")
def create_run(reset: bool = True):
    return run_gate_a(reset=reset)
