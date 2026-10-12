"""
LightCloud - !manage control panel (button layout) + command module.

This file lives in the `commands/` folder next to bot.py. Every .py file in this
folder (except ones starting with "_") is loaded automatically when the bot starts.
To add more commands, drop another file here with an `async def setup(bot)` function.

`core` is bot.py itself (bot.py registers itself under that name), so all of the
bot's helpers - execute_lxc, create_embed, vps_data, ... - are available as core.<name>.
"""
import asyncio
import os
import re
import shlex
from datetime import datetime

import discord
from discord.ext import commands

import core  # = bot.py

B = discord.ButtonStyle
CPANEL_URL = os.getenv('CPANEL_URL', '').strip()
USER_CAN_DELETE = os.getenv('USER_CAN_DELETE', '1').strip().lower() not in ('0', 'false', 'no')


def _txt(out) -> str:
    """execute_lxc returns True when there is no output."""
    return "" if out is True or out is None else str(out)


def _code(text: str, limit: int = 3500) -> str:
    text = text.replace("```", "'''")
    if len(text) > limit:
        text = "..." + text[-limit:]
    return f"```\n{text if text.strip() else '(no output)'}\n```"


def _is_admin_user(user_id) -> bool:
    uid = str(user_id)
    return uid in core.main_admin_ids or uid in core.admin_data.get("admins", [])


# --------------------------------------------------------------------------- #
#  Modals (File Manager / VPS Console)
# --------------------------------------------------------------------------- #
class _InputModal(discord.ui.Modal):
    def __init__(self, mode: str, container: str, node_id: int):
        titles = {"files": "File Manager", "console": "VPS Console"}
        super().__init__(title=titles[mode])
        self.mode = mode
        self.container = container
        self.node_id = node_id
        if mode == "files":
            self.field = discord.ui.TextInput(
                label="Folder or file path", default="/root", max_length=200)
        else:
            self.field = discord.ui.TextInput(
                label="Command (non-interactive, 60s limit)",
                style=discord.TextStyle.paragraph, placeholder="e.g. apt update && uname -a",
                max_length=500)
        self.add_item(self.field)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        c, nid = self.container, self.node_id
        value = self.field.value.strip()
        try:
            if self.mode == "files":
                p = shlex.quote(value or "/")
                script = (f"if [ -d {p} ]; then ls -lah --group-directories-first {p}; "
                          f"elif [ -f {p} ]; then head -c 1800 {p} | cat -v; "
                          f"else echo 'Path not found'; fi")
                out = _txt(await core.execute_lxc(c, f"exec {c} -- bash -c {shlex.quote(script)}", timeout=30, node_id=nid))
                embed = core.create_info_embed("📁 File Manager", f"`{value or '/'}` on `{c}`\n{_code(out)}")
            else:
                out = _txt(await core.execute_lxc(c, f"exec {c} -- bash -lc {shlex.quote(value)}", timeout=60, node_id=nid))
                embed = core.create_info_embed("🖥️ VPS Console", f"`$ {value[:200]}`\n{_code(out)}")
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            await interaction.followup.send(embed=core.create_error_embed("Failed", _code(str(e), 1500)), ephemeral=True)


