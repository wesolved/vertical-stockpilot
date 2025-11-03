# Copyright (C) 2025 WeSolved BV <https://wesolved.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import models


class ResPartner(models.Model):
    _inherit = "res.partner"


    def _get_stockpilot_partner(self, partner, parent_partner=False):
        """
        Get or create a contact/partner for a Stockpilot order.

        Args:
            partner (dict): Dictionary of partner fields and
            values (may contain 'country' as ISO code).
            parent_partner (recordset, optional): Parent partner
            to assign (for company/contact structure).

        Returns:
            recordset: The found or created res.partner record.
        """
        partner_domain = []
        partner_obj = {}
        for key, value in partner.items():
            if key == "country":
                country_id = self.env["res.country"].search([("code", "=", value)])
                value = country_id.id
                key = "country_id"
            partner_domain.append((key, "=", value))
            partner_obj[key] = value

        if parent_partner:
            partner_domain.append(("parent_id", "=", parent_partner.id))
            partner_obj["parent_id"] = parent_partner.id
            
        partner_id = self.env["res.partner"].search(partner_domain)

        if not partner_id:
            partner_id = self.env["res.partner"].create(partner_obj)

        return partner_id
