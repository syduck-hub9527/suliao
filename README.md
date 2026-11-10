# 塑料学习资料库（suliao）

一个人用的塑料行业学习平台：打开就有整理好的知识，搜一个词就能读到讲解，按学习路线一步步入行。

**当前版本：v0.6**（v0.6：原料篇——补齐 44 种塑料原料，牌号库扩到 191 个牌号、61 家厂商；v0.5：去掉价格功能）

---

## 这一版有什么

| 功能 | 说明 |
|---|---|
| 知识内容 | 原有 91 个入门/原料词条，并新增助剂知识词条：学习路线第 1 阶段“认识塑料行业”（18 个）、第 2 阶段“认识常见塑料”（21 个）、第 3 阶段“看懂牌号和物性表”（8 个：牌号、TDS、典型值与保证值、熔指、测试标准、干态与调湿、HDT、维卡）、第 4 阶段“认识更多塑料原料”（44 个：EVA、PMMA、MPPO、PC/ABS、PPA、PEEK、PPS、氟塑料、SBS/SEBS、TPV、POE、PLA、PBAT、环氧、酚醛等）；第 5 阶段助剂百科覆盖抗氧剂、光稳定剂、阻燃剂、润滑剂、加工助剂、增韧剂、相容剂、成核剂等 |
| 查牌号报价 | 牌号页有“去普拉司查报价”的链接，直接跳到这个牌号在普拉司网的供应商挂牌报价 |
| 牌号库 | 191 个常见牌号、61 家厂商，覆盖通用塑料、工程塑料、特种工程塑料、氟塑料、热塑性弹性体、生物降解塑料、热固性塑料。每个数字都附来源链接和测试条件，分“资料有官方出处（54 个）/ 转载的厂家资料（117 个）/ 资料待核实（20 个）”三档 |
| 原料总览 | `/materials/`：所有塑料原料按类别排好，每种原料能看到收录了几家厂商、几个牌号 |
| 厂商一览 | `/companies/`：按中国大陆、中国台湾、日本、韩国、东南亚、中东、欧洲、北美分组，点进去看这家厂的介绍、品牌和收录的全部牌号；原料词条页下面也有“常用厂商和牌号”表 |
| 牌号页面 | 特点与用途（讲清这个牌号能学到什么）→ 性能数据（按 TDS 习惯分组，保证值和典型值分开，尼龙分干态/调湿）→ 资料来源；词条页下面会列出这种材料的常见牌号，搜索牌号也能直接找到 |
| 词条页面 | 一句话解释 → 小白解释 → 专业内容 → 常见误区；附其他叫法、相关知识、细分类型；可以按学习路线点“上一个 / 下一个” |
| 专业词自动可点 | 正文里出现的其他词条名称、缩写、俗称会自动变成链接，鼠标放上去能看到一句话解释 |
| 搜索 | 中文名、英文名、缩写、俗称、CAS 号都能搜；名称里搜不到时也会在正文里找 |
| 学习路线 | 按阶段排好；每个词条可以标“学习中 / 还不懂 / 已掌握”，可以收藏；“还不懂”的会进生词本 |
| 分类浏览 | 按材料、术语等类别和分类树浏览 |
| 免登录 | 只有自己用，打开就直接进入 |
| 后台 | `/admin/` 可以修改任何内容；在后台改过的词条不会被自动导入覆盖 |

所有知识内容都由 AI 整理，页面上会标注“AI 整理 · 待核对”。涉及给客户的承诺、安全、食品接触、阻燃等级等重要结论，请以生产商最新的 TDS/SDS 和官方标准为准。

**后面的版本**：原料篇之后做助剂篇——按类别（增塑剂、抗氧剂、阻燃剂、光稳定剂、润滑剂、成核剂等）整理常用助剂和它们的厂商、牌号。

---

## 第一次部署（在服务器上操作）

前提：服务器已经装好 Docker，并且 mihomo 代理在 `127.0.0.1:7890` 上运行。