# --------------------------------------------------------------------------- #
#  Delete confirmation
# --------------------------------------------------------------------------- #
class _ConfirmDelete(discord.ui.View):
    def __init__(self, panel, owner_id: str, actual_idx: int):
        super().__init__(timeout=60)
        self.panel = panel
        self.owner_id = owner_id
        self.actual_idx = actual_idx

    @discord.ui.button(label="Yes, delete permanently", style=B.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        try:
            vps = core.vps_data[self.owner_id][self.actual_idx]
            c = vps["container_name"]
            nid = vps.get("node_id", 1)
            try:
                await core.execute_lxc(c, f"delete {c} --force", node_id=nid)
            except Exception as e:
                if not any(x in str(e).lower() for x in ("not found", "does not exist", "no such")):
                    raise
            conn = core.get_db()
            cur = conn.cursor()
            cur.execute("DELETE FROM vps WHERE container_name = ?", (c,))
            cur.execute("DELETE FROM port_forwards WHERE vps_container = ?", (c,))
            conn.commit()
            conn.close()
            del core.vps_data[self.owner_id][self.actual_idx]
            if not core.vps_data[self.owner_id]:
                del core.vps_data[self.owner_id]
                if interaction.guild:
                    member = interaction.guild.get_member(int(self.owner_id))
                    role = await core.get_or_create_vps_role(interaction.guild)
                    if member and role and role in member.roles:
                        try:
                            await member.remove_roles(role, reason="No VPS ownership")
                        except discord.Forbidden:
                            pass
            core.save_vps_data()
            self.panel.stop()
            await interaction.followup.send(embed=core.create_success_embed("VPS Deleted", f"`{c}` was deleted."), ephemeral=True)
            try:
                await self.panel.message.edit(embed=core.create_warning_embed("VPS Deleted", f"`{c}` no longer exists."), view=None)
            except Exception:
                pass
        except Exception as e:
            await interaction.followup.send(embed=core.create_error_embed("Delete Failed", str(e)), ephemeral=True)

    @discord.ui.button(label="Cancel", style=B.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Cancelled.", embed=None, view=None)


# --------------------------------------------------------------------------- #
#  The panel
# --------------------------------------------------------------------------- #
class LightManageView(core.ManageView):
    """Same logic as the original ManageView, new button layout + extra actions."""

    NEW_ACTIONS = {"restart", "network", "logs", "backup", "password", "files",
                   "sshx", "console", "cpanel", "health", "delete", "refresh"}

    def _btn(self, label, emoji, style, action, row):
        b = discord.ui.Button(label=label, emoji=emoji, style=style, row=row)

        async def cb(interaction, _a=action):
            await self.action_callback(interaction, _a)
        b.callback = cb
        self.add_item(b)

    def add_action_buttons(self):
        owner = not self.is_shared and not self.is_admin
        full = not self.is_shared
        can_delete = full and (USER_CAN_DELETE or self.is_admin)

        # Row 0
        if owner:
            self._btn("Reinstall", "🔄", B.danger, "reinstall", 0)
        self._btn("Start", "▶️", B.success, "start", 0)
        self._btn("Stop", "⏸️", B.secondary, "stop", 0)
        self._btn("Restart", "🔁", B.primary, "restart", 0)
        self._btn("Stats", "📊", B.secondary, "stats", 0)
        # Row 1
        self._btn("Network", "🌐", B.primary, "network", 1)
        self._btn("Console Logs", "📜", B.secondary, "logs", 1)
        if full:
            self._btn("Backup", "💾", B.success, "backup", 1)
            self._btn("Password", "🔑", B.primary, "password", 1)
            self._btn("File Manager", "📁", B.primary, "files", 1)
        # Row 2
        self._btn("SSH", "🔐", B.primary, "tmate", 2)
        if full:
            self._btn("SSHX", "🌐", B.primary, "sshx", 2)
            self._btn("Tunnel", "🔄", B.primary, "reconnect_tunnel", 2)
            self._btn("VPS Console", "🖥️", B.primary, "console", 2)
            self._btn("cPanel", "🌐", B.secondary, "cpanel", 2)
        # Row 3
        self._btn("Health Check", "🩺", B.success, "health", 3)
        if full:
            self._btn("Change Password", "🔁", B.primary, "changepass", 3)
        if can_delete:
            self._btn("Delete VPS", "🗑️", B.danger, "delete", 3)
        self._btn("Refresh", "🔄", B.secondary, "refresh", 3)

    # ----------------------------------------------------------------- #
    async def action_callback(self, interaction: discord.Interaction, action: str):
        if action not in self.NEW_ACTIONS:
            return await super().action_callback(interaction, action)

        if str(interaction.user.id) != self.user_id and not self.is_admin:
            return await interaction.response.send_message(
                embed=core.create_error_embed("Access Denied", "This is not your VPS!"), ephemeral=True)
        if self.selected_index is None:
            return await interaction.response.send_message(
                embed=core.create_error_embed("No VPS Selected", "Please select a VPS first."), ephemeral=True)

        actual_idx = self.actual_index if self.is_shared else self.indices[self.selected_index]
        vps = core.vps_data[self.owner_id][actual_idx]
        c = vps["container_name"]
        nid = vps["node_id"]
        suspended = vps.get("suspended", False)

        if action == "refresh":
            await interaction.response.defer()
            embed = await self.create_vps_embed(self.selected_index)
            return await interaction.edit_original_response(embed=embed, view=self)

        if suspended and not self.is_admin:
            return await interaction.response.send_message(
                embed=core.create_error_embed("Access Denied", "This VPS is suspended. Contact an admin to unsuspend."), ephemeral=True)

        # Modals must be the first response
        if action in ("files", "console"):
            return await interaction.response.send_modal(_InputModal(action, c, nid))

        if action == "delete":
            if not (self.is_admin or USER_CAN_DELETE) or self.is_shared:
                return await interaction.response.send_message(
                    embed=core.create_error_embed("Access Denied", "You can't delete this VPS."), ephemeral=True)
            warn = core.create_warning_embed(
                "Delete VPS", f"⚠️ This permanently deletes `{c}` and **all its data**, backups and port forwards.\nThis cannot be undone.")
            return await interaction.response.send_message(
                embed=warn, view=_ConfirmDelete(self, self.owner_id, actual_idx), ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        send = lambda embed: interaction.followup.send(embed=embed, ephemeral=True)

        try:
            if action == "restart":
                try:
                    await core.execute_lxc(c, f"stop {c}", timeout=120, node_id=nid)
                except Exception:
                    pass  # already stopped
                await core.safe_start_container(c, nid)
                vps["status"] = "running"
                core.save_vps_data()
                await core.apply_internal_permissions(c, nid)
                readded = await core.recreate_port_forwards(c)
                await send(core.create_success_embed("VPS Restarted", f"`{c}` restarted. Re-added {readded} port forwards."))
                await self._refresh_panel()

            elif action == "network":
                out = _txt(await core.execute_lxc(c, f"list {c} -c 4 --format csv", node_id=nid))
                embed = core.create_info_embed("🌐 Network", f"Network info for `{c}`")
                core.add_field(embed, "Internal IPv4", _code(out, 500), False)
                if vps.get("pinggy_address"):
                    host, port = vps["pinggy_address"].split(":")
                    core.add_field(embed, "SSH Tunnel", f"`ssh root@{host} -p {port}`", False)
                forwards = [f for f in core.get_user_forwards(self.owner_id) if f["vps_container"] == c]
                if forwards:
                    ip = core.get_public_ip()
                    lines = [f"`{ip}:{f['host_port']}` → VPS:{f['vps_port']}" for f in forwards[:10]]
                    core.add_field(embed, "Port Forwards", "\n".join(lines), False)
                await send(embed)

            elif action == "logs":
                try:
                    out = _txt(await core.execute_lxc(c, f"exec {c} -- journalctl -n 40 --no-pager", timeout=30, node_id=nid))
                except Exception:
                    out = _txt(await core.execute_lxc(c, f"console {c} --show-log", timeout=30, node_id=nid))
                await send(core.create_info_embed("📜 Console Logs", f"Latest logs for `{c}`\n{_code(out)}"))

            elif action == "backup":
                name = f"backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
                await core.execute_lxc(c, f"snapshot {c} {name}", timeout=300, node_id=nid)
                await send(core.create_success_embed(
                    "Backup Created",
                    f"Snapshot `{name}` of `{c}` was created.\nAn admin can restore it with `{core.PREFIX}restore-snapshot {c} {name}`."))

            elif action == "password":
                pw = vps.get("root_password")
                if pw:
                    await send(core.create_info_embed("🔑 Root Password", f"User: `root`\nPassword: ||`{pw}`||\n\nKeep it private."))
                else:
                    await send(core.create_warning_embed("No Password Stored", "Use **Change Password** to set a new one."))

            elif action == "sshx":
                script = ("rm -f /tmp/sshx.log; command -v curl >/dev/null || (apt-get update -y && apt-get install -y curl) "
                          ">/dev/null 2>&1; nohup sh -c 'curl -sSf https://sshx.io/get | sh -s run' >/tmp/sshx.log 2>&1 </dev/null &")
                await core.execute_lxc(c, f"exec {c} -- bash -c {shlex.quote(script)}", timeout=90, node_id=nid)
                link = ""
                for _ in range(8):
                    await asyncio.sleep(3)
                    log = _txt(await core.execute_lxc(
                        c, f"exec {c} -- bash -c {shlex.quote('cat /tmp/sshx.log 2>/dev/null')}", timeout=15, node_id=nid))
                    m = re.search(r"https://sshx\.io/s/[A-Za-z0-9_#\-]+", log)
                    if m:
                        link = m.group(0)
                        break
                if link:
                    await send(core.create_success_embed("SSHX Ready", f"Open this link in your browser:\n{link}\n\nKeep it private."))
                else:
                    await send(core.create_error_embed("SSHX Failed", "Couldn't get a link. The VPS may have no internet access."))

            elif action == "cpanel":
                if CPANEL_URL:
                    await send(core.create_info_embed("🌐 cPanel", f"Open your panel: {CPANEL_URL}"))
                else:
                    await send(core.create_warning_embed("cPanel Not Set Up", "No panel is configured on this host yet."))

            elif action == "health":
                stats = await core.get_container_stats(c, nid)
                issues, fixed = [], []
                if stats["status"] != "running":
                    issues.append("VPS is not running")
                    try:
                        await core.safe_start_container(c, nid)
                        vps["status"] = "running"
                        core.save_vps_data()
                        await core.apply_internal_permissions(c, nid)
                        await core.recreate_port_forwards(c)
                        fixed.append("Started the VPS")
                    except Exception as e:
                        issues.append(f"Auto-start failed: {e}")
                if stats["cpu"] > 90:
                    issues.append(f"High CPU usage ({stats['cpu']:.0f}%)")
                if stats["ram"]["pct"] > 90:
                    issues.append(f"High memory usage ({stats['ram']['pct']:.0f}%)")
                if not vps.get("pinggy_address"):
                    issues.append("No SSH tunnel - press Tunnel")
                embed = (core.create_success_embed if not issues else core.create_warning_embed)(
                    "🩺 Health Check", f"Results for `{c}`")
                core.add_field(embed, "Status", "✅ Everything looks healthy" if not issues else "\n".join(f"⚠️ {i}" for i in issues), False)
                if fixed:
                    core.add_field(embed, "Auto-repaired", "\n".join(f"🔧 {f}" for f in fixed), False)
                core.add_field(embed, "Usage", f"CPU {stats['cpu']:.1f}% • RAM {stats['ram']['pct']:.1f}% • Disk {stats['disk']}", False)
                await send(embed)
                if fixed:
                    await self._refresh_panel()
        except Exception as e:
            await send(core.create_error_embed("Action Failed", _code(str(e), 1500)))

    async def _refresh_panel(self):
        try:
            embed = await self.create_vps_embed(self.selected_index)
            await self.message.edit(embed=embed, view=self)
        except Exception:
            pass


# --------------------------------------------------------------------------- #
#  The command
# --------------------------------------------------------------------------- #
class ManageCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="manage")
    async def manage(self, ctx, user: discord.Member = None):
        """Open the VPS control panel."""
        if user:
            if not _is_admin_user(ctx.author.id):
                return await ctx.send(embed=core.create_error_embed("Access Denied", "Only admins can manage other users' VPS."))
            vps_list = core.vps_data.get(str(user.id), [])
            if not vps_list:
                return await ctx.send(embed=core.create_error_embed("No VPS Found", f"{user.mention} doesn't have any {core.BOT_NAME} VPS."))
            view = LightManageView(str(ctx.author.id), vps_list, is_admin=True, owner_id=str(user.id))
            embed = await view.get_initial_embed() if view.initial_embed or view.selected_index is not None else \
                core.create_info_embed(f"Managing {user.name}'s VPS", f"Managing VPS for {user.mention}")
        else:
            vps_list = core.vps_data.get(str(ctx.author.id), [])
            if not vps_list:
                embed = core.create_error_embed("No VPS Found", f"You don't have any {core.BOT_NAME} VPS. Contact an admin to create one.")
                core.add_field(embed, "Quick Actions", f"• `{core.PREFIX}manage` - Manage VPS\n• Contact admin for VPS creation", False)
                return await ctx.send(embed=embed)
            view = LightManageView(str(ctx.author.id), vps_list)
            embed = await view.get_initial_embed()
        view.message = await ctx.send(embed=embed, view=view)


async def setup(bot):
    await bot.add_cog(ManageCog(bot))
