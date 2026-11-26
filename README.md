# Telegram 媒体提取 bot

贴一条 Telegram 消息链接给它，它把**原图 / 原视频 / 原文件**发回给你。

- 任何你能看到的会话都行：公开频道、私密群、付费群、加密群的链接
- 付费媒体的「模糊预览」→ 只要你的账号已解锁，拿到的是清晰原版
- 相册（一次多张）会整组取回
- 大文件自动存进你的「收藏夹」

> 原理：bot 只是聊天窗口，真正干活的是**你自己的账号**。所以凡是你手机上能看到的，它都能下。

---

## 第一步：准备两个东西

### 1) API_ID 和 API_HASH

1. 浏览器打开 <https://my.telegram.org>，用你的手机号登录（验证码会发到 Telegram 里）
2. 点 **API development tools**
3. 随便填：App title 填 `extract`，Short name 填 `extract`，Platform 选 **Other**
4. 提交后页面会出现 `App api_id`（一串数字）和 `App api_hash`（一串字母数字）

### 2) BOT_TOKEN

1. Telegram 里搜索 **@BotFather**，点开始
2. 发 `/newbot`
3. 名字随便填，比如 `My Extract`
4. 用户名必须以 `bot` 结尾，比如 `mypic_extract_bot`
5. 它会给你一串 `123456789:AA...` 的东西，这就是 BOT_TOKEN

---

## 第二步：跑起来（复制粘贴，两行）

打开「终端」App，整段复制下面这行，回车：

```bash
cd ~/telegram-extract && ./start.sh
```

第一次运行会依次问你：

1. `API_ID（纯数字）` → 粘贴第一步的数字，回车
2. `API_HASH` → 粘贴，回车
3. `BOT_TOKEN` → 粘贴，回车
4. `请输入你的电话号码` → 格式 `+8613800000000`，回车
5. `Please enter the code` → Telegram 会收到验证码，填进来，回车
6. 有两步验证密码的话，再输一次密码

看到这行就成功了：

```
✅ 已启动：以 @你的用户名 的身份运行，服务 1 个用户
```

**这个终端窗口别关**，关了 bot 就停了。

---

## 第三步：手机上用

1. 在 Telegram 里找到你刚创建的 bot（就是 BOT_TOKEN 对应的那个），点 **Start**
2. 在任意频道/群里，长按一条消息 → **复制链接**
3. 把链接发给 bot

支持的链接格式：

```
https://t.me/频道名/123
https://t.me/c/1234567890/123
tg://openmessage?chat_id=-1001234567890&message_id=77
```

---

## 常见问题

**Q：发回来的是模糊的？**
说明这条是付费媒体，而你的账号还没解锁（没付过钱）。bot 会在消息里提示。付款解锁后重新发一次链接就是清晰版。

**Q：文件很大怎么办？**
bot 直传上限 50MB。超过的会自动上传到你的**收藏夹**（Saved Messages），bot 会告诉你。iOS 上收藏夹就是那个「Saved Messages」对话。

**Q：提示「找不到这个群」？**
`t.me/c/…` 这种链接只有**你账号在群里**才能读。确认这个群你还待着（没退、没被踢）。

**Q：bot 不回消息了？**
终端窗口被关了 / Mac 睡眠了。重新跑 `cd ~/telegram-extract && ./start.sh`。

**Q：会不会封号？**
用的是官方 MTProto 协议，正常频率（一次发一两个链接）不会有问题。别拿它批量刷几千条。

---

## 加第二个账号（多账号）

bot 可以同时挂多个账号，取文件时**自动用那个恰好在群里**的账号。所以你想让主号以后进的群也能用，就把主号也加进来。

```bash
cd ~/telegram-extract && ./start.sh add
```

然后**在手机上用主号**：Telegram → 设置 → 设备 → 关联桌面设备 → 扫终端里的二维码。

扫码不需要短信，+86 号也能过。扫完会自动把这个号加进白名单。

用手机号加（不走扫码）：

```bash
cd ~/telegram-extract && ./start.sh add-phone
```

---

## 换成服务器常驻（可选，想 24 小时在线才需要）

买台 VPS（1 核 1G 就够），装好 Docker 后：

```bash
# 把整个 telegram-extract 文件夹传到服务器，然后在里面执行
docker compose up -d --build
docker compose logs -f
```

注意：`data/` 目录里是你的登录凭证（`user.session`），**别外传**。在服务器上首次登录需要在服务器上跑一次 `./start.sh` 完成验证码验证。

---

## 目录说明

```
start.sh          一键启动
tgextract/        源码
  login.py        首次登录向导
  bot.py          主程序
  extract.py      解析链接、下载媒体
  links.py        链接格式解析
data/             登录凭证 + 临时文件（敏感，别外传）
.env              你的配置（自动生成）
```
