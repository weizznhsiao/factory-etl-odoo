from odoo import models, fields

class ETLType(models.Model):
    _name = 'factory.order.etl.type'
    _description = 'Factory Order ETL Type'

    name = fields.Char(string="訂單種類名稱", required=True)

    template_file = fields.Binary(string="目標匯出格式 (Excel)", required=True)
    template_filename = fields.Char(string="匯出格式檔名")
