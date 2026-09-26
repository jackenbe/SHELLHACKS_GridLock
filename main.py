from fastapi import FastAPI
from read_pdf import read_pdf
from pydantic import BaseModel
from overlap import find_overlaps, missing_coordinates, closest_km, Overlap

app = FastAPI()

table1 = []
table2 = []

class Path(BaseModel):
    path: str


@app.post("/create-path")
async def create_path(request: Path):
    table1 = read_pdf(request.path)
    print(table1)
    return {"words": table1}


# {
#     {"path": "v/data/using-data/georgia.pdf"}
# }