# AUTO-BUAA 课程独立签到助手 Pro - Linux & Docker 官方镜像
FROM python:3.11-slim

# 设置工作目录与时区（中国标准时间 CST / UTC+8）
WORKDIR /app
ENV TZ=Asia/Shanghai
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV HEADLESS=1

# 安装系统基础依赖与证书
RUN apt-get update && apt-get install -y --no-install-recommends \
    tzdata \
    ca-certificates \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

# 复制运行依赖并安装
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制核心源码、服务逻辑与前端静态资产
COPY core/ core/
COPY server/ server/
COPY run.py .
COPY config.json .

# 暴露 WebUI 默认访问端口
EXPOSE 18346

# 声明配置持久化挂载点
VOLUME ["/app/config.json"]

# 启动 Headless 跨网段 Web 服务
CMD ["python", "run.py", "--headless", "--host", "0.0.0.0", "--port", "18346"]
