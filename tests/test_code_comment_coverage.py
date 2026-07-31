"""核心教学源码的注释契约。

这不是追求所有函数都有 docstring 的形式主义检查。列表只覆盖面试和业务理解
所依赖的入口，防止重构时删掉解释系统边界的关键注释。
"""

import ast
from pathlib import Path


CORE_MODULES = [
    Path("app/api/dependencies.py"),
    Path("app/services/document_upload_service.py"),
    Path("app/services/extraction_service.py"),
    Path("app/services/review_service.py"),
    Path("app/services/candidate_matching_service.py"),
    Path("app/services/reconciliation_application_service.py"),
    Path("app/services/reconciliation_service.py"),
    Path("app/workers/extraction_worker.py"),
    Path("app/evaluation/runner.py"),
]

CORE_PUBLIC_TYPES = {
    Path("app/domain/extraction_tasks.py"): {"ExtractionTask"},
    Path("app/domain/extraction_runs.py"): {"ExtractionRun"},
    Path("app/domain/document_drafts.py"): {"DocumentDraft"},
    Path("app/domain/document_versions.py"): {"DocumentVersion"},
    Path("app/services/review_service.py"): {"ReviewService"},
    Path("app/services/reconciliation_application_service.py"): {
        "ReconciliationApplicationService"
    },
    Path("app/evaluation/runner.py"): {"ExtractionEvaluationRunner"},
}


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def test_core_learning_modules_explain_their_boundary() -> None:
    for path in CORE_MODULES:
        assert ast.get_docstring(_tree(path)), path


def test_core_business_types_have_teaching_docstrings() -> None:
    for path, required_names in CORE_PUBLIC_TYPES.items():
        classes = {
            node.name: node
            for node in _tree(path).body
            if isinstance(node, ast.ClassDef)
        }
        for name in required_names:
            assert name in classes, f"{path}: missing {name}"
            docstring = ast.get_docstring(classes[name])
            assert docstring and len(docstring) >= 20, f"{path}: {name}"


def test_comment_guide_links_the_end_to_end_source_path() -> None:
    guide = Path("docs/reference/18-code-comment-guide.md").read_text(
        encoding="utf-8"
    )
    required_sources = [
        "document_upload_service.py",
        "extraction_worker.py",
        "review_service.py",
        "candidate_matching_service.py",
        "reconciliation_service.py",
        "evaluation/runner.py",
    ]

    for filename in required_sources:
        assert filename in guide, filename
