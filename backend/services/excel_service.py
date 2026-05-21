import pandas as pd
from io import BytesIO
from typing import List
from models.schemas import Candidate

REQUIRED_COLUMNS = {"name", "phone"}


def parse_excel(file_bytes: bytes) -> List[Candidate]:
    df = pd.read_excel(BytesIO(file_bytes))
    df.columns = [c.strip().lower() for c in df.columns]

    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"Excel is missing required columns: {missing}")

    df = df.dropna(subset=["name", "phone"])
    df["phone"] = df["phone"].astype(str).str.strip().str.replace(r"\D", "", regex=True)

    return [
        Candidate(
            id=idx,
            name=str(row["name"]).strip(),
            phone=str(row["phone"]).strip(),
        )
        for idx, row in df.iterrows()
    ]


def export_excel(candidates: List[Candidate]) -> bytes:
    rows = [
        {
            "Name": c.name,
            "Phone": c.phone,
            "Status": c.status.value,
            "Overall Satisfaction": c.overall_satisfaction or "",
            "Would Recommend": c.would_recommend or "",
            "Issues Faced": c.issues_faced or "",
            "Suggestions": c.suggestions or "",
            "Call Duration (s)": c.call_duration or "",
            "Error": c.error_message or "",
        }
        for c in candidates
    ]

    df = pd.DataFrame(rows)
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Survey Results")
        ws = writer.sheets["Survey Results"]
        for col in ws.columns:
            max_len = max(len(str(cell.value or "")) for cell in col) + 4
            ws.column_dimensions[col[0].column_letter].width = min(max_len, 55)
    output.seek(0)
    return output.read()