from odoo import models, fields, api, exceptions
import base64
import logging

from ..core.etl_process import process_orders_in_memory

_logger = logging.getLogger(__name__)


class ETLWizard(models.TransientModel):
    _name = 'factory.order.etl.wizard'
    _description = 'Factory Order ETL Wizard'

    state = fields.Selection([
        ('upload', '上傳'),
        ('done', '完成')
    ], default='upload', string="狀態")

    order_type_id = fields.Many2one('factory.order.etl.type', string="訂單種類", required=True)

    order_files = fields.Many2many(
        'ir.attachment',
        'etl_wizard_attachment_rel',
        'wizard_id',
        'attachment_id',
        string="原始訂單檔案 (Excel / PDF)",
        help="可一次選取多個 Excel (.xls, .xlsx, .xlsb) 或 PDF 檔案"
    )

    output_file = fields.Binary(string="匯出結果", readonly=True)
    output_filename = fields.Char(string="匯出結果檔名", readonly=True)

    log_summary = fields.Text(string="執行日誌", readonly=True)

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
            self.output_filename = "橫式匯入_Output.xlsx"
            self.log_summary = log_summary
            self.state = 'done'

            return {
                'type': 'ir.actions.act_window',
                'res_model': 'factory.order.etl.wizard',
                'view_mode': 'form',
                'res_id': self.id,
                'target': 'new',
            }

        except exceptions.UserError:
            raise
        except Exception as e:
            _logger.error("ETL Wizard Error", exc_info=True)
            raise exceptions.UserError(f"An unexpected error occurred: {str(e)}")
