"""discord.py bot: slash commands + Approve/Reject buttons for KS."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Callable

import discord
from discord import app_commands

from ks.config import AppConfig, load_config
from ks.device.fake import FakeDevice
from ks.discord.auth import member_has_write_role
from ks.discord.bridge import (
    execute_proposal,
    propose_gather_from_json,
    propose_gather_live,
)
from ks.discord.config import DiscordConfig, load_discord_config
from ks.discord.proposals import ProposalStore
from ks.models import NothingToDo, Proposal

log = logging.getLogger(__name__)

APPROVE_PREFIX = "ks:approve:"
REJECT_PREFIX = "ks:reject:"


class ConfirmView(discord.ui.View):
    """Approve / Reject buttons bound to a pending proposal id."""

    def __init__(self, proposal_id: str, *, timeout: float) -> None:
        super().__init__(timeout=timeout)
        self.proposal_id = proposal_id

        approve = discord.ui.Button(
            label="Approve",
            style=discord.ButtonStyle.success,
            custom_id=f"{APPROVE_PREFIX}{proposal_id}",
        )
        reject = discord.ui.Button(
            label="Reject",
            style=discord.ButtonStyle.danger,
            custom_id=f"{REJECT_PREFIX}{proposal_id}",
        )
        approve.callback = self._approve  # type: ignore[method-assign]
        reject.callback = self._reject  # type: ignore[method-assign]
        self.add_item(approve)
        self.add_item(reject)

    async def _approve(self, interaction: discord.Interaction) -> None:
        bot = interaction.client
        assert isinstance(bot, KSBot)
        await bot.handle_approve(interaction, self.proposal_id)

    async def _reject(self, interaction: discord.Interaction) -> None:
        bot = interaction.client
        assert isinstance(bot, KSBot)
        await bot.handle_reject(interaction, self.proposal_id)


class KSBot(discord.Client):
    """Always-on Discord client wired to KS gather propose/execute."""

    def __init__(
        self,
        discord_cfg: DiscordConfig,
        app_cfg: AppConfig,
        *,
        device_factory: Callable[[], object] | None = None,
    ) -> None:
        intents = discord.Intents.default()
        # message_content: optional chat awareness; enable in Dev Portal if used.
        intents.message_content = True
        # Invoker roles arrive on slash/button interactions without Members intent.
        super().__init__(intents=intents)
        self.discord_cfg = discord_cfg
        self.app_cfg = app_cfg
        self.store = ProposalStore(ttl_seconds=discord_cfg.proposal_ttl_seconds)
        self.tree = app_commands.CommandTree(self)
        self._device_factory = device_factory or self._default_device_factory
        self._proposals: dict[str, Proposal] = {}

    def _default_device_factory(self):
        if self.discord_cfg.candidates_json is not None:
            return FakeDevice()
        from ks.device.adb import AdbDevice

        serial = (
            self.app_cfg.adb.get("serial")
            if isinstance(self.app_cfg.adb, dict)
            else None
        )
        return AdbDevice.connect(serial=serial)

    async def setup_hook(self) -> None:
        self.tree.add_command(self._status_command())
        self.tree.add_command(self._gather_command())
        if self.discord_cfg.guild_id is not None:
            guild = discord.Object(id=self.discord_cfg.guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()

    def _status_command(self) -> app_commands.Command:
        @app_commands.command(name="status", description="KS bot status (read)")
        async def status(interaction: discord.Interaction) -> None:
            adb = self.app_cfg.adb if isinstance(self.app_cfg.adb, dict) else {}
            await interaction.response.send_message(
                f"KS Discord bot online.\n"
                f"dry_run={self.app_cfg.dry_run}\n"
                f"write_role=`{self.discord_cfg.write_role}`\n"
                f"adb.serial={adb.get('serial')!r}\n"
                f"candidates_json={self.discord_cfg.candidates_json}",
                ephemeral=True,
            )

        return status

    def _gather_command(self) -> app_commands.Command:
        @app_commands.command(
            name="gather",
            description="Propose a gather (requires write role; Approve/Reject)",
        )
        async def gather(interaction: discord.Interaction) -> None:
            member = interaction.user
            if not isinstance(member, discord.Member):
                await interaction.response.send_message(
                    "Gather is only available inside a server.",
                    ephemeral=True,
                )
                return
            if not member_has_write_role(member, self.discord_cfg.write_role):
                await interaction.response.send_message(
                    f"Denied: need role `{self.discord_cfg.write_role}`.",
                    ephemeral=True,
                )
                return

            await interaction.response.defer(ephemeral=False)
            try:
                proposal = self._build_proposal()
            except Exception as exc:  # noqa: BLE001
                log.exception("gather propose failed")
                await interaction.followup.send(f"Propose failed: {exc}")
                return

            if isinstance(proposal, NothingToDo):
                await interaction.followup.send(f"Nothing to do: {proposal.reason}")
                return

            pending = self.store.create(
                user_id=member.id,
                rationale=proposal.rationale,
                actions=proposal.actions,
            )
            self._proposals[pending.id] = proposal

            view = ConfirmView(
                pending.id,
                timeout=float(self.discord_cfg.proposal_ttl_seconds),
            )
            await interaction.followup.send(
                f"**Gather proposal**\n{proposal.rationale}\n"
                f"dry_run={self.app_cfg.dry_run}",
                view=view,
            )

        return gather

    def _build_proposal(self) -> Proposal | NothingToDo:
        if self.discord_cfg.candidates_json is not None:
            return propose_gather_from_json(
                self.discord_cfg.candidates_json,
                self.app_cfg,
            )
        device = self._device_factory()
        return propose_gather_live(device, self.app_cfg)

    async def handle_approve(
        self, interaction: discord.Interaction, proposal_id: str
    ) -> None:
        member = interaction.user
        if not isinstance(member, discord.Member):
            await interaction.response.send_message(
                "Approve only works in a server.", ephemeral=True
            )
            return
        if not member_has_write_role(member, self.discord_cfg.write_role):
            await interaction.response.send_message(
                f"Denied: need role `{self.discord_cfg.write_role}`.",
                ephemeral=True,
            )
            return

        pending = self.store.pop(proposal_id)
        proposal = self._proposals.pop(proposal_id, None)
        if pending is None or proposal is None:
            await interaction.response.send_message(
                "Proposal expired or already handled.", ephemeral=True
            )
            return

        await interaction.response.defer()
        try:
            device = self._device_factory()
            outcome = execute_proposal(device, proposal, self.app_cfg)
        except Exception as exc:  # noqa: BLE001
            log.exception("gather execute failed")
            await interaction.followup.send(f"Execute failed: {exc}")
            return

        if not outcome.ok:
            await interaction.followup.send(f"Execute failed: {outcome.message}")
            return
        await interaction.followup.send(f"Approved: {outcome.message}")

    async def handle_reject(
        self, interaction: discord.Interaction, proposal_id: str
    ) -> None:
        member = interaction.user
        if not isinstance(member, discord.Member):
            await interaction.response.send_message(
                "Reject only works in a server.", ephemeral=True
            )
            return
        if not member_has_write_role(member, self.discord_cfg.write_role):
            await interaction.response.send_message(
                f"Denied: need role `{self.discord_cfg.write_role}`.",
                ephemeral=True,
            )
            return

        pending = self.store.pop(proposal_id)
        self._proposals.pop(proposal_id, None)
        if pending is None:
            await interaction.response.send_message(
                "Proposal expired or already handled.", ephemeral=True
            )
            return
        await interaction.response.send_message("Rejected. No actions executed.")


def run_bot(
    *,
    discord_config_path: Path | None = None,
    app_config_path: Path | None = None,
) -> None:
    """Load configs and start the Discord gateway (blocking)."""
    discord_cfg = load_discord_config(discord_config_path)
    app_cfg = load_config(app_config_path)
    bot = KSBot(discord_cfg, app_cfg)
    bot.run(discord_cfg.token, log_handler=None)


def main(argv: list[str] | None = None) -> int:
    """CLI entry: ``ks-discord``."""
    parser = argparse.ArgumentParser(
        prog="ks-discord",
        description="Always-on Discord bot for KS gather propose/confirm.",
    )
    parser.add_argument(
        "--discord-config",
        type=Path,
        default=None,
        help="Path to config/discord.yaml",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to config/params.yaml",
    )
    args = parser.parse_args(argv)
    try:
        run_bot(discord_config_path=args.discord_config, app_config_path=args.config)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0