**1. 让 git 访问 GitHub 时走代理**（只对 github.com 生效）

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
nano .env
```

把 `DJANGO_SECRET_KEY=` 后面换成第二条命令输出的那串随机字符。保存按 `Ctrl+O` 再回车，退出按 `Ctrl+X`。然后：

```
chmod 600 .env
```

**4. 先单独下载 Python 基础镜像**

构建镜像时，Docker 去官方仓库查基础镜像这一步不会走代理，国内服务器会超时。先用 `docker pull`（它会走代理）把基础镜像下载到本机，构建时就直接用本机的：

```
docker pull python:3.12-slim
```

**5. 构建并启动**

```
docker compose up -d --build
docker compose logs --tail 30 web
```

日志里出现 `知识导入完成：……`、`牌号导入完成：……` 和 `Listening at: http://0.0.0.0:8000`，就成功了。

---

## 怎么打开网站

网站只在服务器本机（`127.0.0.1:8000`）上运行，外面访问不到。你在自己电脑上用 **SSH 隧道**访问，SSH 登录就是这道“门”，所以网站本身不需要登录。

**1.** 在你的电脑上打开终端（Windows 用 PowerShell），执行：

```
ssh -L 8000:127.0.0.1:8000 admin@你的服务器公网IP
```

登录后**保持这个窗口别关**。

**2.** 浏览器打开 <http://127.0.0.1:8000>。

想同时打开 mihomo 面板，可以一条命令开两个隧道：

```
ssh -L 8000:127.0.0.1:8000 -L 9090:127.0.0.1:9090 admin@你的服务器公网IP
```

---

## 以后怎么更新

```
cd ~/suliao
git pull
docker compose up -d --build
```

数据库结构有变化时会自动升级，新的知识内容会自动导入。你的学习进度、收藏和在后台改过的内容都会保留。久几分钟。

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
| 手动重新导入知识 | `docker compose exec web python manage.py load_content` |
| 运行自测 | `docker compose exec web python manage.py test kb` |

---

## 重要注意事项

1. **永远不要执行 `docker compose down -v`**。加了 `-v` 会删除数据卷，学习进度和你改过的内容会全部消失。
2. **网站只能通过 SSH 隧道访问**。免登录模式下，如果把 `.env` 里的 `DJANGO_ALLOWED_HOSTS` 改成公网地址，网站会拒绝启动，这是故意的保护。
3. **`.env` 只放在服务器上**。这个仓库是公开的，`.env` 已经在 `.gitignore` 里排除，不会被提交。
4. **数据存在哪**：在 Docker 数据卷 `suliao_suliao-data` 里，位于系统盘上，阿里云快照会一起备份。大改动之前先打快照。
5. **基础镜像下载失败**：如果 `docker pull python:3.12-slim` 也失败，可以在 `.env` 里加一行 `PYTHON_IMAGE=镜像站地址/python:3.12-slim`，换一个能访问的镜像站。

---

## 知识内容怎么加

知识写在 `content/` 目录的 Markdown 文件里，格式见 [content/README.md](content/README.md)。
牌号写在 `content/grades/` 目录的 YAML 文件里，格式和“每个数字必须有出处”的规矩见 [content/grades/README.md](content/grades/README.md)。
容器启动时两者都会自动导入，重复导入是安全的；在后台改过的词条和牌号不会被覆盖。

---

## 项目结构

```
suliao/
├── content/                知识内容（Markdown），按学习路线分目录
│   └── grades/             牌号库数据（YAML）
├── config/                 Django 项目设置
├── kb/                     主应用
│   ├── models.py           数据库的 22 张表
│   ├── content.py          知识文件的读取和导入
│   ├── grades_import.py    牌号文件的读取和导入
│   ├── render.py           正文渲染、专业词自动加链接
│   ├── search.py           搜索
│   ├── views.py            页面
│   ├── middleware.py       免登录模式
│   ├── admin.py            后台
│   ├── templates/kb/       页面模板
│   ├── migrations/         数据库结构升级脚本（含预置数据）
│   ├── management/         命令：load_content 导入知识和牌号
│   └── tests.py            自动测试（45 项）
├── templates/admin/        后台页面的小调整
├── docker/entrypoint.sh    网站容器启动：升级数据库 → 导入知识 → 启动网站
├── Dockerfile
├── docker-compose.yml
├── .env.example            配置模板
└── requirements.txt
```

技术栈：Python 3.12 · Django 5.2 · SQLite · Gunicorn · WhiteNoise · Markdown · Docker。

开发约定：只有一个 `main` 分支，代码直接推送到 `main`。
