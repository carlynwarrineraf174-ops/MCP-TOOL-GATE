# 1. 指定基础镜像：使用官方精简版的 Python 3.12
# slim 版本体积小，不带多余的编译工具，适合生产环境
FROM python:3.12-slim

# 2. 设置环境变量
# 告诉 Python 不要在容器里生成 .pyc 缓存文件
ENV PYTHONDONTWRITEBYTECODE=1
# 告诉 Python 直接把日志输出到控制台（不缓冲），这样 docker logs 能看到实时日志
ENV PYTHONUNBUFFERED=1

# 3. 设置工作目录
# 相当于在容器里执行 mkdir /app && cd /app
WORKDIR /app

# 4. 先拷贝依赖文件（核心优化点）
# 为什么先拷 pyproject.toml？因为只要这个文件没变，Docker 就会使用缓存，
# 不会重新去 pip install，这能大大加快构建速度。
COPY pyproject.toml .

# 5. 安装依赖
# 注意：这里安装的是你的 govern 可选依赖，而不是全量
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -e ".[govern]"

# 6. 拷贝剩下的项目代码
COPY govern/ ./govern/
COPY examples/ ./examples/
COPY alembic/ ./alembic/
COPY alembic.ini .

# 7. 暴露端口
# 声明这个容器会用到 8000 端口（Prometheus 监控端口）
EXPOSE 8000

# 8. 容器启动时的默认命令
# 注意：Docker 不能直接跑 stdio 模式，因为 stdio 需要前台输入。
# 为了让容器在后台活着并提供服务，通常需要把协议转成 HTTP/SSE。
# 这里先用 proxy.py 占位，实际开发中你可能需要写一个 FastAPI 启动入口。
CMD ["python", "govern/proxy.py"]