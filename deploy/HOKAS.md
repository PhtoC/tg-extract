# 部署到 HOKAS（免费、无卡）

代码仓库：<https://github.com/PhtoC/tg-extract>

## 1. 注册

打开 <https://hokas.net> 注册（邮箱即可，不要卡）。

## 2. 新建服务器

- 面板 → New Server
- Runtime 选 **Python**
- 连 GitHub → 选仓库 `PhtoC/tg-extract`（授权一次）
- 名字随便

## 3. 填环境变量（Environment Variables）

逐条添加，值从下面复制：

```
API_ID=22124198
API_HASH=<见下方>
BOT_TOKEN=<见下方>
ALLOWED_USER_IDS=6819469472,8022790367
ZIP_PASSWORDS=666666
TASK_TIMEOUT=1800
STALL_TIMEOUT=60
TGX_SESSIONS=<长串，见下方>
```

`TGX_SESSIONS` 是登录态，很长（约 1450 字符），必须一次完整粘进去，不能换行。

## 4. 启动命令

```
python -u -m tgextract.bot
```

（仓库根目录有 `start-hokas.sh`、`Procfile`、`Dockerfile`，平台会自动识别依赖。）

## 5. 启动后

面板 Console 里应出现：

```
✅ 已启动，可用账号：8022790367, 6819469472；服务 2 个用户
```

这时手机发链接即可用。

## 注意

- 代码仓库是**公开**的，但 `.env`、session、密钥都没进仓库，凭证只在环境变量里
- 免费额度 256MB 内存，够用；别同时发几十个链接
- 平台要靠看广告续时长，记得定期续
- 会话失效（比如在手机上点“终止其他会话”）就要重新导出 `TGX_SESSIONS`
