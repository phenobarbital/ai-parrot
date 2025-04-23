from navconfig import BASE_DIR
from .plot import create_plot
from .eda import quick_eda, generate_eda_report, list_available_dataframes
from .gamma import gamma_link


report_dir = BASE_DIR.joinpath('static', 'reports')
