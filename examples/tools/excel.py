import pandas as pd
from parrot.tools.excel import ExcelTool


# Example usage and testing
if __name__ == "__main__":
    # Create sample DataFrame
    data = {
        'Name': ['Alice', 'Bob', 'Charlie', 'Diana'],
        'Age': [25, 30, 35, 28],
        'Department': ['Engineering', 'Marketing', 'Sales', 'HR'],
        'Salary': [75000, 65000, 70000, 60000],
        'Start Date': ['2020-01-15', '2019-06-01', '2021-03-10', '2020-11-20']
    }
    df = pd.DataFrame(data)
    # Initialize the tool
    tool = ExcelTool(output_dir="./output")
    # Example 1: Basic Excel export with default styling
    result1 = tool._run(
        dataframe=df,
        output_filename="employee_data.xlsx",
        sheet_name="Employees"
    )
    print("Example 1:", result1)

    # Example 2: Excel with custom header styling
    header_styles = {
        'font_name': 'Arial',
        'font_size': 14,
        'bold': True,
        'font_color': 'FFFFFF',
        'background_color': '4472C4',
        'horizontal': 'center'
    }

    data_styles = {
        'font_name': 'Arial',
        'font_size': 11,
        'horizontal': 'left'
    }

    result2 = tool._run(
        dataframe=df,
        output_filename="styled_employee_data.xlsx",
        sheet_name="StyledEmployees",
        header_styles=header_styles,
        data_styles=data_styles
    )
    print("Example 2:", result2)

    # Example 3: ODS export
    result3 = tool._run(
        dataframe=df,
        output_filename="employee_data.ods",
        output_format="ods",
        sheet_name="Employees"
    )
    print("Example 3:", result3)
