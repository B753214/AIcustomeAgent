import pytest

from eval import run_knowledge_eval
from app.rag import retriever


@pytest.mark.asyncio
async def test_grade_answer_retries_invalid_structured_output(monkeypatch):
    class Judge:
        def __init__(self):
            self.calls = 0

        async def ainvoke(self, _prompt):
            self.calls += 1
            if self.calls == 1:
                raise ValueError("invalid structured output")
            return run_knowledge_eval.AnswerGrade(score=5, reason="correct")

    judge = Judge()

    class Model:
        def with_structured_output(self, _schema):
            return judge

    async def no_sleep(_delay):
        return None

    monkeypatch.setattr(retriever, "build_llm", lambda: Model())
    monkeypatch.setattr(run_knowledge_eval.asyncio, "sleep", no_sleep)

    result = await run_knowledge_eval.grade_answer("question", "reference", "answer")

    assert result.score == 5
    assert judge.calls == 2
