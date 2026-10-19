# 本地测试报告

此目录保存 `backend/tests/run_isolated.py` 和 `backend/verification/` 生成的 JSON、日志等临时验收输出。报告文件默认由 Git 忽略；验收结论、截图和证据摘要统一保存在本地 `private-docs/verification/YYYY-MM-DD/<topic>/`，不随代码提交。

从仓库根目录运行隔离回归并保存报告：

```powershell
.\.venv\Scripts\python.exe -m backend.tests.run_isolated --report backend/reports/backend-regression.json
```

新报告使用小写英文 kebab-case 命名，日期统一为 `YYYY-MM-DD`，例如 `2026-10-19-backend-regression.json`。既有报告保留原始文件名和内容；原 `backend/test_reports/` 已整体迁入本目录。

隔离回归强制使用 Echo 和临时数据库。`backend/verification/` 中的人工验收工具可能调用真实模型或启动进程，运行前需阅读相应脚本的参数和用途。
