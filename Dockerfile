# =================================================================
# 第一阶段：构建器 (Builder)
# 在此阶段准备所有依赖项，包括 Chrome 和 Python 包
# =================================================================
FROM python:3.13.5-slim AS builder

# 1. 设置环境变量
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    # 将 venv 加入 PATH，后续 pip 和 python 命令会使用它
    VIRTUAL_ENV=/opt/venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# 2. 安装“构建时”所需的工具
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    unzip \
    # 清理 apt 缓存
    && rm -rf /var/lib/apt/lists/*

# 3. 下载并解压 Chrome 和 Chromedriver
ARG CHROME_VERSION=139.0.7258.138
WORKDIR /build
RUN wget -q https://storage.googleapis.com/chrome-for-testing-public/${CHROME_VERSION}/linux64/chrome-linux64.zip \
 && wget -q https://storage.googleapis.com/chrome-for-testing-public/${CHROME_VERSION}/linux64/chromedriver-linux64.zip \
 && unzip chrome-linux64.zip \
 && unzip chromedriver-linux64.zip \
 && rm *.zip

# 4. 创建虚拟环境并安装 Python 依赖
# 这样做可以更好地利用缓存，只有 requirements.txt 变化时才重新安装
WORKDIR /app
RUN python3 -m venv $VIRTUAL_ENV
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt


# =================================================================
# 第二阶段：最终镜像 (Final Image)
# 这是最终交付的、轻量且安全的镜像
# =================================================================
FROM python:3.13.5-slim

# 1. 设置环境变量
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    VIRTUAL_ENV=/opt/venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# 2. 安装“运行时”必需的系统依赖
# [优化] 移除了所有构建工具 (wget, unzip) 和调试工具 (nano, vim)
RUN apt-get update && apt-get install -y --no-install-recommends \
    procps \
    bash \
    dos2unix \
    # 以下是 Chrome 运行必需的库
    ca-certificates \
    libasound2 libxkbcommon0 libglib2.0-0 libnss3 libgconf-2-4 \
    libfontconfig1 libatk-bridge2.0-0 libatk1.0-0 libcairo2 \
    libcups2 libdbus-1-3 libexpat1 libgbm1 libgdk-pixbuf2.0-0 \
    libnspr4 libpango-1.0-0 libx11-6 libx11-xcb1 libxcb1 \
    libxcomposite1 libxdamage1 libxext6 libxfixes3 libxrandr2 \
    libxss1 libfreetype6 libgtk-3-0 \
    # 清理 apt 缓存
    && rm -rf /var/lib/apt/lists/*

# 3. 从 builder 阶段复制预先准备好的文件
# [优化] 无需再次下载解压，直接复制结果
COPY --from=builder /build/chrome-linux64 /opt/chrome
COPY --from=builder /build/chromedriver-linux64/chromedriver /usr/local/bin/
COPY --from=builder /opt/venv /opt/venv

# 4. 创建 Chrome 的软链接，使其可以被直接调用
RUN chmod +x /usr/local/bin/chromedriver \
 && ln -s /opt/chrome/chrome /usr/bin/google-chrome \
 && ln -s /opt/chrome/chrome /usr/bin/google-chrome-stable

# 5. 设置工作目录并复制项目代码
WORKDIR /app
COPY . .

# 6. [优化] 添加非 root 用户，并赋予其工作目录权限，增强安全性
RUN useradd --create-home --shell /bin/bash appuser \
 && chown -R appuser:appuser /app
USER appuser

# 7. 处理脚本权限和换行符
# [注] dos2unix 的存在说明你的 Git 配置可能需要调整，建议使用 .gitattributes 统一换行符
RUN mkdir -p data/creator_db \
 && dos2unix ./xhs \
 && chmod +x ./xhs

# 8. 暴露端口
EXPOSE 9527

# 9. [优化] 设置正确的生产环境入口点
ENTRYPOINT ["python", "-m", "xhs_toolkit", "server", "start", "--host", "0.0.0.0", "--port", "9527"]