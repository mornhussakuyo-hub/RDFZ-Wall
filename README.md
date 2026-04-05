# 人亚校园墙（增强版）

这是在原始 MVP 基础上改出来的增强版校园墙，新增了这些能力：

- 管理员后台登录发帖
- 首页卡片直接展示封面 + 标题 + 摘要 + 点赞数 + 评论数
- 支持上传多张图片
- 支持上传视频
- 普通用户可注册 / 登录
- 登录用户可点赞
- 登录用户可评论
- 整体 UI 做了重新美化
- 预留网站图标支持：`app/static/favicon.ico`

---

## 1. 安装依赖

```bash
pip install -r requirements.txt
```

---

## 2. 初始化管理员

```bash
python scripts/init_admin.py
```

会提示你输入管理员用户名和密码。

---

## 3. 放置网站图标

把你自己的图标文件放到：

```text
app/static/favicon.ico
```

模板已经自动引用这个路径：

```html
<link rel="icon" href="/static/favicon.ico">
```

如果你已经有图标，直接覆盖进去就行。

---

## 4. 运行项目

### 开发模式

```bash
python run.py
```

或者：

```bash
uvicorn app.main:app --reload
```

默认地址：

- 前台首页：`http://127.0.0.1:8000/`
- 用户登录：`http://127.0.0.1:8000/login`
- 用户注册：`http://127.0.0.1:8000/register`
- 后台登录：`http://127.0.0.1:8000/admin/login`

---

## 5. 数据库说明

默认使用 SQLite：

```text
data/wall.db
```

项目启动时会自动检查并补齐新增表与新增字段。也就是说：

- 旧版数据库可以直接继续用
- 会自动补充 `users`、`comments`、`post_likes` 等表
- 会自动给 `posts` 表补 `videos_json` 字段

---

## 6. 上传规则

### 图片

- 格式：jpg / jpeg / png / webp / gif
- 最多：9 张
- 单张默认不超过：10MB

### 视频

- 格式：mp4 / webm / mov / m4v
- 最多：3 个
- 单个默认不超过：100MB

这些限制可以在 `app/config.py` 里改。

---

## 7. 项目结构

```text
wall_mvp/
├─ app/
│  ├─ main.py
│  ├─ config.py
│  ├─ db.py
│  ├─ models.py
│  ├─ auth.py
│  ├─ routers/
│  │  ├─ public.py
│  │  └─ admin.py
│  ├─ templates/
│  │  ├─ base.html
│  │  ├─ index.html
│  │  ├─ post_detail.html
│  │  ├─ user_login.html
│  │  ├─ user_register.html
│  │  ├─ admin_login.html
│  │  ├─ admin_new_post.html
│  │  └─ admin_posts.html
│  └─ static/
│     ├─ css/style.css
│     └─ favicon.ico   # 你自己放
├─ scripts/
│  └─ init_admin.py
├─ data/
├─ requirements.txt
└─ run.py
```

---