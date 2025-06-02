# Copyright (C) 2025 WeSolved BV <https://wesolved.com>
# @author Miro Tasevski <miro.tasevski@wesolved.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import fields, models


class StockpilotChannelMapping(models.Model):
    _name = "stockpilot.channel.mapping"
    _description = "Stockpilot Channel Mapping"

    config_id = fields.Many2one("stockpilot.configuration")
    stockpilot_channel = fields.Char(string="Stockpilot Channel Name")
    odoo_team_id = fields.Many2one(
        "crm.team", string="Odoo Sales Team", domain=[("team_type", "=", "sales")]
    )
