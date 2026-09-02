from document_processor import extract_document


class ContractIntakeAutomation:
    """Orchestrates intake through review preparation; never makes a human decision."""

    def __init__(self, database, analyzer):
        self.database = database
        self.analyzer = analyzer

    def run(self, attachments: list[dict]):
        result = {
            "found": len(attachments), "review_ready": [], "analyzed_only": [],
            "skipped": [], "errors": [], "human_review_required": True,
        }
        for attachment in attachments:
            key = {
                "gmail_msg_id": attachment["gmail_msg_id"],
                "attachment_id": attachment["attachment_id"],
                "filename": attachment["filename"],
            }
            if self.database.gmail_attachment_import_exists(
                attachment["gmail_msg_id"], attachment["attachment_id"]
            ):
                result["skipped"].append({**key, "reason": "already_imported"})
                continue
            try:
                text, sha256 = extract_document(attachment["filename"], attachment["data"])
                document = self.database.get_document_by_sha256(sha256)
                if not document:
                    analysis = self.analyzer.analyze_document(attachment["filename"], text)
                    document, _, _ = self.database.save_document(
                        attachment["filename"], attachment.get("mime_type"), sha256, text, analysis
                    )
                self.database.link_gmail_attachment(document["id"], attachment)

                candidate, reference, selection_error = self.database.select_trusted_reference(
                    document["id"]
                )
                if selection_error == "no_match":
                    result["analyzed_only"].append({
                        **key, "document_id": document["id"],
                        "next_step": "Assign a trusted reference",
                    })
                    continue
                if selection_error:
                    raise ValueError("Document could not be prepared for trusted comparison")

                stored = self.database.get_document_comparison_by_hashes(
                    candidate["sha256"], reference["sha256"]
                )
                duplicate_comparison = stored is not None
                if not stored:
                    comparison = self.analyzer.compare_documents(
                        candidate["filename"], candidate["extracted_text"],
                        reference["filename"], reference["extracted_text"],
                    )
                    stored, _, _ = self.database.save_document_comparison(
                        candidate["filename"], candidate["sha256"],
                        reference["filename"], reference["sha256"], comparison,
                    )
                self.database.link_comparison_sources(
                    stored["id"], candidate["id"], reference["id"]
                )
                result["review_ready"].append({
                    **key, "document_id": document["id"],
                    "comparison_id": stored["id"],
                    "trusted_reference_id": reference["trusted_reference_id"],
                    "reference_document_id": reference["id"],
                    "reference_label": reference["label"],
                    "duplicate_comparison": duplicate_comparison,
                    "next_step": "Human approve, request revision, or reject",
                })
            except Exception as exc:
                result["errors"].append({**key, "error": str(exc)})
        return result
