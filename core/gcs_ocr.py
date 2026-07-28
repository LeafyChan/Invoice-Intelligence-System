import os
from google.cloud import storage, documentai_v1 as documentai

GCS_BUCKET = os.environ.get("GCS_BUCKET", "invoice-intel-staging-apac")
DOCAI_PROJECT = os.environ.get("BQ_PROJECT_ID", "apac-01072016")
DOCAI_LOCATION = os.environ.get("DOCAI_LOCATION", "asia-southeast1")
DOCAI_PROCESSOR_ID = os.environ.get("DOCAI_PROCESSOR_ID", "a8adef76e59d012e")

def upload_to_gcs(local_path: str, doc_type: str) -> str:
    client = storage.Client()
    bucket = client.bucket(GCS_BUCKET)
    filename = os.path.basename(local_path)
    blob = bucket.blob(f"{doc_type}/{filename}")
    blob.upload_from_filename(local_path)
    return f"gs://{GCS_BUCKET}/{doc_type}/{filename}"

def ocr_with_documentai(gcs_uri: str) -> str:
    client = documentai.DocumentProcessorServiceClient(
        client_options={"api_endpoint": f"{DOCAI_LOCATION}-documentai.googleapis.com"}
    )
    name = f"projects/{DOCAI_PROJECT}/locations/{DOCAI_LOCATION}/processors/{DOCAI_PROCESSOR_ID}"
    request = documentai.ProcessRequest(
        name=name,
        gcs_document=documentai.GcsDocument(
            gcs_uri=gcs_uri,
            mime_type="application/pdf"
        )
    )
    result = client.process_document(request=request)
    return result.document.text