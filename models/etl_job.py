from odoo import models, fields, api, exceptions
import base64
import logging

from ..core.etl_process import process_orders_in_memory

_logger = logging.getLogger(__name__)


class ETLJob(models.Model):
    _name = 'factory.order.etl.job'
    _description = 'Factory Order ETL Job'
    _order = 'create_date desc'

    name = fields.Char(string="作業編號", required=True, copy=False, readonly=True, default=lambda self: 'New')

    state = fields.Selection([
        ('draft', '草稿'),
        ('done', '完成')
    ], default='draft', string="狀態", tracking=True)

    order_type_id = fields.Many2one('factory.order.etl.type', string="訂單種類", required=True)

    order_files = fields.Many2many(
        'ir.attachment',
        'etl_job_attachment_rel',
        'job_id',
        'attachment_id',
        string="原始訂單檔案 (Excel / PDF)",
        help="可一次選取多個 Excel (.xls, .xlsx, .xlsb) 或 PDF 檔案"
    )

    output_file = fields.Binary(string="匯出結果", readonly=True)
    output_filename = fields.Char(string="匯出結果檔名", readonly=True)

    log_summary = fields.Text(string="執行日誌", readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('factory.order.etl.job') or 'Job'
        return super().create(vals_list)

    def action_process(self):
        self.ensure_one()

        try:
            if not self.order_type_id.template_file:
                raise exceptions.UserError("所選訂單種類缺少匯出格式範本檔案，請先至「訂單種類設定」上傳範本。")

            template_bytes = base64.b64decode(self.order_type_id.template_file)

            if not self.order_files:
                raise exceptions.UserError("請至少上傳一個訂單檔案（Excel 或 PDF）。")

            # Collect uploaded files
            order_files = []
            for attachment in self.order_files:
                if not attachment.datas:
                    continue
                file_bytes = base64.b64decode(attachment.datas)
                order_files.append((attachment.name, file_bytes))

            if not order_files:
                raise exceptions.UserError("找不到有效的訂單檔案內容，請確認上傳的檔案正確。")

            # Process ETL in memory (no mapping table — parser is auto-detected)
            output_bytes, log_summary = process_orders_in_memory(
                order_files=order_files,
                template_bytes=template_bytes
            )

            if output_bytes is None:
                raise exceptions.UserError(f"ETL 處理失敗：\n{log_summary}")

            self.output_file = base64.b64encode(output_bytes)
            self.output_filename = f"{self.order_type_id.name}_匯出結果.xlsx"
            self.log_summary = log_summary
            self.state = 'done'

        except exceptions.UserError:
            raise
        except Exception as e:
            _logger.error("ETL Job Error", exc_info=True)
            raise exceptions.UserError(f"An unexpected error occurred: {str(e)}")
