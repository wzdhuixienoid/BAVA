# 独立分析代码沙箱

## 执行边界

银行 Agent 默认只选择预注册工具，不在 API 或 Worker 进程执行模型代码。自定义／生成的 Python 分析代码通过独立命令入口运行，每次新建受限容器。它不能调用银行写工具，没有数据库、认证器、LLM key 或账户凭据，也不挂载项目目录。沙箱结果只是分析产物，不能作为银行余额、到账或授权证据。

入口为 [run_code_sandbox.py](../../scripts/run_code_sandbox.py)，宿主编排见 [code_sandbox.py](../../apps/api/src/banking_api/security/code_sandbox.py)，唯一执行任意代码的解释器在 [容器 runner](../../infra/sandbox/runner.py) 中。银行 Compose 不挂载 Docker socket，不能为了使用此入口给银行 API 添加宿主 Docker 权限。

## 隔离与资源控制

| 边界 | 控制 |
| --- | --- |
| 文件 | 无宿主挂载、根文件系统只读；仅8MB临时目录可写，设置 noexec／nosuid／nodev |
| 网络 | 每任务 `--network none`，无银行或外部网络 |
| 身份 | 非 root UID/GID 65532，移除全部 Linux capabilities，禁止获得新权限 |
| 资源 | 内存及交换总额128MB、CPU配额0.5、CPU时间2秒、进程数32、文件描述符64、文件大小64KB |
| 时间与输入输出 | 代码≤16KB、请求≤32KB、标准输出／错误各≤64KB、默认墙钟5秒；超限停止并删除容器 |
| 日志与清理 | Docker 不保留任务输出日志；无论成功或失败，清理精确任务名的容器 |
| 失败关闭 | Docker或镜像不可用返回 UNAVAILABLE，不退回宿主 `exec` 或子进程 Python |

Docker 与操作系统内核属于信任边界，容器隔离不能等同于独立虚拟机或已通过生产渗透测试。构建镜像需依赖可信基础镜像；正式发布应固定经过审查的镜像摘要。

## 构建、运行与监控

在根目录执行，输入仅使用明确选择的合成或脱敏聚合数据：

```bash
docker build -t banking-analysis-sandbox:1.0.1 infra/sandbox
PYTHONPATH=apps/api/src apps/api/.venv/bin/python scripts/run_code_sandbox.py \
  --code infra/sandbox/example.py --input infra/sandbox/example-input.json \
  --audit /private/tmp/banking-sandbox-audit.jsonl
```

示例合计为65.00，计数为3。审计 JSONL 记录任务ID、代码及输入 SHA-256、状态和执行时长，不保留代码、输入或分析结果正文。调用方负责将审计保存在有访问控制的位置。若宿主异常导致清理失败，可以按 `banking.disposable-analysis=true` 标签检查残余容器，不能清理其他业务容器。

## 验证

```bash
RUN_DOCKER_SANDBOX_TESTS=1 APP_ENVIRONMENT=test AUTH_MODE=development \
  apps/api/.venv/bin/python -m pytest apps/api/tests/test_code_sandbox.py -m sandbox -q
```

测试实际检查正常计算、只读文件系统、未挂载文件、断网、输出洪泛、内存限制和超时；无 Docker 的默认回归还检查失败关闭和禁止宿主挂载等配置约束。
