<div align="center">

<img src="logo.png" alt="LightCloud Logo" width="320">

# ☁️ LightCloud — VPS Bot

**Fully automated Discord bot for managing LXC/LXD-based VPS containers.**

Creation • Resizing • Suspension • Port Forwarding • Multi-Node • Admin Controls — all from Discord.

![Hosting](https://img.shields.io/badge/Hosting-LightCloud-2f8fff?style=for-the-badge)
![Python](https://img.shields.io/badge/Python-3-2f8fff?style=for-the-badge&logo=python&logoColor=white)
![LXC](https://img.shields.io/badge/LXC%2FLXD-Powered-4aa3ff?style=for-the-badge)

</div>

---

## 📋 Requirements

- A fresh Ubuntu or Debian server (root access)
- A Discord Bot Token ([Discord Developer Portal](https://discord.com/developers/applications))
- Your Discord User ID (main admin)
- `git` installed (`sudo apt install git -y` if missing)

## 🚀 Installation

Clone the repo and run the installer as root:

```bash
git clone https://github.com/lightcloudsupport/vps-bot.git
cd vps-bot
chmod +x install.sh
sudo ./install.sh
```

Then follow the prompts:

1. Choose your OS (Ubuntu / Debian).
2. Enter your **Discord Bot Token** and **Main Admin Discord ID**.

> Not using GitHub? Place `bot.py` and `install.sh` in the same folder on your server and run `sudo ./install.sh`.

The installer will:

- Install and initialize LXD/LXC
- Install Python 3, pip, and required packages (`discord.py`, `requests`)
- Copy `bot.py` to `/root/bot.py`
- Create and enable a `bot.service` systemd unit so the bot runs 24/7 and restarts on failure or reboot

## 🛠️ Managing the Bot

| Action            | Command                      |
| ----------------- | ---------------------------- |
| Check status      | `systemctl status bot`       |
| View live logs    | `journalctl -u bot -f`       |
| Restart           | `sudo systemctl restart bot` |
| Stop              | `sudo systemctl stop bot`    |
| Disable autostart | `sudo systemctl disable bot` |

## ⚙️ Configuration

Environment variables live in `/etc/systemd/system/bot.service`. After editing, apply them with:

```bash
sudo systemctl daemon-reload
sudo systemctl restart bot
```

| Variable               | Description                                                              | Default      |
| ---------------------- | ------------------------------------------------------------------------ | ------------ |
| `DISCORD_TOKEN`        | Your bot's token                                                         | — (required) |
| `MAIN_ADMIN_ID`        | Your Discord user ID. Multiple IDs allowed, comma-separated (`id1,id2`)  | — (required) |
| `BOT_NAME`             | Display name used in embeds                                              | `LightCloud` |
| `PREFIX`               | Command prefix                                                           | `!`          |
| `VPS_USER_ROLE_ID`     | Role ID granted to VPS owners                                            | —            |
| `DEFAULT_STORAGE_POOL` | LXD storage pool name                                                    | `default`    |
| `LOGO_URL`             | Public image link for the logo shown in embeds                           | LightCloud logo |

Set the hosting name like this:

```ini
Environment="BOT_NAME=LightCloud"
```

## 👑 Admin Management

- `!admin-add @user` / `!admin-remove @user` — manage regular admins by mention (main admin only).
- `!add-admin <user_id>` / `!rm-admin <user_id>` — manage **main admins** by raw Discord ID (main admin only). At least one main admin is always kept.
- `!admin-list` — shows all main admins and regular admins.

Admins are stored in the database (seeded from `MAIN_ADMIN_ID`), so changes persist across restarts.

## 📝 Notes

- The bot runs as **root** because it manages LXC containers directly. Keep your bot token and server access secured.
- `vps.db` (SQLite) is created automatically in `/root` on first run and stores nodes, VPS records, admins, and settings.
- Run `!help` in Discord after the bot is online to see the full command list.

---

<div align="center">

**☁️ LightCloud** — Fast. Reliable. Always online.

Based on [vps-deploy-bot-v1](https://github.com/evilsaad0-hash/vps-deploy-bot-v1) by EVILSAAD

</div>
