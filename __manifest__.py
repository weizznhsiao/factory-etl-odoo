{
    'name': 'Factory Order ETL',
    'version': '1.0',
    'category': 'Sales',
    'summary': 'Parse brand order files (Adidas, Nike, NB) into ERP horizontal template',
    'description': """
        Provides a persistent model to upload raw order files and a customer mapping table,
        processes them in-memory, and provides a formatted Excel file for ERP import.
    """,
    'author': 'Antigravity',
    'depends': ['base'],
    'external_dependencies': {
        'python': ['pandas', 'openpyxl', 'xlrd', 'pyxlsb', 'pdfplumber'],
    },
    'data': [
        'security/ir.model.access.csv',
        'views/etl_type_views.xml',
        'views/etl_job_views.xml',
        'views/etl_wizard_views.xml',
    ],
    'installable': True,
    'application': True,
}
