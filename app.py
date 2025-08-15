import uuid
import os
import tempfile
from datetime import datetime
from typing import List

import boto3
from fastapi import FastAPI
from pydantic import BaseModel, Field
from reportlab.pdfgen import canvas

# Loading config from environment. Later will inject in Docker/EKS
AWS_REGION = os.getenv("AWS_REGION", "us-east-2")
# Table and bucket name are placeholders for now
TABLE_NAME = os.getenv("DDB_TABLE", "verdant-dev-invoices")
BUCKET = os.getenv("S3_BUCKET", "verdant-dev-invoices")

dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
table = dynamodb.Table(TABLE_NAME)
s3 = boto3.client("s3", region_name=AWS_REGION)

app = FastAPI()

@app.get("/health")
def health_check():
    return {"status": "ok"}

# Defining request body
class InvoiceItem(BaseModel):
    description: str = Field(..., example="Landscape Design")
    unit_cost: float = Field(..., example=250.0)
    quantity: int = Field(..., example=1)

class InvoiceRequest(BaseModel):
        quoteId: str = Field(..., example="1234-quote-uuid")
        type: str = Field(..., example="estimate")
        customerName: str = Field(..., example="Alice")
        items: List[InvoiceItem] = Field(...,
            description="Line items for the invoice"
        )

# Stubbing out the POST /invoices/generate endpoint
@app.post("/invoices/generate")
def generate_invoice(req: InvoiceRequest):
    # Generating a random invoice ID
    invoice_id = str(uuid.uuid4())
    key_prefix = "estimates" if req.type == "estimate" else "invoices"
    s3_key = f"{key_prefix}/{invoice_id}.pdf"

    # Creating PDF in a temp dir (works on Windows)
    tmp_dir = tempfile.gettempdir()
    pdf_path = os.path.join(tmp_dir, f"{invoice_id}.pdf")

    c = canvas.Canvas(pdf_path)
    # Header
    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, 800, f"Invoice: {invoice_id}")
    c.setFont("Helvetica", 12)
    c.drawString(50, 780, f"Quote ID: {req.quoteId}")
    c.drawString(50, 760, f"Customer: {req.customerName}")
    # Line Items
    y = 740
    for item in req.items:
        c.drawString(50, y, f"{item.quantity} x {item.description} @ ${item.unit_cost:.2f}")
        y -= 20
    c.drawString(50, y - 10, f"Generated: {datetime.utcnow().isoformat()}")
    c.save()

    # uploading to S3
    s3.upload_file(pdf_path, BUCKET, s3_key)

    # Writing metadata to DynamoDB
    table.put_item(Item = {
        "invoiceId": invoice_id,
        "quoteId": req.quoteId,
        "type": req.type,
        "pdfKey": s3_key,
        "createdAt": datetime.utcnow().isoformat(),
        "status": "generated"
    })

    # Returning a presigned URL thats valid for 1 hour
    url = s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": BUCKET, "Key": s3_key},
        ExpiresIn=3600
    )
    return {
        "invoice_id": invoice_id,
        "message": f"Received request for quote {req.quoteId} with {len(req.items)} items",
        "signedUrl": url
    }