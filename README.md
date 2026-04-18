# 人亚校园墙

一个基于 `FastAPI + SQLAlchemy + Jinja2` 的轻量校园墙项目，支持前台浏览、用户互动、后台发帖管理，以及基于 `LangChain` 的 AI 图文总结。

## 功能概览

- 前台帖子列表与详情页
- 普通用户注册、登录、退出
- 登录用户点赞、评论
- 管理员后台登录与发帖
- 支持多图上传
- 支持视频上传
- 帖子详情页 AI 一键总结
- AI 可结合正文、图片、点赞数、评论内容生成简短总结
- 管理员后台可强制重新生成 AI 总结

## 技术栈

- Python 3.10+
- FastAPI
- SQLAlchemy
- Jinja2
- SQLite
- LangChain
- langchain-openai

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

在项目根目录创建 `.env` 文件，最少建议配置这些内容：

```env
SECRET_KEY=replace-with-a-long-random-string
SITE_NAME=人亚校园墙
ADMIN_USERNAME=admin

AI_SUMMARY_API_KEY=your_api_key
AI_SUMMARY_MODEL=qwen3.5-flash
AI_SUMMARY_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
```

如果暂时不想启用 AI 总结，可以先不填 `AI_SUMMARY_API_KEY` 和 `AI_SUMMARY_BASE_URL`。

### 3. 初始化管理员

```bash
python scripts/init_admin.py
```

脚本会提示你输入管理员用户名和密码。

### 4. 启动项目

开发环境推荐：

```bash
python run.py
```

或者：

```bash
uvicorn app.main:app --reload
```

默认地址：

- 首页：`http://127.0.0.1:8000/`
- 用户登录：`http://127.0.0.1:8000/login`
- 用户注册：`http://127.0.0.1:8000/register`
- 管理后台：`http://127.0.0.1:8000/admin/login`

## AI 总结说明

### 能力范围

AI 总结会综合以下信息：

- 帖子标题
- 帖子正文
- 最多若干张图片
- 点赞数
- 最近若干条评论内容

### 用户侧规则

- 未登录用户不能使用 AI 总结
- 每个用户对同一帖子只能使用一次
- 如果该帖子已经存在缓存总结，用户第一次使用时会直接读取缓存，不会重复调用模型

### 管理员侧规则

- 管理员可以在后台强制重新生成 AI 总结
- 强制重生成会覆盖原有总结内容
- 后台支持显示“生成中”状态，刷新页面后状态仍然保留

### AI 相关环境变量

```env
AI_SUMMARY_API_KEY=your_api_key
AI_SUMMARY_BASE_URL=https://api.openai.com/v1
AI_SUMMARY_MODEL=gpt-4.1-mini
AI_SUMMARY_TIMEOUT=45
AI_SUMMARY_TEMPERATURE=0.2
AI_SUMMARY_MAX_IMAGES=3
AI_SUMMARY_MAX_IMAGE_BYTES=5242880
AI_SUMMARY_MAX_TEXT_CHARS=4000
```

说明：

- `AI_SUMMARY_BASE_URL` 支持 OpenAI 兼容接口
- `AI_SUMMARY_MODEL` 按你的服务商实际模型名填写
- 默认会读取最多 3 张图片

## 数据库说明

默认使用 SQLite，数据库文件位置：

```text
data/wall.db
```

项目启动时会自动：

- 创建缺失的数据表
- 补齐旧库缺失字段
- 补齐 AI 总结相关字段和使用记录表

这意味着旧版本数据通常可以直接继续使用。

## 上传规则

### 图片

- 支持格式：`jpg` `jpeg` `png` `webp` `gif`
- 最多上传：9 张
- 单张默认限制：10MB

### 视频

- 支持格式：`mp4` `webm` `mov` `m4v`
- 最多上传：3 个
- 单个默认限制：100MB

相关配置都可以在 [app/config.py](/d:/news/wal/wall_mvp/wall_src/app/config.py:1) 中调整。

## 常用环境变量

```env
DATABASE_URL=sqlite:///data/wall.db
SECRET_KEY=replace-with-a-long-random-string
SESSION_COOKIE_NAME=wall_session
UPLOAD_DIR=app/static/uploads
MAX_UPLOAD_FILES=9
MAX_SINGLE_FILE_MB=10
MAX_VIDEO_FILES=3
MAX_SINGLE_VIDEO_MB=100
SITE_NAME=人亚校园墙
ADMIN_USERNAME=admin
```

## 生产部署建议

### 直接运行

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 推荐生产方式

- 使用 `systemd` 托管 `uvicorn`
- 使用 `Nginx` 反向代理到 `127.0.0.1:8000`
- 通过域名和 HTTPS 对外提供服务

## 日志

当前项目会输出：

- FastAPI / Uvicorn 请求日志
- AI 总结业务日志
- 是否命中缓存
- 是否真正请求了大模型
- 使用的模型名、图片数、评论数等上下文信息

## 项目结构

```text
wall_src/
├─ app/
│  ├─ auth.py
│  ├─ config.py
│  ├─ db.py
│  ├─ main.py
│  ├─ models.py
│  ├─ routers/
│  │  ├─ admin.py
│  │  └─ public.py
│  ├─ services/
│  │  └─ ai_summary.py
│  ├─ static/
│  │  ├─ css/
│  │  │  └─ style.css
│  │  ├─ js/
│  │  │  ├─ admin_ai_summary.js
│  │  │  └─ post_ai_summary.js
│  │  ├─ uploads/
│  │  └─ favicon.ico
│  └─ templates/
│     ├─ admin_login.html
│     ├─ admin_new_post.html
│     ├─ admin_posts.html
│     ├─ base.html
│     ├─ index.html
│     ├─ post_detail.html
│     ├─ user_login.html
│     └─ user_register.html
├─ data/
├─ scripts/
│  └─ init_admin.py
├─ requirements.txt
├─ run.py
└─ README.md
```

## 开发提示

- 本地开发优先使用 `python run.py`
- 如果修改了模型字段，应用启动时会自动尝试补齐 SQLite 字段
- 如果 AI 总结不可用，先检查 `.env` 中的 `AI_SUMMARY_API_KEY`、`AI_SUMMARY_BASE_URL`、`AI_SUMMARY_MODEL`
- 如果在 Windows 上遇到时区问题，项目已经内置了 `UTC+8` 回退逻辑

## License

项目根目录保留了原始 `LICENSE` 文件，使用时请按对应许可处理。
