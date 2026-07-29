import io
import zipfile

from app.domain.parsing import ParseState
from app.infra.mineru_parser import MinerUPrecisionParser


class FakeDoneResult:
    state = "done"
    progress = 100
    markdown = "# TAX INVOICE"
    task_id = "task-456"
    images = []
    content_list = [
        {"type": "text", "page_idx": 0, "text": "TAX INVOICE"},
        {"type": "table", "page_idx": 0, "html": "<table></table>"},
    ]


class FakeMinerUClient:
    def submit(self, path: str, **options) -> str:
        with open(path, "rb") as handle:
            self.content = handle.read()
        self.options = options
        return "batch-123"

    def get_batch(self, batch_id: str):
        self.batch_id = batch_id
        return [FakeDoneResult()]


def test_submit_uses_vlm_english_ocr_and_tables() -> None:
    client = FakeMinerUClient()
    parser = MinerUPrecisionParser(client=client, timeout_seconds=600)
    result = parser.submit(
        filename="invoice.pdf",
        content_type="application/pdf",
        content=b"%PDF-1.7",
    )
    assert result.remote_job_id == "batch-123"
    assert client.content == b"%PDF-1.7"
    assert client.options == {
        "model": "vlm",
        "ocr": True,
        "table": True,
        "formula": False,
        "language": "en",
    }


def test_poll_maps_done_result_and_packages_artifacts() -> None:
    client = FakeMinerUClient()
    parser = MinerUPrecisionParser(client=client, timeout_seconds=600)
    result = parser.poll("batch-123")
    assert result.state == ParseState.SUCCEEDED
    assert result.result is not None
    assert result.result.markdown == "# TAX INVOICE"
    assert result.result.page_count == 1
    assert len(result.result.tables) == 1
    with zipfile.ZipFile(io.BytesIO(result.result.artifact_archive)) as archive:
        assert {"document.md", "content_list.json", "manifest.json"} <= set(
            archive.namelist()
        )


def test_poll_maps_failed_without_leaking_provider_message() -> None:
    class FailedClient:
        def get_batch(self, batch_id: str):
            result = type(
                "FailedResult",
                (),
                {"state": "failed", "progress": 72},
            )()
            return [result]

    parser = MinerUPrecisionParser(client=FailedClient())
    result = parser.poll("batch-123")
    assert result.state == ParseState.FAILED
    assert result.error_code == "MINERU_PARSE_FAILED"
    assert result.error_message == "MinerU could not parse the document"
