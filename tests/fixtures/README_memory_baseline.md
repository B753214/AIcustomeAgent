# memory_baseline.jsonl

Memory-M0-3 基线用例。每行一条 JSON。

- 路径：`tests/fixtures/memory_baseline.jsonl`
- 状态字段 `baseline_status` 描述**当前系统**（2026-09）：`pass` | `partial` | `fail`
- 改造后应用同一文件对比，目标是隔离/追问/长上下文等从 fail→pass

校验单行：

```bash
python -c "import json; p='tests/fixtures/memory_baseline.jsonl';
print(sum(1 for _ in open(p,encoding='utf-8')));
[json.loads(l) for l in open(p,encoding='utf-8') if l.strip()]; print('ok')"
```
