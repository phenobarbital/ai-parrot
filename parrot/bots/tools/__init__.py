from navconfig import BASE_DIR
from .plot import create_plot
from .eda import quick_eda, generate_eda_report, list_available_dataframes
from .pdf import generate_pdf_from_html


report_dir = BASE_DIR.joinpath('static', 'reports')
