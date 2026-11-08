# 塑料学习资料库（suliao）

一个人用的塑料行业学习与资料平台：词条百科、牌号与性能数据、技术文件、价格记录、学习笔记和问答记录。

**当前版本：v0.1**：数据库、录入后台、搜索。

---

## 这一版有什么

| 功能 | 说明 |
|---|---|
| 数据库 | 22 张表，分 6 组：知识百科、行业实体（公司/品牌/工厂/牌号）、性能数据、资料来源、价格行情、学习记录 |
| 录入后台 | 打开 `/admin/`，所有表都能增删改查、搜索、筛选 |
| 搜索首页 | 中文名、英文名、缩写、俗称、牌号、CAS 号都能搜；不区分大小写，空格、横杠不影响结果；模糊结果会单独标出来 |
| 预置数据 | 9 种公司类型、25 个常用性能指标（带单位和“必须记录的测试条件”提示） |
| 自测 | 22 项自动测试 |

**还没有做**：好看的前台页面、学习路线页面、价格图表、AI 读 PDF、批量导入、自动备份。后面一版一版加。

---

## 第一次部署（在服务器上操作）

前提：服务器已经装好 Docker，并且 mihomo 代理在 `127.0.0.1:7890` 上运行。

**1. 让 git 访问 GitHub 时走代理**（只对 github.com 生效，不影响别的）

```
git config --global http.https://github.com.proxy http://127.0.0.1:7890
```

**2. 下载代码**

```
cd ~
git clone https://github.com/syduck-hub9527/suliao.git
cd suliao
```

**3. 生成配置文件**

```
cp .env.example .env
python3 -c "import secrets; print(secrets.token_urlsafe(50))"
```

第二条命令会输出一长串随机字符，复制下来。然后编辑配置文件：

```
nano .env
```

改两行：
- `DJANGO_SECRET_KEY=` 后面换成刚才复制的那串字符
- `DJANGO_SUPERUSER_PASSWORD=` 后面换成你自己的登录密码（至少 8 位，不要太简单）

保存：按 `Ctrl+O`，回车；退出：按 `Ctrl+X`。最后把文件权限设成只有自己能看：

```
chmod 600 .env
```

**4. 构建并启动**

```
docker compose up -d --build
```

第一次要下载 Python 基础镜像和依赖库，需要几分钟。

**5. 确认启动成功**

```
docker compose ps
docker compose logs --tail 30 web
```

`STATUS` 显示 `Up`，并且日志里有 `已创建管理员 admin` 和 `Listening at: http://0.0.0.0:8000`，就成功了。

---

## 怎么打开网站

网站只在服务器本机（`127.0.0.1:8000`）上运行，外面访问不到，这样更安全。你在自己电脑上用 **SSH 隧道** 访问：

**1.** 在你的电脑上打开终端（Windows 用 PowerShell），执行：

```
ssh -L 8000:127.0.0.1:8000 admin@你的服务器公网IP
```

登录后**保持这个窗口别关**。

**2.** 浏览器打开 <http://127.0.0.1:8000>，用 `.env` 里设置的管理员账号和密码登录。

如果想同时打开 mihomo 面板，一条命令可以开两个隧道：

```
ssh -L 8000:127.0.0.1:8000 -L 9090:127.0.0.1:9090 admin@你的服务器公网IP
```

---

## 验收：试一下

1. 登录后，首页能看到统计数字和“常用操作”。
2. 点“+ 新建词条”：种类选“材料”，中文名填 `聚丙烯`，英文名填 `Polypropylene`，缩写填 `PP`。在下面的“别名”里加一条：写法填 `百折胶`，类型选“行业俗称”。点保存。
3. 回到首页，分别搜 `pp`、`聚丙烯`、`百折胶`，都能找到这个词条。

---

## 以后怎么更新

每次推送新代码后，在服务器上执行：

```
cd ~/suliao
git pull
docker compose up -d --build
```

数据不会丢。如果数据库结构有变化，启动时会自动升级。

---

## 常用命令

都在 `~/suliao` 目录下执行。

| 想做什么 | 命令 |
|---|---|
| 看运行状态 | `docker compose ps` |
| 看最近日志 | `docker compose logs --tail 50 web` |
| 实时看日志（按 Ctrl+C 退出） | `docker compose logs -f web` |
| 重启网站 | `docker compose restart web` |
| 停止网站 | `docker compose down` |
| 运行自测 | `docker compose exec web python manage.py test kb` |
| 修改管理员密码 | `docker compose exec web python manage.py changepassword admin` |

---

## 重要注意事项

1. **永远不要执行 `docker compose down -v`**。加了 `-v` 会删除数据卷，数据库和上传的文件会全部消失。
2. **`.env` 只放在服务器上**。这个仓库是公开的，任何人都能看到。`.env` 已经在 `.gitignore` 里排除，不会被提交。
3. **数据存在哪**：在 Docker 数据卷 `suliao_suliao-data` 里，位于服务器系统盘上。阿里云快照会把它一起备份，所以大改动之前先打快照。
4. **自动备份**：下一版加。

---

## 项目结构

```
suliao/
├── config/                 Django 项目设置（settings.py、urls.py）
├── kb/                     主应用
│   ├── models.py           22 张表的定义（数据库设计）
│   ├── admin.py            录入后台
│   ├── search.py           搜索逻辑
│   ├── views.py            首页/搜索页
│   ├── templates/kb/       页面模板
│   ├── migrations/         数据库结构升级脚本（含预置数据）
│   ├── management/         自定义命令（自动创建管理员）
│   └── tests.py            自动测试
├── docker/entrypoint.sh    容器启动脚本：升级数据库 → 创建管理员 → 启动网站
├── Dockerfile              镜像构建说明
├── docker-compose.yml      部署配置
├── .env.example            配置模板（复制成 .env 再改）
└── requirements.txt        Python 依赖
```

技术栈：Python 3.12 · Django 5.2 · SQLite · Gunicorn · WhiteNoise · Docker。

开发约定：只有一个 `main` 分支，代码直接推送到 `main`。
